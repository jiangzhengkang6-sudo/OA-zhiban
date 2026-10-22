# 真实 OA HTTP Bridge 契约

本项目的 `OA_PROVIDER=real` 只接入一个明确的 HTTP bridge，不猜测企业 OA 的私有接口。部署方需要提供以下 JSON 接口，并把地址配置到 `OA_BASE_URL`：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/capabilities` | 返回 `capabilities` 布尔对象 |
| GET | `/users/{user_id}` | 返回 `UserContext` |
| GET | `/leaves/{business_id}` | 返回 `LeaveCase` |
| GET | `/users/{user_id}/leave-balance/{leave_type}` | 返回 `Balance` |
| GET | `/leaves/{business_id}/approval-route?user_id=...` | 返回 `ApprovalRoute` |
| POST | `/approvals` | 写入审批，必须支持 `Idempotency-Key` |
| GET | `/approvals/results/{idempotency_key}` | 对账审批写入 |
| POST | `/leaves/{business_id}/edit` | 写入请假编辑，必须支持幂等键 |
| GET | `/leaves/edits/{idempotency_key}` | 对账请假编辑 |
| POST | `/tickets` | 创建/合并工单，必须支持幂等键 |
| POST | `/notifications` | 发送通知，必须支持幂等键 |
| GET | `/notifications/{idempotency_key}` | 对账通知 |

认证使用 `Authorization: Bearer <OA_API_KEY>`。所有成功响应可以直接返回对象，也可以包在 `{"data": {...}}` 中。失败响应应返回 JSON；HTTP 408、429、5xx 的只读请求会有限重试，写请求不会自动重试。写请求超时或 5xx 后必须先调用对应 results 接口对账，不能直接再次写入。

## 配置

```dotenv
OA_PROVIDER=real
OA_BASE_URL=https://oa-gateway.example.com/api
OA_API_KEY=<secret>
OA_TIMEOUT_SECONDS=10
OA_READ_RETRIES=2
```

启动前访问 `/api/readiness`。只有 `identity`、`leave_read` 和 `approval_write` 同时为 `true` 时才会报告 `ready: true`；未配置地址、能力缺失或探测失败均会 fail-closed。

当前仓库包含 MockTransport 契约测试，但没有真实 OA 沙箱凭据，因此不能宣称真实 OA 已接通。
