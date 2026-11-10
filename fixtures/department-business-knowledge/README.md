# 部门业务标准模板资料包

本资料包用于 OA 智能助手的知识检索、流程引导、标准话术和业务试运行验证。所有资料均以“标准模板（试运行）”标注，不自动代表公司已经发布或强制执行的正式制度。

## 使用边界

- 可用于智能助手检索、引用、业务办理指引和内部试运行。
- 不得将模板中的建议时限、建议流程直接表述为公司正式生效规则。
- 正式执行前，应由责任部门结合公司实际管理要求修订，并由业务负责人审核确认。
- 模板中不设置未经确认的具体金额、个人账号、员工个人信息或密钥。
- 后续制度调整应通过知识版本升级完成，旧版本自动下线并保留审计记录。

## 资料清单

资料清单、文件路径、模板编号和责任部门以 `manifest.json` 为准。`questions.json` 仅用于验收提问，不导入知识库。

## 导入方式

在 `backend/` 目录执行：

```powershell
.\.venv\Scripts\python.exe .\scripts\import_department_standard_templates.py
.\.venv\Scripts\python.exe .\scripts\import_department_standard_templates.py --apply --username oa_admin
```

第一条命令仅做预检；第二条命令才会创建知识源、版本、切片、向量、租户授权和审计记录。重复执行时会根据内容哈希复用已发布版本。
