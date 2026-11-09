"""Semantic check failures cannot be hidden by successful HTTP responses."""
import pytest
from types import SimpleNamespace

from scripts.verify_project_model_quality import automated_failures, failure_code


@pytest.mark.parametrize('failure', ['retrieval', 'intent', 'terms', 'transport', None])
def test_quality_evaluation_detects_incorrect_outputs(failure):
    report = dict(retrieval=[dict(case='policy', correct=failure != 'retrieval')], results=[
        dict(provider='primary', case='intent', correct=failure != 'intent'),
        dict(provider='primary', case='answer', lexical_checks_pass=failure != 'terms'),
        dict(provider='primary', case='missing_evidence', manual_semantic_review='PENDING'),
    ])
    if failure == 'transport':
        report['results'].append(dict(provider='fallback', case='answer', error='generation_failed'))
    assert bool(automated_failures(report)) == (failure is not None)


@pytest.mark.parametrize('status,expected', [
    ('unavailable', 'unavailable'), ('rejected', 'rejected'),
    ('invalid_output', 'invalid_output'), ('sensitive-provider-text', 'generation_failed'),
    (None, 'generation_failed'),
])
def test_quality_error_codes_never_expose_provider_text(status, expected):
    client = SimpleNamespace(last_attempts=[{'status': status}] if status else [])
    assert failure_code(client) == expected
