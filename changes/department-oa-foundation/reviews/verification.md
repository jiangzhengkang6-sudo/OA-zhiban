# M1 B5 验证与人工审查

日期：2026-10-18。结论：通过 M1 本地工程验收，B1–B5 完成。仅覆盖已批准的账号、会话、组织和权限底座；不表示 OA 生产可上线。当前实施者按用户批准的人工流程完成代码复核，无独立审查 agent、机器收据或 Git SHA。

## 实际运行结果

后端环境：ENVIRONMENT=test；三类数据库连接均指向 oa_identity_m1_test；允许重置仅在命令环境中启用；LLM、嵌入、OA 和默认身份为 Mock，身份用例显式切换 builtin。预览使用另一个 oa_identity_m1_preview_test，不与 pytest 共用数据库。迁移用例另外创建随机临时 *_test 数据库并释放。

| 检查 | 实际命令 | 结果 | 本地原始证据 |
| --- | --- | --- | --- |
| 后端全部测试 | backend/.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short | 516 passed，0 failed，0 skipped，17 warnings，189.76s | data/verification/m1/backend-full.txt |
| 兼容最终补验 | 同一解释器 -m pytest backend/tests/integration/test_identity_business_compatibility.py -q --tb=short | 10 passed，0 failed，0 skipped；含全量运行后追加的空来源缓存断言 | data/verification/m1/compatibility-final.txt |
| 前端全部测试 | frontend 下 npm test | 19 文件，74 passed，0 failed | data/verification/m1/frontend-tests.txt |
| 类型检查及构建 | frontend 下 npm run build | exit 0，vue-tsc 与 Vite 构建成功，5.84s | data/verification/m1/frontend-build.txt |
| 桌面/手机浏览器 | frontend 下 npx playwright test --config=playwright.m1.config.ts | 2 passed，0 failed；重启最终后端后复验，7.4s | data/verification/m1/browser-tests.txt、browser-result.json |
| 初始化 CLI | backend 下 .venv/Scripts/python.exe -m app.cli.bootstrap_admin --help | exit 0；username 参数存在；未对原业务库初始化 | 实际命令输出已核对 |
| 预览连通 | GET 5193/login 及 5193/api/auth/config | 200；provider=builtin | 实际 HTTP 返回已核对 |

复现环境及命令见 [验收说明](../../../docs/m1-identity-acceptance.md)。测试进程均已结束，隔离预览服务保留供本地查看。

## 失败与修复记录

- B1 新模型缺失导致新增测试失败；补模型、注册与扩张迁移，修复联合唯一约束命名后通过。
- B2 凭证/身份服务和 auth 路由缺失导致新增用例失败；补实现后登录、锁定、轮换、重放、Origin/CSRF 和改密测试通过。
- B5 扩大回归曾出现 492 passed、11 failed：文档模板/报表指标/合同上传路由及工作任务创建人漏改 async 身份调用、未知受派人错误状态、校验 detail 契约、历史 P3 迁移断言等；修正后定向 11 passed，再完整回归 510 passed。
- 自定义角色被旧 employee/approver/admin/ops 通用白名单拦截：新增失败用例后，Mock 保留原语义，builtin 依据资源权限；专用管理员/审批人限制保留。
- 旧全局管理接口尚未完成正式租户隔离：增加 builtin 503 的失败关闭和 5 个拒绝用例。随后一次全量为 510 passed、5 failed，原因是新增测试构造 Starlette Request 缺 headers；修正测试请求字段后定向通过。
- 来源检查用例先失败：仅有 work_task read 的账号读取会议来源时未先检查 meeting read。补来源资源权限、关闭 builtin 旧工单/审批来源，报表缓存空 source_ids 同样检查来源授权。最终兼容 10 passed。
- Windows Python 3.14 预览使用 Uvicorn 默认事件循环与 psycopg 不兼容，独立预览脚本使用已有 Selector 策略并以 loop=none 启动；最终浏览器复验通过。

不补造每个规划步骤的独立 Red 日志。早期失败保留于本地验证输出及批次人工审查记录，最终结果以上表为准。

## 需求与实现复核

| 维度 | 结论 | 证据与限制 |
| --- | --- | --- |
| 完整性 | PASS | M1-01 至 M1-08 对应验收矩阵、B1–B5 和真实测试；初始化、迁移、会话、组织生命周期、业务范围及前端闭环已实现 |
| 正确性 | PASS | 并发失败锁定/刷新重放、最后管理员竞争、审计回滚、提交前版本/会话、跨租户/部门、调岗失效、来源权限和后台失效路径通过 |
| 一致性 | PASS | 独立身份 Provider、异步复核、ApiResponse/CurrentUser 兼容；组织 users、auth configureAuth/refreshSession 及实际浏览器文件名已回写文档 |
| 范围 | PASS | 未实施 M2/M3、生产部署、真实人员导入或 Mock 历史映射；未改真实 .env、原业务数据库或模型优先级；本轮零付费模型调用 |

账号/权限管理获取租户事务锁和账号有序行锁，业务 before_commit 复核当前状态及版本；管理自身生命周期变更只在持锁且已授权后移除自身旧快照。组织管理员不隐含敏感业务读取权，自定义角色写权限必须包含相同或更大范围读权限。builtin 未接通的全局管理、旧业务和来源均明确拒绝。

授权入口复核见 [清单](../authorization-inventory.md)。截图 organization-desktop.png、organization-mobile.png、login-mobile.png 已目视检查，无内容重叠或敏感凭证；手机表格横向滚动显示其余列。

## 工程提示与未验收范围

Python 17 条提示为 Windows 事件循环 API、历史 datetime.utcnow 和 re.split 参数弃用提示；前端测试有组件 stub 提示，构建有约 1.28 MB 主包的体积提示。均未造成测试或构建失败，后续性能优化可单独安排。

旧 Mock 浏览器全套集成用例本轮未重跑；新的隔离身份用例已从默认旧浏览器套件排除，避免误连旧服务或记录认证 trace。没有生产压测、渗透测试、备份恢复演练及正式业务用户验收。合同、任务批次/来源和报表来源保留更窄条件；多标签页 refresh 竞争可能要求重新登录。上述边界与现阶段交付范围一致，详见验收说明。

本轮工程记录齐备，尚未执行正式归档或主规格合并，也没有记录用户未做出的归档确认。
