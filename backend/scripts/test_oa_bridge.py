"""本机测试 OA Bridge，仅验证真实 OA HTTP 契约，不连接企业系统。"""
from __future__ import annotations
import copy
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from fastapi import FastAPI, Header, HTTPException, Query, Request

API_KEY = os.getenv("TEST_OA_API_KEY", "")
if not API_KEY:
    raise RuntimeError("TEST_OA_API_KEY is required")
app = FastAPI(title="Test OA Bridge", version="1.0.0")
USER = {"user_id":"u_emp_001", "tenant_id":"tenant_test_001", "name":"演示员工", "dept_id":"dept_001", "dept_name":"研发部", "roles":["employee"], "data_scope":{"departments":["dept_001"]}}
LEAVE = {"business_id":"leave_demo_001", "user_id":"u_emp_001", "leave_type":"annual", "start_at":"2026-10-22T09:00:00Z", "end_at":"2026-10-22T18:00:00Z", "reason":"本地 OA 联调演示", "attachments":[], "status":"PENDING", "form_snapshot":{"source":"test-oa-bridge"}}
BALANCE = {"leave_type":"annual", "total":15.0, "used":3.0, "remaining":12.0, "unit":"day"}
ROUTE = {"business_id":"leave_demo_001", "nodes":[{"order":1,"approver_id":"u_manager_001","approver_name":"演示主管","is_proxy":False,"proxy_for":None,"rule_version":"test-rule-v1"}], "rule_version":"test-rule-v1", "risk_hint":"本地测试路由", "conflict":False}
RESULTS: dict[str, dict[str, dict[str, Any]]] = {"approvals":{}, "leave_edits":{}, "tickets":{}, "notifications":{}}

def authorize(value: str | None) -> None:
    if value != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="测试 OA Token 无效")

def idempotency(value: str | None) -> str:
    if not value:
        raise HTTPException(status_code=400, detail="缺少 Idempotency-Key")
    return value

def stored(namespace: str, key: str, factory) -> dict[str, Any]:
    if key in RESULTS[namespace]:
        return copy.deepcopy(RESULTS[namespace][key])
    result = factory()
    RESULTS[namespace][key] = copy.deepcopy(result)
    return result

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status":"ok", "provider":"test-oa-bridge"}

@app.get("/capabilities")
async def capabilities(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    return {"capabilities":{"identity":True,"leave_read":True,"approval_write":True,"ticket_write":True,"notification":True}}

@app.get("/users/{user_id}")
async def get_user(user_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    if user_id != USER["user_id"]: raise HTTPException(status_code=404, detail="用户不存在")
    return copy.deepcopy(USER)

@app.get("/leaves/{business_id}")
async def get_leave(business_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    if business_id != LEAVE["business_id"]: raise HTTPException(status_code=404, detail="请假单不存在")
    return copy.deepcopy(LEAVE)

@app.get("/users/{user_id}/leave-balance/{leave_type}")
async def get_balance(user_id: str, leave_type: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    if user_id != USER["user_id"] or leave_type != BALANCE["leave_type"]: raise HTTPException(status_code=404, detail="假期余额不存在")
    return copy.deepcopy(BALANCE)

@app.get("/leaves/{business_id}/approval-route")
async def get_route(business_id: str, user_id: str = Query(...), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    if business_id != LEAVE["business_id"] or user_id != USER["user_id"]: raise HTTPException(status_code=404, detail="审批路线不存在")
    return copy.deepcopy(ROUTE)

async def write_payload(request: Request, authorization: str | None, namespace: str, prefix: str, *, ticket_id: bool = False, delivered: bool = False) -> dict[str, Any]:
    authorize(authorization)
    key = idempotency(request.headers.get("Idempotency-Key"))
    payload = await request.json()
    def factory() -> dict[str, Any]:
        result: dict[str, Any] = {"success":True,"request_id":f"{prefix}_{secrets.token_hex(8)}","idempotency_key":key,"status":"accepted","payload":{"received":payload,"processed_at":datetime.now(timezone.utc).isoformat()},"error":""}
        if ticket_id: result["ticket_id"] = f"ticket_test_{secrets.token_hex(5)}"
        if delivered: result["delivered"] = True
        return result
    return stored(namespace, key, factory)

@app.post("/approvals")
async def create_approval(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return await write_payload(request, authorization, "approvals", "approval")

@app.get("/approvals/results/{idempotency_key}")
async def approval_result(idempotency_key: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    result = RESULTS["approvals"].get(idempotency_key)
    if result is None: raise HTTPException(status_code=404, detail="审批写入记录不存在")
    return copy.deepcopy(result)

@app.post("/leaves/{business_id}/edit")
async def edit_leave(business_id: str, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    if business_id != LEAVE["business_id"]: raise HTTPException(status_code=404, detail="请假单不存在")
    return await write_payload(request, authorization, "leave_edits", "leave_edit")

@app.get("/leaves/edits/{idempotency_key}")
async def leave_edit_result(idempotency_key: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    result = RESULTS["leave_edits"].get(idempotency_key)
    if result is None: raise HTTPException(status_code=404, detail="请假编辑记录不存在")
    return copy.deepcopy(result)

@app.post("/tickets")
async def create_ticket(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return await write_payload(request, authorization, "tickets", "ticket", ticket_id=True)

@app.post("/notifications")
async def create_notification(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return await write_payload(request, authorization, "notifications", "notification", delivered=True)

@app.get("/notifications/{idempotency_key}")
async def notification_result(idempotency_key: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    result = RESULTS["notifications"].get(idempotency_key)
    if result is None: raise HTTPException(status_code=404, detail="通知记录不存在")
    return copy.deepcopy(result)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("TEST_OA_PORT", "8091")))
