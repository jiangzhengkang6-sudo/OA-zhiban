from datetime import datetime, timedelta, timezone
import pytest
from app.core.config import Settings
from app.services.credential_service import hash_password, verify_password, encode_access, decode_access


def settings():
    return Settings(_env_file=None, auth_jwt_secret='test-only-secret-' * 4)


def test_argon2_and_invalid_password():
    hashed = hash_password('Test-password-123!')
    assert hashed.startswith('$argon2id$')
    assert verify_password('Test-password-123!', hashed)
    assert not verify_password('incorrect', hashed)
    with pytest.raises(ValueError):
        hash_password('short')


def test_jwt_fixed_claims_expiry_and_secret():
    s = settings()
    token = encode_access('u', 's', 1, s)
    assert decode_access(token, s)['sid'] == 's'
    with pytest.raises(ValueError):
        decode_access(token[:-5] + 'aaaaa', s)
    with pytest.raises(ValueError):
        decode_access(token, s.model_copy(update={'auth_jwt_audience': 'different'}))
    with pytest.raises(ValueError):
        encode_access('u', 's', 1, s.model_copy(update={'auth_jwt_secret': ''}))
    with pytest.raises(ValueError):
        decode_access(encode_access('u', 's', 1, s, now=datetime.now(timezone.utc)-timedelta(days=1)), s)
