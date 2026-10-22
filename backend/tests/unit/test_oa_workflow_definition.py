"""Published workflow packages are finite, typed and deterministic."""
from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError


def definition():
    return dict(schema_version=1, scene='leave', entry_id='review',
        form=dict(leave_types=['annual', 'sick']), rules=dict(timeout_hours=48),
        nodes=[dict(id='review', kind='approval', mode='single',
                    selector=dict(kind='manager', levels=1), next_id='end'),
               dict(id='end', kind='end')])


def validate(value):
    from app.schemas.oa_workflow import ValidatedDefinition
    return ValidatedDefinition.model_validate(value)


def test_valid_definition_and_normalized_leave():
    from app.schemas.oa_leave import NormalizedLeaveFields
    result = validate(definition())
    assert result.nodes[0].selector.levels == 1
    fields = NormalizedLeaveFields.model_validate(dict(leave_type='annual',
        start_date='2026-12-31', end_date='2027-01-02', reason='休假', attachment_ids=[]))
    assert fields.days == 3
    assert fields.days_by_year == {2026: 1, 2027: 2}


@pytest.mark.parametrize('change', ['cycle', 'unknown', 'missing_end', 'unreachable',
    'amount', 'missing_default', 'duplicate_id', 'self_edge', 'invalid_type', 'no_approval'])
def test_invalid_definitions_rejected(change):
    value = definition()
    if change == 'cycle': value['nodes'][0]['next_id'] = 'review'
    if change == 'unknown': value['execute'] = 'eval'
    if change == 'missing_end': value['nodes'].pop()
    if change == 'unreachable': value['nodes'].append(dict(id='orphan', kind='end'))
    if change in {'amount', 'missing_default', 'invalid_type'}:
        value['entry_id'] = 'branch'
        value['nodes'].insert(0, dict(id='branch', kind='branch',
            cases=[dict(field='amount' if change == 'amount' else 'days', op='gt',
                        value='abc' if change == 'invalid_type' else 3, next_id='review')],
            default_next_id='review'))
        if change == 'missing_default': del value['nodes'][0]['default_next_id']
    if change == 'duplicate_id': value['nodes'].append(deepcopy(value['nodes'][0]))
    if change == 'self_edge': value['nodes'][0]['next_id'] = 'review'
    if change == 'no_approval': value['nodes'] = [dict(id='review', kind='end')]
    with pytest.raises(ValidationError): validate(value)


def test_condition_boundaries_and_exact_decimal():
    from app.services.oa_workflow_service import evaluate_condition
    assert evaluate_condition('days', 'gt', 3, {'days': 4})
    assert not evaluate_condition('days', 'gt', 3, {'days': 3})
    assert evaluate_condition('days', 'le', 3, {'days': 3})
    assert evaluate_condition('amount', 'eq', Decimal('0.30'), {'amount': Decimal('0.1') + Decimal('0.2')})
    assert evaluate_condition('leave_type', 'in', ['annual'], {'leave_type': 'annual'})


@pytest.mark.parametrize('extra', [dict(reason=''), dict(end_date='2026-10-17'),
    dict(start_date='not-a-date'), dict(days=999), dict(amount=3)])
def test_invalid_leave_fields(extra):
    from app.schemas.oa_leave import NormalizedLeaveFields
    value = dict(leave_type='annual', start_date='2026-10-18', end_date='2026-10-19', reason='休假')
    with pytest.raises(ValidationError): NormalizedLeaveFields.model_validate(value | extra)
