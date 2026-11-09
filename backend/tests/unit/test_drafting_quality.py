from scripts.verify_drafting_quality import checks_for


def test_quality_check_rejects_missing_actions_and_unapproved_reply_promise():
    sample = dict(summary='维护准备', action_items=[], reply_body='已收到。')
    assert not all(checks_for('email', sample).values())
    sample['action_items'] = [dict(title='整理维护清单', assignee_candidate=None,
        due_at_candidate=None, needs_confirmation=True)]
    assert all(checks_for('email', sample).values())
    sample['reply_body'] = '我会整理维护清单，完成后向您反馈。'
    assert not checks_for('email', sample)['no_unapproved_commitment']
    sample['reply_body'] = '已收到，请确认负责人和截止时间。'
    sample['action_items'][0]['assignee_candidate'] = 'invented-person'
    assert not checks_for('email', sample)['missing_metadata_not_invented']
