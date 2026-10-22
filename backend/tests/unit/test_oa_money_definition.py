from copy import deepcopy

import pytest
from pydantic import ValidationError


def reimbursement_definition():
    return dict(schema_version=1,scene='reimbursement',entry_id='amount',
        form=dict(categories=['travel','office']),rules=dict(timeout_hours=48),
        nodes=[dict(id='amount',kind='branch',cases=[dict(field='amount',op='le',value='1000.00',next_id='review')],default_next_id='high'),
            dict(id='review',kind='approval',mode='single',selector=dict(kind='manager',levels=1),next_id='end'),
            dict(id='high',kind='approval',mode='single',selector=dict(kind='manager',levels=1),next_id='end'),dict(id='end',kind='end')])


def fields(amount='1000.00',**extra):
    from app.schemas.oa_reimbursement import ReimbursementFields
    return ReimbursementFields.model_validate(dict(purpose='差旅报销',expense_date='2026-10-19',category='travel',amount=amount,currency='CNY')|extra)


@pytest.mark.parametrize('amount,cents,formatted',[('0.01',1,'0.01'),('1',100,'1.00'),('1.2',120,'1.20'),('999999999.99',99999999999,'999999999.99')])
def test_exact_money(amount,cents,formatted):
    result=fields(amount)
    assert result.amount_minor==cents and result.amount==formatted


@pytest.mark.parametrize('amount',['0','-1','+1','1e3','NaN','Infinity','1.001',' 1','1 ','1\n','.1','1.','9999999999',1,1.2,True,None])
def test_invalid_money(amount):
    with pytest.raises(ValidationError): fields(amount)


def test_currency_and_duplicate_invoices():
    for extra in [dict(currency='USD'),dict(attachment_ids=['same','same'])]:
        with pytest.raises(ValidationError): fields(**extra)


@pytest.mark.parametrize('amount,match',[('999.99',True),('1000.00',True),('1000.01',False)])
def test_published_amount_boundary(amount,match):
    from app.services.oa_workflow_service import validate_definition,evaluate_condition
    value=validate_definition(reimbursement_definition())
    condition=value.nodes[0].cases[0]
    assert evaluate_condition('amount',condition.op,condition.value,{'amount':fields(amount).amount_minor}) is match
    assert validate_definition(value.model_dump(mode='json')).model_dump(mode='json')==value.model_dump(mode='json')


@pytest.mark.parametrize('field,value',[('days',1),('leave_type','annual'),('amount','1.001'),('amount',1000),('amount',' 1000')])
def test_scene_rejects_wrong_condition(field,value):
    from app.services.oa_workflow_service import validate_definition
    package=deepcopy(reimbursement_definition())
    package['nodes'][0]['cases'][0].update(field=field,value=value)
    with pytest.raises(ValidationError): validate_definition(package)
