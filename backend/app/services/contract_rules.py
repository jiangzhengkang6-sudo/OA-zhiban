"""Versioned demonstration checks, never legal determinations."""
from .contract_parser import validate_evidence

RULE_VERSION = 'demo-1'
RULES = [
    ('payment', '付款条件', ('付款', '支付', 'payment')),
    ('breach', '违约责任', ('违约', 'liability', 'breach')),
    ('termination', '终止条款', ('终止', '解除', 'termination')),
    ('dispute', '争议解决', ('争议', '仲裁', '法院', 'dispute')),
]


def check_rules(parsed, *, rules=None, rule_version=None):
    risks = []
    for rule_id, name, words in RULES if rules is None else rules:
        paragraph = next((p for p in parsed['paragraphs'] if any(w in p['quote'].lower() for w in words)), None)
        evidence = paragraph or dict(start=0, end=len(parsed['text']), page=1, paragraph=0, quote='')
        risk = dict(risk_id=rule_id, rule_id=rule_id, rule_version=rule_version or RULE_VERSION, name=name,
            severity='medium' if paragraph else 'high', missing=paragraph is None,
            applicability='通用合同演示检查', source='内置演示规则（无法规效力）', evidence=evidence,
            suggestion='请人工核对条款完整性及适用性' if paragraph else '未检出对应条款，请人工核验全文并补充约定')
        validate_evidence(parsed, evidence, missing=risk['missing'])
        risks.append(risk)
    return risks

