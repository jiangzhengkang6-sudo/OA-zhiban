# B7 audit, observability and degradation review — 2026-10-13

## Scope

覆盖受控审计导出、运行 Span/模型用量指标、trace 下钻、场景降级与在途任务策略，以及管理员运维和降级页面。

## Verification

- 后端全量：`194 passed`。
- 前端测试：`19 passed`。
- 前端构建：`npm run build` 成功；仅保留 Vite 大 chunk 提示。
- 开发库迁移头：`0015 (head)`，未清库。
- 服务冒烟：`http://127.0.0.1:8001/healthz` 返回 `status: ok`；前端 `http://localhost:5173` 返回 `200`。
- 管理员 API 冒烟：`GET /api/operations/metrics` 与 `GET /api/operations/degradations` 返回 `200`。

## Findings

- 审计导出具备角色授权、敏感摘要脱敏、过期引用和导出审计记录。
- 运行观测支持按 trace 聚合节点耗时、工具错误和模型用量；未知 token 以缺失标记呈现。
- 降级控制支持租户/部门/场景作用域、新任务回退或拒绝、在途继续或暂停，以及管理员恢复。
- 前端注册了审计导出、运维观测和降级控制入口；管理员菜单按角色显示。
- 修正 `audit_export.expires_at` 模型未声明时区导致的迁移模型一致性失败。

## Remaining validation

- 仍需使用管理员账号完成真实浏览器操作：打开 `/operations`、`/degradation`，创建/恢复一次降级并确认页面状态变化。
- B7 通过前不宣称 P1 总体验收完成；B8 真实 OA 与上线验证尚未开始。

## Verdict

B7 后端和前端实现及自动化验证 PASS；服务冒烟 PASS；真实浏览器验收 PENDING。
