# 前端工具链升级与本地交付验证

验证日期：2026-10-22。工作分支：`codex/m1-identity-foundation`。

## 交付结论

前端开发依赖的 6 项已知漏洞已清除；本地单元测试、生产构建、桌面与手机浏览器回归、容器全新安装及 HTTP 检查均通过。本结论仅覆盖本次工具链升级和所列合成场景，不代表生产上线验收完成。

M4 已完成本地验证并进入逻辑收尾，记录提交为 `4ebee82`。此次新建独立变更 `changes/frontend-toolchain-hardening`，不改写 M4 原有历史验收口径。尚未合并分支、推送远端或部署服务器。

## 变更内容

| 项目 | 原版本范围 | 本次版本范围 |
| --- | --- | --- |
| Vite | ^5.4.8 | ^7.3.7 |
| Vitest | ^2.1.9 | ^4.1.12 |
| Vue 构建插件 | ^5.1.4 | ^6.0.10 |

- 更新 `frontend/package.json` 和 npm 锁文件；运行时依赖声明及已有运行时锁条目保持不变。
- 声明 Node.js 要求为 `^20.19.0 || >=22.12.0`；容器使用项目现有 Node 22 构建阶段。
- `frontend/vite.config.ts` 默认仅监听本机，显式保留原构建目标 `es2020 / Edge 88 / Firefox 78 / Chrome 87 / Safari 14`。这属于编译目标设置，未实际验证所有这些浏览器版本。
- 增加 `frontend/playwright.isolated.config.ts` 和 `test:e2e:isolated` 命令；独立端口、独立测试服务、全量 API 拦截及失效后端代理端口防止误连正常后端。
- 修正 P1 角色菜单和 P2 会议旧用例的认证配置、平台标题和中文确认按钮断言。未修改业务权限或登录逻辑。

## 验证结果

下列命令从仓库根目录执行，浏览器测试使用本机 Microsoft Edge。

| 检查 | 命令 | 实际结果 |
| --- | --- | --- |
| 全部 npm 依赖审计 | `npm --prefix frontend audit --registry=https://registry.npmjs.org --json` | 从 6 项降为 0 项，包括开发依赖；原有 3 项中危、1 项高危、2 项严重 |
| 前端单元回归 | `npm --prefix frontend test -- --reporter=dot` | 25 个文件、119 项通过 |
| 类型检查和生产构建 | `npm --prefix frontend run build` | `vue-tsc -b` 与 Vite 构建通过 |
| 隔离浏览器回归 | `npm --prefix frontend run test:e2e:isolated` | 桌面 18 项、手机 18 项，共 36 项通过，0 跳过、0 不稳定用例，约 48 秒 |
| 干净容器构建 | `docker build --pull=false -t oa-toolchain-frontend:local ./frontend` | Dockerfile 中 `npm ci` 和生产构建通过，安装审计 0 项漏洞 |
| 容器 HTTP 验证 | `./backend/.venv/Scripts/python.exe backend/scripts/m4_frontend_smoke.py --frontend-image oa-toolchain-frontend:local` | 健康接口、页面路由、JS/CSS 资源、GET/POST 转发、404 保留、后端中断 502、静态健康检查均通过 |
| 改动格式检查 | `git diff --check` | 通过 |

浏览器覆盖五类演示角色菜单、会议草稿编辑/确认/拒绝、网络响应丢失后的幂等重试、访问撤销、审计跳转，以及正式身份模拟下的请假/工单确认、冲突和恢复对账。P1/P2 使用演示认证接口替身，M3 使用正式认证接口替身；它们不能证明真实后端权限校验。已查看桌面 1440×960 与手机 390×844 的请假确认截图；M3 用例同时检查页面无横向溢出。

初次浏览器执行因旧用例缺少 `/api/auth/config` 模拟响应而跳转登录页；修正后发现会议用例仍查找英文 `OK`，而界面已改为中文 `确定`。更新测试后完整 36 项通过，无需修改产品代码。容器安装耗时约 176 秒，最终成功；未修改 Docker 全局网络或镜像源配置。

镜像标识：`oa-toolchain-frontend:local`，ID 为 `sha256:9352c417c7de65b97157c5d3c151de3602076513d615df167b9b32daae08c33b`。浏览器原始结果及截图保存在本地忽略目录 `data/verification/toolchain/`。HTTP 检查仅使用私有 internal 网络和临时合成后端，临时容器、网络及浏览器测试服务已清理。

## 边界与后续

- 构建仍提示主 JS 包约 1.29 MB、gzip 约 415 KB，可后续按加载性能数据进行拆包；当前构建成功，不将提示隐藏。
- 部分单元用例存在路由和图标测试替身警告，未影响通过结果；本次未扩大范围改写它们。
- npm 审计结果仅说明本次查询未报告已知 npm 漏洞，不包含容器操作系统扫描、渗透测试或未来新增漏洞。
- 未读取真实 `.env`、连接现有业务数据库、调用模型/OA/邮件/企业微信或发送真实通知。本次未改动后端，复用 M4 已有后端和恢复证据，不重复整套恢复演练。
- 原 M4 的根目录参考文档通过 `.git/info/exclude` 精确本地排除处理，9 份文档哈希未改变；未加入共享忽略规则，未删除或移动文档。
- 后续应在明确测试账号、样例数据和通知收件范围后开展真实服务业务联调。服务器准备好后再验收 HTTPS、网络访问控制、异地恢复、生产容量、历史生产版本回滚及持续备份运行。
