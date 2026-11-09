"""Formal asynchronous OA bridge.

This module deliberately calls the authoritative services directly. It does not
construct an adapter, make a loopback HTTP request, or fall back to mock data.
"""

from contextlib import contextmanager
from typing import Any

from sqlalchemy import or_, select

from ..core.errors import AppException, ErrorCode
from ..core.leave_types import leave_type_code
from ..core.context import get_trace_id, set_trace_id
from ..models.identity import OADepartment, OAUser
from ..models.oa_workflow import OAWorkflowOperation, OAWorkflowInstance, OAWorkflowVersion, OAWorkflowEvent, OAWorkflowOutbox
from ..models.oa_notification import OANotification, OANotificationDelivery, OANotificationAttempt
from ..models.oa_leave import OALeave, OALeaveVersion
from ..services import identity_service
from ..services.oa_access_service import OAAccessTarget, authorize_oa, builtin_actor, user_department
from ..services import oa_approval_service, oa_balance_service, oa_leave_service, oa_ticket_service, oa_workflow_service
from ..services.oa_command_service import OACommand, CommandOutcome, canonical_hash, run_command
from ..services.oa_access_service import denied, invalid
from ..services import oa_confirmation_service
from ..schemas.oa_leave import LeaveDraftPatch, SubmitLeaveCommand
from ..schemas.oa_bridge import BridgeApprovalDecision, BridgeLeaveEdit, BridgeLeaveSubmit, BridgeNotification
from ..services import oa_notification_source as notification_sources
from ..schemas.oa_workflow import DecideNodeCommand
from ..schemas.oa_ticket import FormalTicketProposal
from .gateway import BridgeContext


CORE_CAPABILITIES = (
    "get_user_context", "get_leave_case", "get_leave_balance", "get_approval_route",
    "create_or_update_approval", "get_approval_result", "edit_leave_case",
    "get_leave_edit_result", "create_or_merge_ticket", "get_ticket_result",
    "notify", "get_notification_result", "capabilities",
)
AUXILIARY_CAPABILITIES = ("get_ticket_status", "get_field_dict")


class BuiltinGateway:
    """Context-bound gateway for builtin OA identity and business services."""

    provider = "builtin"

    def __init__(self, context: BridgeContext):
        self.context = context

    @property
    def db(self):
        return self.context.session

    @property
    def actor(self):
        return self.context.actor

    async def _actor(self):
        return await builtin_actor(self.db, self.actor)

    @contextmanager
    def _trace_scope(self):
        previous = get_trace_id()
        set_trace_id(self.context.trace_id or previous)
        try:
            yield
        finally:
            set_trace_id(previous)

    async def capabilities(self) -> dict[str, Any]:
        await self._actor()
        return {
            "provider": self.provider,
            "capabilities": list(CORE_CAPABILITIES + AUXILIARY_CAPABILITIES),
            "trace_id": self.context.trace_id,
            "confirmation_bound": bool(self.context.confirmation_id),
        }

    async def get_user_context(self, user_id: str | None = None) -> dict[str, Any]:
        actor = await self._actor()
        user_id = user_id or actor.user_id
        if user_id != actor.user_id:
            from ..services.organization_service import _actor as organization_actor
            await organization_actor(self.db, actor, 'read')
        user = await self.db.scalar(select(OAUser).where(OAUser.id == user_id, OAUser.tenant_id == actor.tenant_id))
        if user is None:
            raise AppException(ErrorCode.FORBIDDEN, "无权访问该用户信息", http_status=403)
        department_id = await user_department(self.db, actor.tenant_id, user.id)
        department = await self.db.scalar(select(OADepartment).where(
            OADepartment.id == department_id, OADepartment.tenant_id == actor.tenant_id))
        fresh = await identity_service.current_identity(self.db, user)
        return {
            "user_id": fresh.user_id,
            "tenant_id": fresh.tenant_id,
            "name": fresh.data_scope.get("display_name", user.display_name),
            "dept_id": department_id,
            "dept_name": department.name if department else "",
            "roles": fresh.roles,
            "data_scope": fresh.data_scope,
        }

    async def _leave(self, business_id: str):
        actor = await self._actor()
        row = await self.db.scalar(select(OALeave).where(
            OALeave.tenant_id == actor.tenant_id,
            or_(OALeave.id == business_id, OALeave.business_no == business_id)))
        if row is None:
            raise AppException(ErrorCode.NOT_FOUND, "请假单不存在或不可访问", http_status=404)
        return actor, row

    async def get_leave_case(self, business_id: str) -> dict[str, Any]:
        actor, row = await self._leave(business_id)
        await authorize_oa(self.db, actor, "leave", "read", target=OAAccessTarget(
            actor.tenant_id, row.applicant_id, row.department_id))
        return await oa_leave_service.detail(self.db, actor, row.id)

    async def get_leave_balance(self, user_id: str | None = None, leave_type: str | None = None):
        actor = await self._actor()
        rows = await oa_balance_service.list_balances(self.db, actor, user_id)
        if leave_type is None:
            return rows
        matches = [row for row in rows if row.get("leave_type") == leave_type_code(leave_type)]
        if not matches:
            raise AppException(ErrorCode.NOT_FOUND, "未找到对应假期余额", http_status=404)
        return matches

    async def get_field_dict(self) -> dict[str, Any]:
        actor = await self._actor()
        available = await oa_workflow_service.list_definitions(self.db, actor, available=True, scene='leave')
        result = []
        for row in available:
            version = await oa_workflow_service.current_version(self.db, actor, row['id'], scene='leave')
            result.append(dict(id=row['id'], name=row['name'], workflow_version=version.version,
                form_version=version.form_version, rule_version=version.rule_version,
                form=version.package['form'], rules=version.package['rules']))
        return {'workflows': result}

    async def get_ticket_status(self, ticket_id: str) -> dict[str, Any]:
        actor = await self._actor()
        return await oa_ticket_service.detail(self.db, actor, ticket_id)

    async def get_ticket_result(self, idempotency_key: str):
        actor = await self._actor()
        return await oa_ticket_service.get_result(self.db, actor, idempotency_key)

    async def get_approval_route(self, business_id: str):
        actor, leave = await self._leave(business_id)
        await oa_leave_service.applicant_access(self.db, actor, leave.id)
        from ..schemas.oa_leave import NormalizedLeaveFields
        if leave.submission_version and leave.state not in oa_leave_service.EDITABLE:
            snapshot = await self.db.scalar(select(OALeaveVersion).where(
                OALeaveVersion.tenant_id == actor.tenant_id, OALeaveVersion.leave_id == leave.id,
                OALeaveVersion.version == leave.submission_version))
            if snapshot is None:
                raise invalid('请假提交版本缺失，请人工核对')
            version = await self.db.scalar(select(OAWorkflowVersion).where(
                OAWorkflowVersion.tenant_id == actor.tenant_id, OAWorkflowVersion.id == snapshot.workflow_version_id))
            instance = await self.db.scalar(select(OAWorkflowInstance).where(
                OAWorkflowInstance.tenant_id == actor.tenant_id, OAWorkflowInstance.leave_version_id == snapshot.id))
            if version is None or instance is None:
                raise invalid('请假流程快照缺失，请人工核对')
            route_nodes, pause_reasons = instance.route_snapshot, [instance.pause_reason] if instance.pause_reason else []
        else:
            version = await oa_workflow_service.current_version(
                self.db, actor, leave.workflow_definition_id, scene='leave')
            form = NormalizedLeaveFields.model_validate(leave.fields)
            route = await oa_workflow_service.resolve_route(self.db, actor, version, form)
            route_nodes, pause_reasons = route.nodes, route.pause_reasons
        nodes = []
        for index, node in enumerate(route_nodes):
            seats = []
            for seat in node.get("seats", []):
                user = await self.db.scalar(select(OAUser).where(
                    OAUser.tenant_id == actor.tenant_id, OAUser.id == seat.get("user_id")))
                if user:
                    seats.append({"order": index, "approver_id": user.id,
                                  "approver_name": user.display_name,
                                  "is_proxy": False, "rule_version": str(version.version)})
            nodes.extend(seats)
        return {"business_id": leave.business_no, "nodes": nodes,
                "rule_version": str(version.version), "risk_hint": "；".join(pause_reasons),
                "conflict": bool(pause_reasons)}

    def _require_confirmation(self):
        if not self.context.confirmation_id:
            raise AppException(ErrorCode.FORBIDDEN, '业务写入必须绑定服务端确认', http_status=403)

    @staticmethod
    def _values(command):
        return dict(command) if isinstance(command, dict) else command.model_dump(mode='json')

    async def _confirmed_leave_command(self, actor, bridge, *, kind, object_id, target_version, execute):
        self._require_confirmation()
        await identity_service.lock_tenant(self.db, actor.tenant_id)
        confirmed_payload = bridge.model_dump(mode='json')
        if confirmed_payload.get('review_route_hash') is None:
            confirmed_payload.pop('review_route_hash', None)
        values = dict(thread_id=bridge.thread_id, action=kind, object_id=object_id,
            object_version=bridge.expected_revision, payload=confirmed_payload)
        # Enclose the domain command and consumption in one savepoint so callers
        # cannot commit business changes after catching an invalid confirmation.
        async with self.db.begin_nested():
            binding = await oa_confirmation_service.binding(self.db, actor,
                self.context.confirmation_id, lock=True, **values)
            with self._trace_scope():
                result = await execute()
            operation = await self.db.scalar(select(OAWorkflowOperation).where(
                OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.actor_id == actor.user_id,
                OAWorkflowOperation.kind == kind, OAWorkflowOperation.target_id == object_id,
                OAWorkflowOperation.target_version == str(target_version),
                OAWorkflowOperation.operation_id == bridge.operation_id))
            if operation is None:
                raise invalid('业务命令结果缺失，请人工核对')
            if not result.replayed:
                await oa_confirmation_service.consume(self.db, actor, self.context.confirmation_id, operation.id, **values)
            elif binding.consumed_operation_id and binding.consumed_operation_id != operation.id:
                raise invalid('确认已用于其他操作')
        return result.result

    async def create_or_update_approval(self, command):
        actor = await self._actor()
        self._require_confirmation()
        values = self._values(command)
        action = values.get("action", "submit")
        if action == 'submit':
            bridge = BridgeLeaveSubmit.model_validate(values)
            _, leave = await self._leave(bridge.business_id)
            await oa_leave_service.applicant_access(self.db, actor, leave.id, write=True)
            payload = SubmitLeaveCommand.model_validate(bridge.model_dump(exclude={'action', 'business_id', 'thread_id', 'review_route_hash'}))
            async def submit_reviewed():
                if bridge.review_route_hash and leave.revision == bridge.expected_revision:
                    route = await self.get_approval_route(leave.id)
                    if canonical_hash(route) != bridge.review_route_hash:
                        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT,
                            '审批路线已变化，请刷新审核内容后再提交', http_status=409)
                return await oa_leave_service.submit(self.db, actor, leave.id, payload)
            return await self._confirmed_leave_command(actor, bridge, kind='leave.submit', object_id=leave.id,
                target_version=payload.requested_submission_version,
                execute=submit_reviewed)
        if action in {'approve', 'reject', 'return_for_correction'}:
            bridge = BridgeApprovalDecision.model_validate(values)
            await oa_approval_service.node_access(self.db, actor, bridge.node_id, write=True, allow_completed=True)
            payload = DecideNodeCommand.model_validate(bridge.model_dump(exclude={'node_id', 'thread_id'}))
            return await self._confirmed_leave_command(actor, bridge, kind='approval.decide', object_id=bridge.node_id,
                target_version=payload.expected_revision,
                execute=lambda: oa_approval_service.decide(self.db, actor, bridge.node_id, payload))
        else:
            raise self._unsupported("create_or_update_approval:" + action)

    async def _leave_result(self, key, kinds):
        actor = await self._actor()
        rows = list((await self.db.scalars(select(OAWorkflowOperation).where(
            OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.actor_id == actor.user_id,
            OAWorkflowOperation.operation_id == key, OAWorkflowOperation.kind.in_(kinds)))).all())
        if len(rows) > 1:
            raise invalid('操作编号对应多个结果，请使用唯一的业务操作编号')
        if not rows:
            return None
        row = rows[0]
        if row.kind == 'approval.decide':
            await oa_approval_service.node_access(self.db, actor, row.target_id, allow_completed=True)
        else:
            await oa_leave_service.applicant_access(self.db, actor, row.target_id)
        return row.result

    async def get_approval_result(self, idempotency_key: str):
        return await self._leave_result(idempotency_key, ['leave.submit', 'approval.decide'])

    async def edit_leave_case(self, command):
        actor = await self._actor()
        self._require_confirmation()
        bridge = BridgeLeaveEdit.model_validate(self._values(command))
        _, leave = await self._leave(bridge.business_id)
        await oa_leave_service.applicant_access(self.db, actor, leave.id, write=True)
        payload = LeaveDraftPatch.model_validate(bridge.model_dump(exclude={'business_id', 'thread_id'}))
        return await self._confirmed_leave_command(actor, bridge, kind='leave.edit', object_id=leave.id,
            target_version=payload.expected_revision,
            execute=lambda: oa_leave_service.update_draft(self.db, actor, leave.id, payload))

    async def get_leave_edit_result(self, idempotency_key: str):
        return await self._leave_result(idempotency_key, ['leave.edit'])

    async def create_or_merge_ticket(self, command):
        actor = await self._actor()
        if not self.context.confirmation_id:
            raise AppException(ErrorCode.FORBIDDEN, "工单写入必须绑定服务端确认", http_status=403)
        payload = FormalTicketProposal.model_validate(command if isinstance(command, dict)
                                                    else command.model_dump(mode="json"))
        with self._trace_scope():
            result = await oa_ticket_service.create_or_merge(
                self.db, actor, payload, confirmation_id=self.context.confirmation_id)
        return result.result if hasattr(result, "result") else result

    async def get_notification_result(self, idempotency_key: str):
        actor = await self._actor()
        await authorize_oa(self.db, actor, 'notification', 'read', target=OAAccessTarget(
            actor.tenant_id, actor.user_id, await user_department(self.db, actor.tenant_id, actor.user_id)))
        operations = list((await self.db.scalars(select(OAWorkflowOperation).where(
            OAWorkflowOperation.tenant_id == actor.tenant_id,
            OAWorkflowOperation.actor_id == actor.user_id,
            OAWorkflowOperation.kind == "notification.intent",
            OAWorkflowOperation.operation_id == idempotency_key))).all())
        if len(operations) > 1:
            raise invalid('操作编号对应多个通知，请使用唯一的业务操作编号')
        if not operations:
            return None
        operation = operations[0]
        source = notification_sources.intent_source(operation.result.get('source'), actor.user_id)
        if not source or operation.result.get('recipient_id') != actor.user_id:
            raise AppException(ErrorCode.DEPENDENCY_FAILED, '该历史通知缺少可信来源，暂不可查询', http_status=503)
        if source.get('business'):
            await notification_sources.check_business(self.db, actor, source['business'])
        notification = await self.db.scalar(select(OANotification).join(OAWorkflowOutbox,
            OANotification.source_outbox_id == OAWorkflowOutbox.id).join(OAWorkflowEvent,
            OAWorkflowOutbox.event_id == OAWorkflowEvent.id).where(
            OANotification.tenant_id == actor.tenant_id, OANotification.recipient_id == actor.user_id,
            OAWorkflowEvent.operation_id == operation.id))
        result = {key: value for key, value in operation.result.items() if key != 'source'}
        result.update(delivered=False, channels={})
        if notification is None:
            return result
        if not await notification_sources.allowed(self.db, notification):
            raise denied()
        deliveries = (await self.db.scalars(select(OANotificationDelivery).where(
            OANotificationDelivery.tenant_id == actor.tenant_id,
            OANotificationDelivery.notification_id == notification.id).execution_options(populate_existing=True))).all()
        for delivery in deliveries:
            attempts = (await self.db.scalars(select(OANotificationAttempt).where(
                OANotificationAttempt.tenant_id == actor.tenant_id,
                OANotificationAttempt.delivery_id == delivery.id).order_by(OANotificationAttempt.number))).all()
            result['channels'][delivery.channel] = dict(state=delivery.state, attempt_count=delivery.attempt_count,
                last_code=delivery.last_code, attempts=[dict(number=row.number, state=row.state,
                    finished_at=row.finished_at.isoformat() if row.finished_at else None) for row in attempts])
        result['status'] = result['channels'].get('inbox', {}).get('state', 'PENDING')
        result['delivered'] = result['status'] == 'ACCEPTED'
        return result

    async def notify(self, command):
        actor = await self._actor()
        payload = BridgeNotification.model_validate(self._values(command))
        await identity_service.lock_tenant(self.db, actor.tenant_id)
        department = await user_department(self.db, actor.tenant_id, payload.user_id)
        target = OAAccessTarget(actor.tenant_id, payload.user_id, department)
        await authorize_oa(self.db, actor, "notification", "write", target=target)
        source = dict(kind='intent', recipient_id=payload.user_id)
        if payload.business_id:
            source['business'] = await notification_sources.business_source(self.db, actor, payload.business_id)
        target_id = payload.business_id or payload.user_id
        async def perform(operation):
            result = {"status": "PENDING", "recipient_id": payload.user_id,
                      "business_id": payload.business_id, "channel": "inbox",
                      "operation_id": operation.id, "source": source}
            return CommandOutcome(result=result, recipients=[payload.user_id],
                recipient_access={payload.user_id: ("notification", target)},
                detail={"notification_intent": True})
        outcome = await run_command(self.db, actor, OACommand(
            kind="notification.intent", target_id=target_id, target_version="1",
            operation_id=payload.idempotency_key,
            payload=payload.model_dump(mode="json"), resource="notification", target=target,
            trace_id=self.context.trace_id), perform)
        return {key: value for key, value in outcome.result.items() if key != 'source'}

    @staticmethod
    def _unsupported(method: str) -> AppException:
        return AppException(ErrorCode.DEPENDENCY_FAILED, f"正式 OA 网关暂未开放能力：{method}", http_status=503)

