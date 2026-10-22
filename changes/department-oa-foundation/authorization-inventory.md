# M1 授权入口清单

| 入口 | 身份来源和边界 |
| --- | --- |
| HTTP 中间件 | 明确 mock/builtin；builtin Bearer 签名和持久会话；请求前后清空 ContextVar |
| 业务 deps | 当前库身份、资源动作；未接通的旧 OA 接口 503；未知资源拒绝 |
| 遗留全局管理 | builtin 知识管理、策略、审计查询/导出及运维 503；不提供可分配权限，生命周期审计仍写入 |
| 组织 API | 当前组织的 organization read/write 管理权限；租户锁、全员有序锁、最后管理员和防环保护 |
| meeting/document/email/report/contract/work_task 服务 | async 当前身份；公共操作独立 resource/action；来源权限再次核对 |
| 列表/详情/导出 | owner 与明确 department 授权共同谓词；合同参与人、报表来源保留更严格条件 |
| thread/task | 解析当前身份、关联场景 read 权限和拥有/参与条件 |
| 工具基座及 report/work_task 工具 | async 身份；静态白名单与策略交集；正式身份拒绝旧 OA 工具 |
| 工作任务来源/报表来源 | meeting read / work_task read 再检查；缓存 source_ids 为空也检查；正式工单/审批来源 503 |
| meeting 图 | 每节点读取权威身份与 meeting write；业务提交前再次校验 |
| leave 图/审批恢复 | Mock OA 工厂在 builtin 模式拒绝，不以 Mock 替代正式业务 |
| 外部审批调度 | builtin 模式不执行旧 Mock OA 调度 |
| 工作任务提醒 | 接收人与创建人从当前 Resolver 解析；事务持有各自校验快照 |
| 数据库提交 | before_commit 检查当前状态、认证/授权版本、session 撤销和期限 |
| 前端路由与菜单 | 当前权限映射；builtin 无 Mock 切换；后端独立授权，不依赖页面隐藏 |
| 前端会话 | 内存 access、HttpOnly refresh、刷新单飞；用户切换/退出清缓存，旧请求和刷新响应不回写 |

证据：backend/tests/integration/test_identity_authorization.py、test_identity_sessions.py、test_organization_access.py、test_identity_business_compatibility.py；前端 auth-session/auth-client/organization-access 测试与 e2e/m1-identity.spec.ts。回归结果见 reviews/verification.md。
