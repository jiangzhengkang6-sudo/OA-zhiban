"""Finite approval DSL. Publication validates every path before any execution."""
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator
from .oa_leave import OAInput, Identifier, OACommand
from .oa_reimbursement import money_minor, MAX_AMOUNT_MINOR


class LeaveForm(OAInput):
    leave_types: list[Identifier] = Field(min_length=1, max_length=50)
    reason_max_length: int = Field(default=2000, ge=1, le=2000)

    @model_validator(mode='after')
    def unique_types(self):
        if len(set(self.leave_types)) != len(self.leave_types):
            raise ValueError('假种不能重复')
        return self


class LeaveRules(OAInput):
    timeout_hours: int = Field(default=48, ge=1, le=8760)
    required_attachments: list[Identifier] = Field(default_factory=list)
    calendar: Literal['inclusive_days'] = 'inclusive_days'


class ReimbursementForm(OAInput):
    categories: list[Identifier] = Field(min_length=1,max_length=50)
    purpose_max_length: int = Field(default=2000,ge=1,le=2000)

    @model_validator(mode='after')
    def unique_categories(self):
        if len(self.categories)!=len(set(self.categories)):
            raise ValueError('报销类别不能重复')
        return self


class ReimbursementRules(OAInput):
    timeout_hours: int = Field(default=48,ge=1,le=8760)
    currency: Literal['CNY'] = 'CNY'
    minimum_invoices: Literal[1] = 1


class Selector(OAInput):
    kind: Literal['manager', 'users', 'role']
    levels: int | None = Field(default=None, ge=1, le=10)
    user_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    role_id: Identifier | None = None

    @model_validator(mode='after')
    def complete(self):
        if self.kind == 'manager' and (self.levels is None or self.user_ids or self.role_id):
            raise ValueError('上级选择器仅接受层级')
        if self.kind == 'users' and (not self.user_ids or self.levels is not None or self.role_id):
            raise ValueError('指定人选择器需要人员')
        if self.kind == 'role' and (not self.role_id or self.levels is not None or self.user_ids):
            raise ValueError('角色选择器需要角色')
        self.user_ids = list(dict.fromkeys(self.user_ids))
        return self


class Approval(OAInput):
    id: Identifier
    kind: Literal['approval']
    mode: Literal['single', 'all', 'any']
    selector: Selector
    next_id: Identifier

    @model_validator(mode='after')
    def single_count(self):
        if self.mode == 'single' and self.selector.kind == 'users' and len(self.selector.user_ids) != 1:
            raise ValueError('单签只能指定一人')
        return self


class CC(OAInput):
    id: Identifier
    kind: Literal['cc']
    selector: Selector
    next_id: Identifier


class Condition(OAInput):
    field: Literal['days', 'leave_type', 'start_date', 'end_date', 'reason','amount','category','expense_date','purpose']
    op: Literal['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'in']
    value: object
    next_id: Identifier

    @model_validator(mode='after')
    def typed(self):
        values = self.value if self.op == 'in' else [self.value]
        if not isinstance(values, list) or not values or len(values) > 100:
            raise ValueError('条件集合无效')
        for value in values:
            if self.field == 'amount':
                if isinstance(value,dict) and set(value)=={'amount_minor'}:
                    cents=value['amount_minor']
                    if type(cents) is not int or not 1<=cents<=MAX_AMOUNT_MINOR:
                        raise ValueError('已发布金额分值无效')
                else:
                    cents=money_minor(value)
                value={'amount_minor':cents}
            elif self.field == 'days':
                if type(value) is not int or value < 1:
                    raise ValueError('天数条件必须为正整数')
            elif self.field in {'start_date', 'end_date','expense_date'}:
                if not isinstance(value, str):
                    raise ValueError('日期条件需要标准日期')
                date.fromisoformat(value)
            elif not isinstance(value, str) or not value or len(value) > 2000:
                raise ValueError('文本条件无效')
        if self.field=='amount':
            normalized=[item if isinstance(item,dict) else {'amount_minor':money_minor(item)} for item in values]
            self.value=normalized if self.op=='in' else normalized[0]
        return self


class Branch(OAInput):
    id: Identifier
    kind: Literal['branch']
    cases: list[Condition] = Field(min_length=1, max_length=50)
    default_next_id: Identifier


class End(OAInput):
    id: Identifier
    kind: Literal['end']


Node = Annotated[Union[Approval, CC, Branch, End], Field(discriminator='kind')]


class ValidatedDefinition(OAInput):
    schema_version: Literal[1]
    scene: Literal['leave','reimbursement']
    entry_id: Identifier
    form: LeaveForm | ReimbursementForm
    rules: LeaveRules | ReimbursementRules
    nodes: list[Node] = Field(min_length=2, max_length=100)

    @model_validator(mode='before')
    @classmethod
    def scene_models(cls,value):
        if not isinstance(value,dict): return value
        scene=value.get('scene')
        if scene not in {'leave','reimbursement'}: return value
        form,rules=(LeaveForm,LeaveRules) if scene=='leave' else (ReimbursementForm,ReimbursementRules)
        return {**value,'form':form.model_validate(value.get('form',{})),
            'rules':rules.model_validate(value.get('rules',{}))}

    @model_validator(mode='after')
    def graph(self):
        by_id = {node.id: node for node in self.nodes}
        if len(by_id) != len(self.nodes) or self.entry_id not in by_id:
            raise ValueError('节点重复或入口不存在')
        if self.scene=='leave':
            if not isinstance(self.form,LeaveForm) or not isinstance(self.rules,LeaveRules):
                raise ValueError('请假场景须使用请假表单和规则')
            if not set(self.rules.required_attachments).issubset(self.form.leave_types):
                raise ValueError('附件规则引用未知假种')
            allowed={'days','leave_type','start_date','end_date','reason'}
        else:
            if not isinstance(self.form,ReimbursementForm) or not isinstance(self.rules,ReimbursementRules):
                raise ValueError('报销场景须使用报销表单和规则')
            allowed={'amount','category','expense_date','purpose'}
        for node in self.nodes:
            if node.kind=='branch' and any(case.field not in allowed for case in node.cases):
                raise ValueError('分支字段不属于当前业务场景')
        visited, visiting = set(), set()

        def walk(node_id, approved):
            if node_id not in by_id or node_id in visiting:
                raise ValueError('路线缺少节点或存在循环')
            marker = (node_id, approved)
            if marker in visited:
                return
            node = by_id[node_id]
            visiting.add(node_id)
            if node.kind == 'end':
                if not approved:
                    raise ValueError('每条路线必须经过审批')
            elif node.kind == 'branch':
                for target in [case.next_id for case in node.cases] + [node.default_next_id]:
                    walk(target, approved)
            else:
                walk(node.next_id, approved or node.kind == 'approval')
            visiting.remove(node_id)
            visited.add(marker)

        walk(self.entry_id, False)
        if {key[0] for key in visited} != set(by_id):
            raise ValueError('包含不可达节点')
        return self


class WorkflowSave(OAInput):
    operation_id: Identifier
    department_id: Identifier
    code: Identifier
    name: Annotated[str, Field(min_length=1, max_length=128)]
    definition: ValidatedDefinition
    expected_revision: int | None = Field(default=None, ge=1)


class PublishWorkflow(OACommand):
    pass


class DecideNodeCommand(OACommand):
    action: Literal['approve', 'reject', 'return_for_correction']
    note: str = Field(default='', max_length=2000)
    reason_code: Literal['materials_incomplete','date_issue','quota_issue','other'] = 'other'
    corrections: list[Literal['leave_type', 'start_date', 'end_date', 'reason', 'attachment_ids','purpose','expense_date','category','amount','currency']] = Field(default_factory=list)
    approval_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def valid_decision(self):
        if self.action != 'approve' and not self.note.strip():
            raise ValueError('驳回或退回需要填写原因')
        if self.action == 'return_for_correction' and not self.corrections:
            raise ValueError('退回需要指定待修正字段')
        if self.action != 'return_for_correction' and self.corrections:
            raise ValueError('仅退回可以指定修正字段')
        if self.action != 'approve' and self.approval_note is not None:
            raise ValueError('仅批准可以补充审批说明')
        self.corrections = list(dict.fromkeys(self.corrections))
        return self


class SeatHandoffCommand(OACommand):
    target_user_id: Identifier
    reason: str = Field(min_length=1, max_length=500)


class SeatReplacement(OAInput):
    seat_id: Identifier
    target_user_id: Identifier


class RouteResumeCommand(OACommand):
    replacements: list[SeatReplacement] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def unique_seats(self):
        if len({item.seat_id for item in self.replacements})!=len(self.replacements):
            raise ValueError('同一席位只能指定一次接收人')
        return self
