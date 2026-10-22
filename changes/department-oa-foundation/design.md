# M1 账号与组织底座设计

状态：2026-10-18 用户已批准；B1–B5 已完成并通过本地工程验证。仅覆盖本次 M1。

## Context

AuthMiddleware 从 Mock 字典解析身份；authorization_service.require_fresh_identity 又经 get_adapter 取用户，不能只替换入口。CurrentUser 被 API、服务、工具和图恢复共用，现有调用为同步函数，而数据库主路径为 AsyncSession。本轮必须同时改造身份来源和调用链，避免异步函数漏 await 或在事件循环直接执行同步数据库查询。

现有迁移 head 是 0022；新表兼容字符串 user_id/tenant_id，不重建旧模型。前端 axios 写入 mock Authorization，App.vue 使用演示用户判断菜单，均须随身份模式切换。

## Goals

- 真实账号、可撤销会话、组织和最小权限形成可测试闭环。
- 保留业务响应和 CurrentUser 基本结构，明确所有身份复核入口。
- 身份与 OA 业务 Provider 解耦；M1 可本地验收，但不解除生产 Mock OA 限制。

## Decisions

### 1. 数据模型与迁移

Choice：`identity.py` 集中定义 OAUser、OADepartment、OAPosition、OAMembership、OARole、OAPermission、OAUserRole、OARolePermission、OAAuthSession、OAAuthThrottle。使用 oa_ 前缀表，UTC 时间，软禁用和稳定 ID。OAUser 有 normalized_username、password_hash、status、auth_version、authorization_version、failed_attempts、locked_until；OAAuthSession 有 family_id、refresh_digest、absolute_expires_at、consumed_at、revoked_at 及版本字段，保留轮换记录以识别旧值重放。角色权限保存 resource/action/scope。唯一约束和外键补足应用校验。

Rationale：统一身份基础，审计和旧业务不需重写主键。组织结构锁与会话行锁保护并发更新；变更与相应审计统一提交。

Alternatives considered：复用 Mock JSON 不提供可撤销权威身份；本轮引入外部 IAM 会增加不必要的运维和接入范围。

### 2. 会话与口令

Choice：Argon2id 及成熟 JWT 库，固定 HS256、issuer/audience、密钥最小强度与配置校验，不自行实现密码算法。access 含 sub、sid、auth_version、iat/exp、iss/aud，不携带可授权的旧角色。refresh 使用高熵随机值并仅保存摘要，绝对期限不因轮换延长。前端 access 仅在内存，refresh 经 HttpOnly、SameSite=Lax Cookie；HTTPS 环境 Secure=true，开发仅显式 localhost 允许非 Secure。

刷新/退出检查配置的精确 Origin，Cookie Path 限定认证路由，CORS 不使用带凭证通配。Cookie 认证接口增加 CSRF 校验；同源首屏获取 CSRF nonce，前端内存保存并用请求头提交。登录限流同时覆盖账号与来源，使用持久化计数和过期清理。refresh 重放撤销整个族；客户端单飞，多标签页竞争时安全退出并提示重登，不保留有效重复凭证。

Rationale：退出和禁用不能等到 JWT 自然过期；无默认密钥和管理员密码。cookie 不作为普通业务授权凭证。

Alternatives considered：localStorage 保存长期令牌和无状态 refresh 均不能满足本轮撤销要求；2 小时只代表 access 上限，不是权限缓存周期。

### 3. 异步身份权威与调用链

Choice：新增 `providers/identity.py` 的异步 `IdentityResolver.resolve(user_id: str, *, session: AsyncSession) -> CurrentUser`，按 AUTH_PROVIDER 选择 mock/builtin，独立于 OA_PROVIDER。`require_fresh_identity` 与 `authorize_tool` 改为 async，显式传 session；资源授权在拿到当前身份后判断。所有 API/service/tool/graph 调用点同时迁移，后台每次操作新建会话复核，不读取遗留 Mock 角色。

中间件入口先清空当前请求身份，严格解析 Bearer；builtin 拒绝裸用户 ID 和 mock:。JWT 签名与会话状态在认证服务解析，受保护路由依赖统一拒绝无效身份。失败不得遗留前一次 ContextVar。高影响写服务比较身份/授权版本并在事务内复核，不依赖请求开始时的长期快照。

Rationale：兼顾现有调用链和异步数据库，避免“入口真登录、业务仍取 Mock 身份”。

Alternatives considered：直接把 get_adapter 替换为 builtin 会混淆身份与尚未实现的业务 Provider；同步数据库查询会阻塞现有异步请求路径。

### 4. 角色、数据范围与管理权

Choice：Mock 保留 employee/approver/support/admin/ops 等语义角色；builtin 通用业务身份允许自定义角色，依据 resource/action/scope 决策，专用审批人/管理员检查仍保留。数据范围为本人和当前部门；写授权须有同资源且范围相同或更大的读授权。审批上下文由 M2 的有效节点提供，M1 不因历史 route 快照赋予永久访问权。SQL 查询和附件读取先限定范围。

系统管理员只管理账号组织；敏感业务读取需另授权限。最后管理员保护在事务内检查；组织防环和归属一致性同时校验。禁用保留历史和待交接标记，M2 才提供业务转交。

builtin 的旧知识管理、策略、审计查询/导出及运维因尚无完整租户隔离明确返回 503，组织角色不提供这些可分配权限；生命周期审计仍原子写入。任务读取会议来源需另有 meeting read，报表查询任务指标需另有 work_task read，包括空来源缓存复核。旧工单与审批来源同样返回 503。合同参与人、任务批次参与人和报表来源条件保留较窄范围，部门授权不绕过这些业务约束。

Rationale：减少权限扩散，保留后续审批最小上下文接口。

Alternatives considered：给 admin 全数据权限简化了实现，但不符合最小权限目标。

### 5. API 与前端

Choice：API 沿用 ApiResponse。`/api/auth/csrf`、`login`、`refresh`、`logout`、`me`、`change-password`；`/api/organization` 管理部门、岗位、成员、角色与授权，所有写操作要求当前组织的 organization write 管理权限，读取要求 organization read。安全模式由服务端公开的无敏感配置接口 `/api/auth/config` 告知前端，不凭 DEV 推断允许 Mock。

新增登录页、组织管理页及 auth store；axios 区分公开认证与业务请求，单飞刷新最多一次，403 不触发刷新，失效清空内存身份及用户相关页面缓存。切换用户清除前用户草稿，禁止静默把旧草稿提交给新身份；站内安全跳转。响应式沿用 Element Plus，正式模式无演示账号选择器。

Rationale：解决硬编码 Mock Authorization 和演示角色菜单，避免前后端身份模式漂移。

Alternatives considered：只添加登录表单不能关闭旧 Mock 入口，也不能满足会话恢复和路由保护。

## Interfaces

JWT 使用字典 claims：sub、sid、av（auth_version）、iat、exp、iss、aud；LoginInput 的 password 使用 SecretStr。AccessGrant 包含 access_token、token_type（默认 bearer）、expires_in、user。内部 IssuedSession 包含 grant 与 refresh，refresh 不出现在 HTTP JSON。

`CurrentUserView(user_id: str, display_name: str, roles: list[str], depts: list[str], permissions: list[PermissionView])`；`PermissionView(resource: str, action: str, scope: Literal["self", "department"])`。

`require_fresh_identity(actor: CurrentUser, required_roles: Iterable[str] = (), *, session: AsyncSession) -> CurrentUser` 是 async；`authorize_tool(actor, scene, tool_name, *, session, required_roles=(), policy_tools=None) -> AuthorizationDecision` 是 async。AuthorizationDecision 保留现有字段。CurrentUser 仅增加带默认值的 session_id/auth_version/authorization_version 元数据，旧构造保持兼容。

## Risks And Trade-Offs

- 同步转异步可能漏调用点：B3 全量搜索并静态/运行验证，不只修改已知页面。
- 权限变更与进行中写入竞争：先明确以提交前授权检查为生效界线，在同事务核对版本；禁止长事务中等待模型。
- 严格 refresh 重放保护可能让多标签页竞争登出：先保证安全，明确提示重登，客户端做单飞；不以放宽重放检查隐藏竞态。
- 旧数据身份无法自动映射：本轮保留原数据，真实账号归属转换另行评审。
- auth=builtin + OA=mock 只在开发允许；仍不得上线，M3 后另做生产验收。
- 身份接口故障默认拒绝，不沿用旧权限；付费模型、邮件、IM 均不在本轮测试路径。
