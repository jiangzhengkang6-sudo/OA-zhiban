"""Synthetic engineering acceptance; no legal quality claims."""
import json
from pathlib import Path
import pytest
from app.services.contract_parser import parse_text, validate_evidence
from app.services.contract_rules import check_rules, RULE_VERSION

DATA = json.loads(Path(__file__).with_name('p3_contract_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', DATA['development'] + DATA['acceptance'], ids=lambda case:case['id'])
def test_contract_evidence_and_missing_range(case):
    parsed = parse_text(case['text'])
    risks = check_rules(parsed)
    assert {risk['rule_id'] for risk in risks if not risk['missing']} == set(case['present'])
    assert len(risks) == 4 and {r['rule_version'] for r in risks} == {RULE_VERSION}
    for risk in risks:
        validate_evidence(parsed, risk['evidence'], missing=risk['missing'])
        evidence = risk['evidence']
        if risk['missing']:
            assert evidence['quote'] == '' and evidence['end'] == len(parsed['text'])
        else:
            assert parsed['text'][evidence['start']:evidence['end']] == evidence['quote']
