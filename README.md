# OA 智能体管理系统 MVP

部门 OA 正式化（更新：2026-10-20）：[PRD V1.5](OA智能体管理系统-正式PRD-V1.5.md)、[实施计划](docs/部门OA正式化实施计划-V1.1.md)、[M1 验收与启动说明](docs/m1-identity-acceptance.md)、[M2 验收与启动说明](docs/m2-manual-oa-acceptance.md)。M1/M2 与 M3 批准的本地工程范围已完成验证；M4 安全、备份、恢复、降级和部署演练仍未完成。

M3 [开发契约已获批准](changes/department-oa-business/execution-contract.md)，包括报销、正式工单、站内/SMTP、13 项核心桥接及 AI/P2/P3 正式权限；[验收报告](changes/department-oa-business/reviews/verification.md)和[继续入口](changes/department-oa-business/planning-status.md)。B1-B7 的批准本地范围已完成实施者串行验证，未宣称生产上线。

M2 按 [已批准执行契约](changes/department-oa-workflow/execution-contract.md) 完成 B1–B6，包含版本固定、会签/或签、私有材料、额度并发、转交、恢复及 AI 关闭的中文人工入口。[联合验证](changes/department-oa-workflow/reviews/verification.md)：后端 608 项通过（明确排除 1 项额外建库的历史迁移测试）、前端 87 项、浏览器 6 项与构建通过。M2 独立预览 `http://127.0.0.1:5194`、后端 `8014`，账号见本机忽略文件 `data/verification/m2/preview-login.txt`；通知当前仅保存待发送事件。

M1 独立预览为 `http://127.0.0.1:5193`，后端 `8013`；使用专用测试库和 Mock 模型，随机管理员凭证仅保存在本机忽略目录 `data/verification/m1/preview-login.txt`。builtin 身份与 OA 业务 Provider 分离，生产 Mock 门禁保留。未修改原业务库、真实 `.env`、豆包主用顺序或真实嵌入配置。

在现有 OA 之上增加的智能编排层，MVP 交付两个业务闭环：**智能请假审批** 与 **智能客服/工单**。
采用 Vue3 + TypeScript + Element Plus + FastAPI + LangGraph + PostgreSQL（pgvector）。

P2 已新增会议文本、文档起草和邮件工作台。文档支持模板、有权限材料引用、版本比较及人工确认；邮件支持分类、摘要、待办候选与回复草稿。当前确认仅保存平台记录。验收范围见 [文档验收记录](docs/p2-document-acceptance.md) 和 [邮件验收记录](docs/p2-email-acceptance.md)。

P3 已新增业务任务、只读报表和私有合同审查工作台。任务从授权来源提取并经人工确认创建；报表批准登记计划后查询权限范围内的数据；长合同在四节点 LangGraph 内实际调用 DeepAgents 进行计划及分块读取。P3 当时迁移至 `0022`，M1 新增 `0023`，M2 新增 `0024`（仅扩张正式业务表，禁止直接删除式降级）；工程验收及生产边界见 [P3 验收记录](docs/p3-acceptance.md)。原 P3 隔离预览地址为 `http://127.0.0.1:5182`，后端 `8012`，数据库为 `oa_agent_test`；该环境文本为豆包主用，嵌入为真实 ARK 1024 维，OA 与身份为 Mock，与 M1/M2 预览分开。

## 目录结构

```
├── docker-compose.yml   # PostgreSQL 16 + pgvector（端口 5433，避开宿主机 5432）
├── backend/             # FastAPI + LangGraph 后端
│   ├── app/
│   │   ├── core/        # 配置/枚举/错误码/上下文
│   │   ├── db/          # 数据库引擎与会话
│   │   ├── models/      # 9 张 ORM 表
│   │   ├── adapters/    # OAAdapter 协议 + MockAdapter
│   │   ├── llm/         # 模型抽象（Mock/ARK）
│   │   ├── tools/       # 工具白名单
│   │   ├── services/    # 会话/审计/策略/知识/调度
│   │   ├── graph/       # LangGraph SuperAgent + 三个子图
│   │   └── api/         # REST 路由
│   └── tests/           # 单元/图集成测试
└── frontend/            # Vue3 6 页面
```

## 快速启动

### 1. 启动数据库

```bash
docker compose up -d
```

> 注意：宿主机若已有 PostgreSQL 占用 5432，本项目的 Docker 数据库使用 **5433** 端口。

### 2. 启动后端

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m alembic upgrade head  # 首次部署和每次升级先迁移；不会清空现有业务表
python run.py                 # Windows：包含兼容的事件循环配置
```

后端接口文档：http://127.0.0.1:8001/docs（如需改端口，启动前设置 `OA_BACKEND_PORT`；前后端须使用同一值）

### 3. 启动前端

```bash
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```

访问：http://localhost:5173

### 4. 运行测试

```bash
cd backend
python -m pytest tests/unit -q    # 单元测试
```

API/图/迁移测试会写入或清理测试数据，必须在**单独数据库**运行：

```powershell
docker exec oa-agent-db createdb -U oa oa_agent_test  # 仅首次创建
cd backend
$env:ALLOW_TEST_DATABASE_RESET = 'true'
python -m pytest tests/migrations tests/api tests/graph -q
Remove-Item Env:ALLOW_TEST_DATABASE_RESET
```

测试夹具在执行任何清表前检查环境为 `test`、三个连接目标一致且数据库名以 `_test` 结尾。默认命令不会连接或清空开发数据库；勿将 `ALLOW_TEST_DATABASE_RESET=true` 写入生产配置。

## 关键设计

- **确定性规则优先**：字段/余额/权限/审批链用代码与 OA 接口裁决，LLM 只做理解与建议。
- **OA 是业务最终权威**：`agent_thread.id` 即 LangGraph `thread_id`，业务单据号 `business_id` 仅作幂等键。
- **HITL 审批门**：写工具严格在 `approve/edit/confirm` 之后调用，且幂等（幂等键 = 业务单据号/会话 ID）。
- **可恢复**：LangGraph PostgreSQL Checkpointer 保存中断点，重启后按 thread_id 恢复，不重复执行写操作。
- **可降级**：智能路径关闭或故障时回退原 OA，不阻断业务。

## Mock 账号（开发期）

| 用户 | 角色 | ID |
| --- | --- | --- |
| 张三 | 员工 | `u_emp_001` |
| 李四 | 审批人 | `u_mgr_001` |
| 王五 | 二级审批人 | `u_mgr_002` |
| 赵六 | 客服 | `u_cs_001` |
| 管理员 | 管理员 | `u_admin_001` |

显式 Mock 模式下，开发侧栏可切换演示账号；builtin 身份模式使用真实账号登录，不提供演示账号切换。管理权不自动授予敏感业务权限。

## 切换真实模型

文本模型支持 DeepSeek 主用、豆包兜底。运行本地后端时编辑 `backend/.env`；
Docker Compose 使用根目录 `.env`。完整配置见 [模型配置](docs/model-configuration.md)。

```
LLM_PROVIDER=ark
LLM_FALLBACK_PROVIDER=none
DEEPSEEK_API_KEY=<你的 DeepSeek API Key>
DEEPSEEK_CHAT_MODEL=deepseek-flash
ARK_API_KEY=<你的火山方舟 API Key>
ARK_CHAT_MODEL=<已开通且支持 JSON 与工具调用的豆包模型或接入点 ID>
EMBEDDING_PROVIDER=ark
ARK_EMBEDDING_MODEL=doubao-embedding-vision-251215
EMBEDDING_DIM=1024
```

DeepSeek 暂不可用，恢复后可切回 `deepseek` 主用、`ark` 兜底。首次切换真实嵌入需同步数据库列维度并重建已有向量，见模型配置文档。

## 切换真实 OA

按 [真实 OA HTTP Bridge 契约](docs/real-oa-bridge.md) 实现企业侧 bridge，并配置 `OA_PROVIDER=real`、`OA_BASE_URL`、`OA_API_KEY`。通过 `/api/readiness` 确认必需能力后再接入业务流。没有真实沙箱时不能宣称 OA 已接通；写操作不会自动重试，必须按原幂等键先对账。
