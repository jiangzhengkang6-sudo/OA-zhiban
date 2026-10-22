# 模型配置

文本和嵌入均已启用真实模型。2026-10-15 按用户要求临时改为豆包（ARK）主用，
停用 DeepSeek 兜底；保留其凭据，恢复后再切回。OA、身份和业务数据仍使用 Mock。

## 启用

本地后端从 `backend/` 启动，读取 `backend/.env`；Compose 读取根目录 `.env`。
将 `backend/.env.llm.example` 中的条目合并到对应配置文件，保留原有数据库及 OA 配置：

```dotenv
LLM_PROVIDER=ark
LLM_FALLBACK_PROVIDER=none
LLM_TIMEOUT_SECONDS=10
MEETING_LLM_TIMEOUT_SECONDS=45
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=
DEEPSEEK_CHAT_MODEL=deepseek-flash
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_API_KEY=
ARK_CHAT_MODEL=doubao-seed-2-1-turbo-260628
ARK_THINKING_TYPE=disabled
EMBEDDING_PROVIDER=ark
ARK_EMBEDDING_MODEL=doubao-embedding-vision-251215
EMBEDDING_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal
EMBEDDING_API_KEY=
EMBEDDING_DIM=1024
EMBEDDING_TIMEOUT_SECONDS=30
```

填写自己的 API Key 和已开通的豆包模型名或 `ep-...` 接入点 ID，然后重启后端。
嵌入可使用独立 Key；留空时复用 `ARK_API_KEY`。当前本地配置已填好，无需重复填写。
豆包配置须同时支持 JSON 输出与工具调用，具体可用模型以账号控制台为准。
DeepSeek 默认使用非思考模式，避免主备工具调用历史包含不同厂商的推理字段。
当前豆包也显式关闭思考，以减少意图识别等待并满足 10 秒请求预算。
`ARK_THINKING_TYPE` 支持 `default`（省略参数）、`disabled`、`enabled`、`auto`；
须按实际模型能力设置，其他 ARK 模型默认省略该参数，避免兼容性问题。
启动环境变量优先于 `.env`；若启动脚本显式指定 `LLM_PROVIDER=mock`，也需要修改该值。
本地含 Key 的 `.env` 已忽略提交，不要把真实 Key 写进样例或前端。

本地也兼容用户已填写的别名：`DEEPSEEK_MODEL`、`DOUBAO_API_KEY`、
`DOUBAO_BASE_URL`、`DOUBAO_MODEL_NAME`、`EMBEDDING_MODEL`。
同一项同时填写时，以标准名称为准；Compose 使用上面展示的标准名称。
DeepSeek 恢复后将 `LLM_PROVIDER=deepseek`、`LLM_FALLBACK_PROVIDER=ark`，再重启后端。

## 接入范围

| 功能 | 模型职责 |
| --- | --- |
| 意图识别、工单、请假 | 分类与结构化提取；原有权限、规则及审批保留 |
| 知识问答 | 基于已授权检索片段生成回答 |
| 会议纪要 | 生成议题、决策与待办候选，校验来源并要求人工确认 |
| 文档起草、邮件 | 生成草稿；原有引用校验与人工审核保留 |
| 业务任务 | 提取候选；人员、期限与任务创建仍由原流程确认 |
| 报表 | 生成定性摘要；统计值由登记查询产生，继续禁止模型编造数字 |
| 长合同 | DeepAgents 计划与分块读取；工具白名单、原文证据校验保留 |

短合同继续使用既有规则检查。文本模型切换不会发送邮件、发文或绕过审批。

## 兜底与预算

- 单次生成至多请求主模型一次、兜底模型一次，不叠加 SDK 重试；每次请求默认总超时 10 秒。
- 会议生成单独使用 `MEETING_LLM_TIMEOUT_SECONDS`（默认 45 秒，最大 60 秒），
  覆盖 HTTP 等待与总截止时间；浏览器生成、重试及重新生成允许最多 130 秒，
  包含主备各一次的等待和检查点保存。分类与其他生成继续使用 10 秒预算。
- 仅网络错误、超时、HTTP 408/429/5xx 触发切换；双方失败即返回失败，不自动改用 Mock。
- 会话消息遇到模型临时不可用时保留用户消息、置为 PAUSED，并返回 502 及明确提示；
  服务恢复后可重新发送，相同幂等键不会重复执行。
- Key/模型配置缺失、400/401/403/404/422、空输出、截断及 JSON/schema 校验失败直接报错。
- 主备各用自己的模型配置，临时主模型覆盖值不会传给豆包。
- 任务和报表每次逻辑生成至多两次请求，每次输出上限 2048 tokens；
  会议、文档、邮件为 4096 tokens。长合同仍最多 22 次实际请求，含兜底请求，整体不超过原有 120 秒。
- 报表、任务及成功长合同的用量按实际接收请求的提供方记录；未返回用量标记为缺失，不推算费用。
  当前未扩展所有模块的用量统计，也未新增失败长合同的用量落库。

## 向量模型

`EMBEDDING_PROVIDER` 独立于文本设置，不随文本主备切换。当前使用真实 ARK 嵌入，
配置与数据库列均为 1024 维。实测当前模型不接受 1536 维，1024 维调用通过。
多模态接口的一组输入只生成一个融合向量，因此每段文本单独请求，保持片段与向量对应。

旧开发库 2 个片段已重建，预览库列维度已同步调整；FAQ 修复复测时已有 1 份文档、2 个片段。
切换嵌入模型或维度后，
即使维度相同也必须重新生成已有向量，不能混用不同模型或 Mock 向量。
从 `backend/` 运行：

```bash
python scripts/reindex_knowledge.py          # 只检查，不请求模型或修改数据库
python scripts/reindex_knowledge.py --apply  # 真实请求并重建，按模型服务计费
```

脚本先生成全部向量，再备份旧向量至忽略提交的 `data/backups/`，最后事务内修改列和数据。
原文、来源与 ID 保留；模型失败或检测到并发修改时终止，不覆盖原有数据。
新安装数据库完成 Alembic 迁移后，也须检查并同步向量列维度。
检索阈值需要用实际业务问答集校准；旧 Mock 阈值不能作为真实模型的质量验收标准。

## 验证边界

离线测试覆盖路由、预算、敏感响应隐藏及知识权限过滤；真实调用已验证嵌入、
中文语义检索、基于来源的结构化回答及豆包工具调用。DeepSeek 生成暂不可用，
按用户要求临时停用。少量冒烟测试不能替代完整业务质量、限流及负载验收。

接口依据（2026-10-15 查阅）：

- DeepSeek：<https://api-docs.deepseek.com/api/create-chat-completion>
- DeepSeek JSON：<https://api-docs.deepseek.com/guides/json_mode>
- 火山方舟 Chat：<https://www.volcengine.com/docs/82379/1298454>
