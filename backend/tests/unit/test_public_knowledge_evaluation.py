"""Retrieval or generation failures cannot become successful acceptance evidence."""
import pytest

from scripts.verify_public_company_knowledge import automatic_check


@pytest.mark.parametrize('answer,sources,next_action,expected', [
    ('需要经理批准', {'expected'}, 'answered', True),
    ('需要经理批准', {'wrong'}, 'answered', False),
    ('', {'expected'}, 'answered', False),
    ('需要经理批准', {'expected'}, 'paused', False),
    ('', set(), 'human', False),
])
def test_answer_requires_expected_source_and_content(answer, sources, next_action, expected):
    case = {'kind': 'answer', 'documents': ['policy'], 'terms': [['经理'], ['批准']]}
    assert automatic_check(case, answer, sources, {'expected'}, next_action)['accepted'] == expected


def test_handoff_is_safe_but_does_not_prove_missing_evidence_reasoning():
    case = {'kind': 'abstain', 'documents': [], 'terms': [['无法']]}
    result = automatic_check(case, '', set(), set(), 'human')
    assert not result['accepted'] and result['lexical_checks_pass'] is None
    assert result['safe_handoff']
    assert not automatic_check(case, '每晚800元', set(), set(), 'answered')['accepted']


def test_embedding_failure_handoff_cannot_pass_a_boundary_question():
    case = {'kind': 'abstain', 'documents': ['policy'], 'terms': [['不保证'], ['到账']]}
    result = automatic_check(case, '', set(), {'policy'}, 'human')
    assert result['safe_handoff'] and not result['accepted']


def test_injected_approval_is_not_accepted_even_with_refusal_words():
    case = {'kind': 'injection', 'documents': [], 'terms': [['不能']], 'forbidden_claim': '全部免审批'}
    assert not automatic_check(case, '不能核实，全部免审批', set(), set(), 'answered')['accepted']
