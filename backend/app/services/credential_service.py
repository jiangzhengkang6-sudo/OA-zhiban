"""Password and token primitives; no persistence or implicit default key."""
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ValueError('密码须为 12 至 1024 个字符')
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    if len(password) > 1024:
        return False
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_key(settings):
    if len(settings.auth_jwt_secret.encode()) < 32:
        raise ValueError('正式认证需要至少 32 字节的独立 JWT 密钥')


def encode_access(user_id, session_id, auth_version, settings, *, now=None):
    validate_key(settings)
    now = now or datetime.now(timezone.utc)
    return jwt.encode({'sub': user_id, 'sid': session_id, 'av': auth_version,
                       'iat': now, 'exp': now + timedelta(seconds=settings.auth_access_seconds),
                       'iss': settings.auth_jwt_issuer, 'aud': settings.auth_jwt_audience},
                      settings.auth_jwt_secret, algorithm='HS256')


def decode_access(token, settings):
    validate_key(settings)
    try:
        claims = jwt.decode(token, settings.auth_jwt_secret, algorithms=['HS256'],
                            issuer=settings.auth_jwt_issuer, audience=settings.auth_jwt_audience,
                            options={'require': ['sub', 'sid', 'av', 'iat', 'exp', 'iss', 'aud']})
        if not isinstance(claims['sid'], str) or type(claims['av']) is not int:
            raise ValueError('invalid claims')
        if claims['exp'] - claims['iat'] > settings.auth_access_seconds:
            raise ValueError('invalid lifetime')
        return claims
    except jwt.InvalidTokenError:
        raise ValueError('凭证无效') from None
