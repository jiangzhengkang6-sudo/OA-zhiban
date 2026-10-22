"""Versioned templates and conservative advisory checks, not legal/DLP certification."""

import re

from ..schemas.document import DocumentCheck, DocumentTemplate


TEMPLATES = {
    "official": DocumentTemplate(id="official", kind="official", name="公文", version=1, sections=["主送对象", "依据", "正文", "执行要求"]),
    "notice": DocumentTemplate(id="notice", kind="notice", name="通知", version=1, sections=["通知对象", "通知事项", "时间安排", "执行要求"]),
    "report": DocumentTemplate(id="report", kind="report", name="报告", version=1, sections=["报告对象", "背景与依据", "主要情况", "后续安排"]),
    "summary": DocumentTemplate(id="summary", kind="summary", name="摘要", version=1, sections=["摘要对象", "材料依据", "核心要点", "待确认事项"]),
}

_SENSITIVE = re.compile(
    r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\d)|"
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"(?:密码|口令|API\s*Key|token)\s*[:：=]\s*\S+", re.IGNORECASE
)


def check_document(body: str, template: DocumentTemplate) -> list[DocumentCheck]:
    issues = []
    if not body.strip():
        issues.append(DocumentCheck(code="EMPTY_BODY", severity="error", message="正文不能为空"))
    headings = set(re.findall(r"^##\s+(.+?)\s*$", body, re.MULTILINE))
    for heading in template.sections:
        if heading not in headings:
            issues.append(DocumentCheck(code="MISSING_SECTION", severity="error", message=f"缺少模板章节：{heading}"))
    if re.search(r"\[待补充\]|\[待确认\]|\{\{.+?\}\}", body):
        issues.append(DocumentCheck(code="UNRESOLVED_PLACEHOLDER", severity="error", message="正文仍含待补充或待确认占位内容"))
    if _SENSITIVE.search(body):
        issues.append(DocumentCheck(code="SENSITIVE_DATA", severity="warning", message="正文可能包含联系方式、身份号码或凭据，请人工核对密级和发文范围"))
    return issues
