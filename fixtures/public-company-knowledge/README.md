# 公开企业制度与业务材料验收集

本资料集取自 GitLab 公开员工手册，供软件企业 OA 项目的知识检索、引用和拒答验收使用。核对日期为 2026-10-22。它不是行业统一标准，不代表本项目或中国企业已经采用这些规则，也不包含 GitLab 的内部单据、员工信息或真实交易。

`documents/` 为中文节译、摘要和办事清单；保留原企业、币种、适用条件和例外，不擅自改为人民币标准。改编内容按 GitLab 手册页面声明的 CC BY-SA 4.0 许可提供，署名 GitLab 及本项目整理者，修改包括中文翻译、节选和步骤归纳，无原企业背书。参见 https://creativecommons.org/licenses/by-sa/4.0/ 。

公开原文：

- 差旅与报销：https://handbook.gitlab.com/handbook/finance/expenses/
- 休假与离岗：https://handbook.gitlab.com/handbook/people-group/time-off-and-absence/time-away-philosophy/
- 权限申请：https://handbook.gitlab.com/handbook/eta/corporate-it/end-user-services/access-requests/
- 电脑报修：https://handbook.gitlab.com/handbook/eta/corporate-it/end-user-services/laptop-management/laptop-repairs/

`manifest.json` 固定原文地址和核对片段。工具抓取原始 Markdown 后在本地忽略目录保留字节、时间和 SHA-256；原文变更不自动修改摘要。页面页脚的许可声明也单独保存。入库使用正式知识来源、版本、原件、真实向量和部门绑定，不走旧版 mock 文档表。

`questions.json` 为整理者依据上述资料编写的评估题和参考答案，不是原企业公布的官方题库。情境题是合成案例，不计入真实业务单据。此文件不导入问答知识库，避免答案泄漏。入库材料包含四份制度/指南及两份依据原文整理的业务材料清单。

在 `backend/` 运行：

```powershell
.\.venv\Scripts\python.exe scripts/import_public_company_knowledge.py --fetch-sources
.\.venv\Scripts\python.exe scripts/import_public_company_knowledge.py --apply --username oa_admin
.\.venv\Scripts\python.exe scripts/verify_public_company_knowledge.py --username oa_admin
```

首次入库必须有成功的原文和许可快照。默认仅校验本地材料，不写数据库；`--apply` 才创建并发布。重复运行复用相同内容的已发布版本；遇到同名的不同内容、权限或过期版本则停止，避免覆盖既有制度。问答验收会创建明确标注的测试会话并记录审计，不发送外部通知。

2026-10-22 已在本地正式知识库发布 6 份材料、28 个片段，重复导入全部复用。最终 20 题真实问答通过自动检查，19 题回答、1 题安全转人工；无答案/边界题的转人工不计回答质量通过。先前分类误判及嵌入服务失败记录均保留，结果不代表本公司制度已生效或真实部门试用完成。完整结果和剩余验收项见[真实业务验收](../../docs/real-business-acceptance.md)。
