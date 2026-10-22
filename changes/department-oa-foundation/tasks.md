# M1 实施任务

B3 补充必要路径：`backend/app/adapters/factory.py`、`backend/app/services/work_task_scheduler.py`。前者在正式身份模式拒绝调用 Mock OA，后者改用权威身份并复核后台写入；不扩展 OA 业务能力。

B5 回归补充路径：`backend/app/api/routers/documents.py`、`reports.py`、`contracts.py` 补迁移异步身份调用；`backend/tests/migrations/test_p3_agents.py` 将历史 P3 断言绑定至 P3 的 0022。新增会话不应改变历史阶段迁移断言。

B5 复核补充：`frontend/src/main.ts` 统一组件中文；业务通用身份检查保留 Mock 角色限制，builtin 使用资源权限；角色写权限须包含不小于写范围的读权限。对应证据写入 `backend/tests/integration/test_identity_business_compatibility.py`。授权清单实际路径为本变更目录根部 `authorization-inventory.md`。

B5 失败关闭补充：旧全局管理接口尚未具备独立租户范围，builtin 的知识管理/策略/审计查询导出/运维返回 503；不提供相应可分配权限。生命周期审计保留事务写入。此项收紧访问，不扩展 M2/M3 功能。

B5 来源复核补充路径：`backend/app/services/report_query.py`，报表指标检查来源资源权限；工作任务会议来源同样检查 meeting read。builtin 的旧工单/审批来源明确 503，避免通过工具或缓存绕过业务入口。

状态：用户已批准串行实施，B1–B5 已完成本地工程审查与验证。复选框表示实现和验证完成，不代表每一条规划中的 Red 顺序都有独立日志；真实失败、修正和通过结果见 reviews，不补造执行历史。

## File Structure

以下为相对实际仓库 `E:/OA AGENT SYSTEM/` 的精确路径。新增文件职责在创建前已经确定；必要新增路径先补本清单。

### B1 Create/Modify

- Create `backend/app/models/identity.py`：账号、组织、权限与会话 ORM。
- Create `backend/migrations/versions/0023_identity_foundation.py`：0022 后的扩张迁移。
- Modify `backend/app/models/__init__.py`：注册新增模型。
- Create `backend/tests/migrations/test_identity_foundation.py`：迁移与旧数据保持。
- Create `backend/tests/unit/test_identity_models.py`：字段约束和模型注册。

### B2 Create/Modify

- Create `backend/app/schemas/identity.py`：登录、令牌、当前用户及权限 DTO。
- Create `backend/app/services/credential_service.py`：哈希与令牌验证，无数据库副作用。
- Create `backend/app/services/identity_service.py`：账号、会话、锁定与权限版本。
- Create `backend/app/cli/bootstrap_admin.py`、`backend/app/cli/__init__.py`：显式首管理员初始化入口。
- Create `backend/app/api/routers/auth.py`：认证配置、CSRF、登录/刷新/退出/me/改密。
- Modify `backend/app/core/config.py`、`backend/requirements.txt`、`.env.example`：身份配置及依赖声明，仅示例变量，无真实密钥。
- Create `backend/tests/unit/test_credentials.py`、`backend/tests/integration/test_identity_sessions.py`：哈希、JWT、锁定与轮换并发。

### B3 Modify/Create

- Create `backend/app/providers/identity.py`：异步身份权威解析，与业务 OA Provider 分离。
- Modify `backend/app/core/context.py`、`backend/app/middleware/auth.py`、`backend/app/api/deps.py`：当前身份元数据、清理、解析和依赖。
- Modify `backend/app/services/authorization_service.py`：异步权威复核和资源动作授权。
- Modify `backend/app/services/contract_service.py`、`document_service.py`、`email_service.py`、`meeting_service.py`、`report_service.py`、`thread_service.py`、`task_service.py`、`work_task_service.py`：上述文件均在 `backend/app/services/`；改造已有身份调用及资源范围，保留业务响应。
- Modify `backend/app/tools/base.py`、`report_tools.py`、`work_task_tools.py`：上述文件均在 `backend/app/tools/`；工具前实时授权。
- Modify `backend/app/graph/meeting_graph.py`、`backend/app/graph/nodes/leave_nodes.py`、`backend/app/api/routers/interrupts.py`：图及恢复的异步身份复核。
- Modify `backend/app/services/approval_service.py`、`backend/app/services/scheduler.py`：提交前权限版本与后台身份检查。
- Modify `backend/app/db/migrations.py`、`backend/app/main.py`：环境防误用、路由及精确 CORS/凭证配置。
- Modify `backend/app/db/session.py`：提交前复核当前账号/授权版本，统一覆盖服务事务提交，避免漏掉高影响写入。
- Modify `backend/tests/unit/test_authorization_service.py`、`test_startup_safety.py`：上述文件均在 `backend/tests/unit/`；覆盖异步和环境变化。
- Create `backend/tests/integration/test_identity_authorization.py`：禁用、调岗、跨资源和恢复身份。
- Create `changes/department-oa-foundation/authorization-inventory.md`：路由、下载、导出、工具与后台入口的权限映射证据。

### B4 Create/Modify

- Create `backend/app/services/organization_service.py`、`backend/app/schemas/organization.py`、`backend/app/api/routers/organization.py`：组织管理及生命周期 API。
- Create `backend/tests/integration/test_organization_access.py`：管理员、最后管理员、防环和范围测试。
- Create `frontend/src/api/organization.ts`、`frontend/src/stores/auth.ts`：会话单飞、当前用户与管理 API；认证请求集中在 store。
- Create `frontend/src/views/LoginView.vue`、`frontend/src/views/AccountView.vue`、`frontend/src/views/OrganizationView.vue`：中文登录、个人密码和组织管理。
- Modify `frontend/src/api/client.ts`、`frontend/src/router/index.ts`、`frontend/src/App.vue`、`frontend/src/utils/roles.ts`、`frontend/src/views/ConfigView.vue`：替换 Mock 身份假设、守卫、菜单和演示开关。
- Modify `frontend/src/stores/assistant.ts`：切换账号清除用户相关草稿和缓存。
- Modify `frontend/src/tests/setup.ts`：认证状态的显式测试初始化，不放宽断言。
- Create `frontend/src/tests/auth-session.test.ts`、`frontend/src/tests/auth-client.test.ts`、`frontend/src/tests/organization-access.test.ts`：登录/刷新单飞/失效、请求隔离及组织授权。
- Create `backend/scripts/m1_preview.py`、`frontend/playwright.m1.config.ts`、`frontend/e2e/m1-identity.spec.ts`：独立本地预览及桌面/手机验收。

### B5 Create/Modify

- Modify `backend/tests/conftest.py`、`backend/tests/unit/test_provider_bundle.py`：身份模式测试隔离和 Mock 兼容。
- Create `backend/tests/integration/test_identity_business_compatibility.py`：旧业务契约与本地身份兼容。
- Modify `frontend/playwright.m1.config.ts`、`frontend/e2e/m1-identity.spec.ts`：桌面/手机身份及管理验收，证据写入独立目录；`frontend/playwright.config.ts` 默认旧 Mock 套件排除此隔离用例。
- Create `docs/m1-identity-acceptance.md`、`changes/department-oa-foundation/reviews/verification.md`：真实运行结果、人工步骤和未验收范围。
- Create `changes/department-oa-foundation/decision-point-audit.md`：本轮授权、人工审查和验证的真实记录；不生成自动归档确认。
- Modify `README.md`：解释本地身份与 Mock 业务边界，提供明确初始化步骤，无凭证。

## Interfaces

B1 Produces：OAUser、OADepartment、OAPosition、OAMembership、OARole、OAPermission、OAUserRole、OARolePermission、OAAuthSession、OAAuthThrottle（SQLAlchemy ORM）；migration revision `0023`，down_revision `0022`，文件为 `0023_identity_foundation.py`，不改变历史迁移。

B2 Consumes：B1 ORM + AsyncSession；Produces：LoginInput、AccessGrant、CurrentUserView、PermissionView（Pydantic）及固定 JWT claims 字典；`resolve_access(token: str, *, session: AsyncSession) -> CurrentUser`、`rotate_refresh(raw: str, *, session: AsyncSession) -> IssuedSession` 均 async。内部 IssuedSession 持有 grant 与 refresh，路由只将 grant 序列化为 JSON，通过 Cookie 设置 refresh。

B3 Consumes：B2 resolve_access 及 B1 当前账号/角色；Produces：async `require_fresh_identity(actor: CurrentUser, required_roles: Iterable[str] = (), *, session: AsyncSession) -> CurrentUser`，async `authorize_tool(..., session: AsyncSession) -> AuthorizationDecision`，CurrentUser 新增可选会话与版本元数据；旧 resource 参数与响应兼容。

B4 Consumes：B2 AccessGrant/CurrentUserView、B3 权限；Produces：`GET /api/auth/me` 当前用户、`/api/organization/departments|positions|users|roles` 管理资源，写输入均通过 Pydantic 校验和明确字段字典；前端 `configureAuth(): Promise<void>`、`refreshSession(): Promise<void>`。

B5 Consumes：B1–B4；Produces：测试与人工验收证据，不产生“正式 OA 已上线”结论。

## 1. B1 数据结构

Depends on: 执行契约批准；不依赖旧 P1 批次批准。Covers M1-01。

- [x] 1.1 账号和组织模型。Red：在 `test_identity_models.py` 按表逐条添加唯一账号、部门引用、组织归属断言。Red Verify：每次仅运行新增用例确认缺失行为。Green：在 `models/identity.py` 每次实现一张模型并注册。Green Verify：通过当前模型测试。Refactor：统一字段和约束命名，不新增行为。
- [x] 1.2 会话及迁移。Red：在 `test_identity_foundation.py` 添加 0022 带数据升级、轮换记录及重复 upgrade 用例。Red Verify：在校验过的隔离库确认失败原因。Green：按组织/权限/会话分组补 migration，核对实际父 revision。Green Verify：逐组验证升级与历史数据。Refactor：检查索引和 downgrade 仅限本轮新增表，禁止运行开发库降级。

Interfaces：Consumes 现有 Base/TimestampMixin 与迁移配置；Produces B1 ORM 与扩张 migration。B1 通过前不执行 B2。

## 2. B2 口令和会话

Depends on: Batch B1。Covers M1-02、M1-03。

- [x] 2.1 凭证和初始化。Red：`test_credentials.py` 添加一次一个哈希验证、过期、错误算法/issuer/audience、弱密钥拒绝；集成用例验证重复初始化拒绝。Red Verify：运行新增用例。Green：逐函数实现 credential_service、DTO、配置及 bootstrap_admin。Green Verify：重跑对应用例，确认输出无敏感值。Refactor：统一过期与错误类型。
- [x] 2.2 登录轮换。Red：`test_identity_sessions.py` 添加错误锁定、并发失败、重启保持、并发刷新、重放族撤销、退出、CSRF/Origin。Red Verify：逐个确认缺行为。Green：按登录计数、会话签发、轮换、撤销各一个事务实现并接 auth 路由。Green Verify：运行对应并发与故障测试。Refactor：提取共享事务操作，敏感数据禁止打印。

Interfaces：Consumes B1；Produces B2 令牌 DTO 和 async 认证接口，公开业务响应沿用 ApiResponse。

## 3. B3 正式身份和授权接入

Depends on: Batch B2。Covers M1-04、M1-05 的业务访问、M1-08。

- [x] 3.1 身份 Resolver。Red：`test_identity_authorization.py` 添加 builtin 不读 Mock、禁用/调岗次请求、错误 JWT、ContextVar 不串人。Red Verify：每次运行新增断言。Green：实现 providers/identity、中间件和 deps，再迁移 authorization_service。Green Verify：当前身份及资源拒绝测试。Refactor：收敛错误和上下文清理。
- [x] 3.2 业务、工具和后台。Red：在 integration 和原有 unit 中分别添加服务调用、工具、图恢复、批准前权限变化测试。Red Verify：逐入口确认旧行为失败。Green：按 File Structure 的每个调用文件分别增加 await/session，并补范围过滤；每完成一个文件检索相邻调用。Green Verify：逐文件对应测试，再核对 inventory 全入口。Refactor：消除重复解析，禁止用请求旧角色或 Mock 补权。
- [x] 3.3 环境门禁。Red：`test_startup_safety.py` 覆盖 builtin 身份+Mock OA 的 production 拒绝、未知 provider、开发显式 Mock。Red Verify：确认新增用例失败。Green：修改 db/migrations 与 main 精确 CORS 和路由，保留业务 Provider 未完成的门禁。Green Verify：环境矩阵和现有启动测试。Refactor：错误信息中文且不含配置密钥。

Interfaces：Consumes B2；Produces B3 async 授权契约及授权 inventory。所有已发现调用点必须迁移，未覆盖入口不得进入 B4。

## 4. B4 管理 API 与界面

Depends on: Batch B3。Covers M1-05 管理、M1-06、M1-07。

- [x] 4.1 组织和生命周期。Red：`test_organization_access.py` 添加防环、最后管理员、权限越界、禁用审计失败回滚、启用不恢复会话。Red Verify：逐个用例确认失败。Green：按部门/岗位/成员/角色各一组实现 schema/service/router，并把变更及审计置于同事务。Green Verify：并发管理员保护与全组测试。Refactor：统一范围和变更版本处理，待交接标记不伪装转交完成。
- [x] 4.2 会话前端。Red：`auth-session.test.ts` 添加仅内存 access、刷新单飞、403 不刷新、失效清理、安全跳转。Red Verify：运行对应断言。Green：先 auth API/store，再 client、router、LoginView；每次只替换一个入口。Green Verify：组件及请求行为测试。Refactor：统一错误提示及退出清理。
- [x] 4.3 组织前端。Red：`organization-access.test.ts` 添加无权直达、当前权限菜单、无正式演示开关、组织编辑状态。Red Verify：确认缺行为。Green：OrganizationView、App/roles/Config 和 assistant 缓存，沿用现有界面模式；实施界面前使用适用 UI 技能。Green Verify：定向测试与构建。Refactor：检查桌面/手机文本、表格和表单不溢出。

Interfaces：Consumes B2/B3；Produces B4 管理接口、CurrentUserView 和客户端 session contract。

## 5. B5 集成验证与交付

B5 范围补记：`frontend/playwright.config.ts` 将隔离身份用例排除在旧 Mock 浏览器默认套件之外，避免误连旧预览环境；`report_query.py` 与 `work_task_service.py` 补来源模块授权及未正式接通来源的拒绝。

Depends on: Batch B4。Covers M1-01 至 M1-08 的联合验收。

- [x] 5.1 旧功能兼容。Red：`test_identity_business_compatibility.py` 覆盖本地身份的未授权旧资源拒绝、已授权新资源访问和明确 Mock 模式；更新现有异步测试 fixture。Red Verify：仅隔离库运行。Green：修复限定范围内集成问题并逐项更新 inventory。Green Verify：后端相关回归与前端测试/构建；根据跨模块影响决定完整回归。Refactor：移除测试中的意外 Mock 身份依赖，不放宽权限断言。
- [x] 5.2 浏览器和收尾。Red：Playwright 添加桌面/手机登录、登出、页面刷新、越权和组织管理断言。Red Verify：本地隔离服务验证失败点。Green：修正真实实现问题，禁止修改断言掩盖错误。Green Verify：截图/网络请求和必要回归，确认无敏感信息泄漏。Refactor：编写 acceptance、verification 和 README，明确未完成业务 Provider、未生产部署与人工待验收项。

Interfaces：Consumes B1–B4；Produces 实际测试证据、人工验收表和 M2 输入。任何未完成项保持未勾选，不借历史测试补当前证据。

## Requirement Coverage

| Requirement | Tasks | 验收来源 |
| --- | --- | --- |
| M1-01 | 1.1、1.2、5.1 | 迁移与旧数据 |
| M1-02 | 2.1、2.2、5.2 | 初始化、登录锁定 |
| M1-03 | 2.1、2.2、4.2、5.2 | JWT、轮换、撤销 |
| M1-04 | 3.1、3.2、5.1 | 当前身份与恢复 |
| M1-05 | 3.2、4.1、4.3、5.1 | 范围、组织、管理权 |
| M1-06 | 4.1、5.1 | 生命周期事务与审计 |
| M1-07 | 4.2、4.3、5.2 | 中文界面、会话与菜单 |
| M1-08 | 3.3、5.1、5.2 | 环境隔离与兼容边界 |
