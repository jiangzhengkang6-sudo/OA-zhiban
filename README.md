# OA 智能体管理系统（部门级）

OA 智能体管理系统是一套面向 **5–10 人部门试点**、并预留 **50–100 人扩展能力** 的轻量化部门级 OA。系统以自建 OA 本体作为身份、组织、权限、单据、流程、通知和审计的业务权威，并通过 LangGraph 智能编排层提供自然语言办理、知识问答、会议纪要、合同审查、文档起草和任务提取等 AI 辅助能力。

> **当前状态**：部门级核心功能已完成本地工程实现、自动化测试和多项真实服务链路验证；服务器部署、HTTPS 域名、多人真实部门试用及持续备份运行仍在推进。仓库代码不是 Mock 演示版，生产上线以最终部署和验收结果为准。

## 一、核心能力

### 1. 正式 OA 本体

- **身份认证**：内置正式账号、argon2 口令哈希、JWT 访问令牌、Refresh Token、CSRF 防护和安全 Cookie 会话。
- **组织管理**：部门、岗位、直属上级、角色、成员启用/停用、调岗、批量维护和入转调离交接。
- **流程引擎**：固定版本流程、顺序审批、会签、或签、流程转交、中断恢复和发布版本控制。
- **业务单据**：请假、报销、正式工单，均具备草稿、提交、状态流转、附件和版本记录。
- **审批中心**：审批收件箱、办理人资格实时校验、限时审批委托、代批记录和防自审/链式委托控制。
- **请假额度**：额度查询、部门管理、余额并发占用控制和余额变动审计。
- **通知体系**：站内信、SMTP 邮件、企业微信群机器人；持久化发件箱、投递记录、幂等去重和失败重试。
- **审计与运维**：完整业务审计、审计导出、运行告警、独立巡检、降级控制和恢复演练。

### 2. 协同办公

- **部门公告**：草稿、发布、撤回、部门可见性、版本冲突保护和显式已读。
- **统一待办**：汇总本人当前审批席位和未完成业务任务，支持来源筛选、分页和截止时间排序。
- **会议管理**：会议发起、邀请、参会反馈、开始、结束、取消和纪要关联。
- **腾讯视频会议**：接入 TUIRoomKit，服务端按需创建房间并签发限时 UserSig，密钥仅保留在服务端。
- **会议转写**：TRTC ASR 实时回调、参会人语句保存、乱序去重、状态轮询和会议纪要草稿。
- **综合办公公共邮箱**：IMAP 收信、SMTP 发信、共享草稿、成员授权、邮件认领/处理和任务转换候选。
- **文档起草**：模板生成、有权限材料引用、版本比较、人工编辑和确认保存。
- **业务任务**：负责人、截止时间、状态跟踪、逾期提醒和来源追溯。

### 3. AI 智能编排

- **统一智能助手 V3**：单一对话入口自动调度知识、任务、会议、报表、工单和请假技能，支持短追问上下文；专项能力作为背后技能执行。所有高影响操作均先保存可复核草稿，经权限二次校验和本人确认后才写入。
- **标准模板资料库**：当前已发布 15 份“标准模板（试运行）”资料，覆盖员工手册、考勤请假、报销差旅、会议、公共邮箱、合同、信息安全和 IT 工单，共 245 个知识切片。
- **知识库问答**：先做权限过滤，再进行向量检索；回答展示可访问来源，证据不足时拒绝推断并转人工。
- **会议纪要**：将会议内容结构化为议题、决定和待办候选，经人工确认后才作为正式版本。
- **合同审查**：输出风险点、页码引文和规则版本；长合同通过 DeepAgents 进行计划与分块读取。
- **只读报表**：先登记查询计划，再在权限范围内读取数据，严格校验指标数字。
- **可降级设计**：关闭 AI 后，所有 OA 业务仍可通过中文人工工作台正常办理。

## 二、技术架构

| 层次 | 技术选型 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、Axios |
| 视频会议 | 腾讯云 TUIRoomKit、TRTC、TRTC ASR |
| 后端 | FastAPI、Pydantic v2、SQLAlchemy 2、Alembic |
| 智能编排 | LangGraph、LangGraph PostgreSQL Checkpointer、DeepAgents |
| 数据库 | PostgreSQL 16、pgvector |
| 通知渠道 | 站内信、SMTP/IMAP、企业微信群机器人 |
| 测试与质量 | Pytest、pytest-asyncio、Vitest、Playwright |

系统采用**模块化单体架构**：OA 业务、智能编排、通知、审计和运维能力分层清晰，但不引入微服务、通用 BPMN 引擎、Redis 或消息队列，以降低部门级试点的部署和维护复杂度。

## 三、架构边界

1. **OA 本体是最终业务权威**：流程状态、审批结果、余额、单据和组织信息以数据库和确定性服务为准。
2. **AI 不直接裁决高影响动作**：LLM 负责理解、检索、起草和建议；提交、批准、驳回、发送等操作必须由有权限的人确认。
3. **权限实时复核**：成员角色、部门、授权发生变化后，旧会话和后续请求立即按新权限处理。
4. **外部请求与业务事务隔离**：模型、邮件、企业微信等调用通过持久化发件箱和投递记录追踪，避免业务事务被外部服务阻塞。
5. **幂等与可恢复**：业务命令使用幂等键和版本前置条件；服务重启后不重复批准、扣减、创建任务或发送通知。
6. **安全默认关闭**：真实邮件、企业微信、模型探测、告警投递和附件扫描均需显式启用；配置不完整时不得默认放行。

## 四、目录结构

```text
├── backend/
│   ├── app/
│   │   ├── api/routers/      # FastAPI 路由
│   │   ├── core/             # 配置、枚举、错误码、上下文
│   │   ├── db/               # 数据库连接与启动校验
│   │   ├── graph/            # LangGraph 图与节点
│   │   ├── llm/               # 模型接入与意图提示词
│   │   ├── models/            # SQLAlchemy 模型
│   │   ├── ops/               # 运行监控与日志关键字
│   │   ├── providers/         # 会议转写、公共邮箱等外部能力提供方
│   │   ├── schemas/           # Pydantic 模型
│   │   └── services/          # 业务服务
│   ├── migrations/versions/  # Alembic 数据库迁移
│   ├── scripts/               # 验证、巡检、导入和运维脚本
│   └── tests/                 # 后端测试
├── frontend/
│   ├── src/
│   │   ├── api/               # 前端接口封装
│   │   ├── components/        # 通用组件和会议组件
│   │   ├── navigation.ts      # 导航与权限入口
│   │   ├── stores/            # 认证与全局状态
│   │   ├── styles/            # 全局样式
│   │   ├── tests/             # 前端单元测试
│   │   └── views/             # 业务页面
│   └── e2e/                   # 浏览器验证脚本
├── docs/                      # 实施、验收、运维和部署文档
├── fixtures/                  # 公开企业参考资料与问答样例
├── specs/                     # 规格说明
└── docker-compose.yml         # PostgreSQL 16 + pgvector
```

## 五、本地启动

### 1. 启动数据库

```powershell
docker compose up -d
```

默认启动 PostgreSQL 16 + pgvector，宿主机端口为 `5433`。

### 2. 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m alembic upgrade head
python run.py
```

部门级本地默认地址：

- 后端：`http://127.0.0.1:8015`
- 接口文档：`http://127.0.0.1:8015/docs`

### 3. 启动前端

```powershell
cd frontend
npm ci
$env:OA_BACKEND_PORT='8015'
npm run dev -- --host 127.0.0.1 --port 5182 --strictPort
```

前端地址：`http://127.0.0.1:5182`

### 4. 正式运行配置

正式 OA 模式使用：

```dotenv
AUTH_PROVIDER=builtin
OA_PROVIDER=builtin
LLM_PROVIDER=deepseek
LLM_FALLBACK_PROVIDER=ark
EMBEDDING_PROVIDER=ark
```

完整配置模板见：

- [backend/.env.formal-oa.example](backend/.env.formal-oa.example)
- [backend/.env.example](backend/.env.example)
- [模型配置说明](docs/model-configuration.md)
- [本地正式 OA 配置](docs/formal-oa-local-setup.md)

密钥只能保存在本机或服务器的 `.env` 中，禁止写入示例文件、文档、日志或前端代码。

## 六、测试与验证

### 自动化测试

- 后端全量测试最新记录：**1291 项通过**。
- 前端：**38 个测试文件、217 项测试通过**。
- 前端生产构建：通过。
- 数据库：Alembic 迁移当前版本为 `0038`。
- 真实链路：已验证 QQ 邮箱 SMTP/IMAP、企业微信机器人受理、腾讯视频房间、TRTC ASR 回调和纪要草稿生成。

### 前端测试命令

```powershell
cd frontend
npm test
npm run build
```

### 后端测试命令

```powershell
cd backend
python -m pytest tests/unit -q
```

涉及数据库清表、迁移或 API/图闭环的测试必须使用独立测试库，禁止对保存正式账号和业务数据的数据库执行重置型测试。完整操作见 [全功能测试流程](docs/全功能测试流程.md)。

## 七、部署前待完成事项

- 正式服务器、域名和内网 HTTPS 配置。
- 精确 CORS 来源、Secure Cookie、网络白名单和防火墙策略。
- 5–10 名真实成员参与的部门试用和业务闭环验收。
- 持续备份、异地副本和定期恢复演练。
- 附件病毒扫描服务接入；未扫描附件不得默认放行。
- 腾讯会议/TUIKit 上游传递依赖的安全升级与真实入会回归。

相关文档：

- [生产部署说明](docs/production-deployment.md)
- [回滚手册](docs/rollback-runbook.md)
- [运行告警运维说明](docs/operations-alerts.md)
- [真实业务与试用验收](docs/real-business-acceptance.md)
- [真实服务联调记录](docs/live-service-verification.md)

## 八、文档索引

### 产品与实施

- [正式 PRD V1.5](OA智能体管理系统-正式PRD-V1.5.md)
- [部门 OA 正式化实施计划](docs/部门OA正式化实施计划-V1.1.md)
- [V2 部门工作台交付说明](docs/v2-department-workbench.md)
- [业务与权限全景说明](项目业务与权限全景说明.md)

### 业务模块

- [会议管理](docs/meeting-management.md)
- [视频会议转写与纪要](docs/meeting-transcription.md)
- [腾讯会议接入配置](docs/tencent-meeting-setup.md)
- [综合办公公共邮箱](docs/public-mailbox.md)
- [企业微信群通知](docs/wecom-notifications.md)
- [业务通知与附件扫描](docs/notification-scanner-integration.md)

### 验收与运维

- [全功能测试流程](docs/全功能测试流程.md)
- [M1 身份与组织验收](docs/m1-identity-acceptance.md)
- [M2 人工流程验收](docs/m2-manual-oa-acceptance.md)
- [M4 本机恢复演练](docs/m4-drill-runbook.md)
- [项目总结](docs/project-summary.md)
