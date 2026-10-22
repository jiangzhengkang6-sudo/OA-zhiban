"""Cookie credentials are confined to auth routes; business requests use Bearer."""
import hmac
import secrets
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from ...core.config import get_settings
from ...core.errors import AppException, ErrorCode
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.identity import LoginInput, PasswordChange
from ...services import identity_service as identities

router = APIRouter(prefix='/auth', tags=['认证'])
REFRESH_COOKIE = 'oa_refresh'
CSRF_COOKIE = 'oa_csrf'


def builtin():
    if get_settings().auth_provider != 'builtin':
        raise AppException(ErrorCode.FORBIDDEN, '当前环境未启用正式账号', http_status=403)


def cookie_options():
    config = get_settings()
    return dict(httponly=True, secure=config.auth_cookie_secure, samesite='lax', path=config.api_prefix + '/auth')


def check_csrf(request):
    builtin()
    config = get_settings()
    cookie = request.cookies.get(CSRF_COOKIE, '')
    header = request.headers.get('x-csrf-token', '')
    origin = request.headers.get('origin', '')
    if origin not in config.auth_allowed_origins or not cookie or not hmac.compare_digest(cookie, header):
        raise AppException(ErrorCode.FORBIDDEN, '认证请求来源或校验凭证无效', http_status=403)


def set_refresh(response, issued):
    response.set_cookie(REFRESH_COOKIE, issued.refresh, max_age=get_settings().auth_refresh_days * 86400, **cookie_options())


async def actor_from_request(request, db):
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer '):
        raise identities.unauthorized()
    return await identities.resolve_access(header[7:], session=db, settings=get_settings())


@router.get('/config')
async def configuration():
    settings = get_settings()
    return ok({'provider': settings.auth_provider, 'capabilities': {
        'manual_oa': settings.auth_provider == 'builtin', 'ai': settings.ai_enabled}})


@router.get('/csrf')
async def csrf(response: Response):
    builtin()
    token = secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, token, **cookie_options())
    response.headers['Cache-Control'] = 'no-store'
    return ok({'token': token})


@router.post('/login')
async def login(payload: LoginInput, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_csrf(request)
    source = request.client.host if request.client else 'unknown'
    issued = await identities.login(db, payload.username, payload.password.get_secret_value(), source=source, settings=get_settings())
    set_refresh(response, issued)
    response.headers['Cache-Control'] = 'no-store'
    return ok(issued.grant)


@router.post('/refresh')
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_csrf(request)
    source = request.client.host if request.client else 'unknown'
    await identities.throttle(db, 'refresh:' + source)
    await db.commit()
    issued = await identities.rotate_refresh(request.cookies.get(REFRESH_COOKIE), session=db, settings=get_settings())
    set_refresh(response, issued)
    response.headers['Cache-Control'] = 'no-store'
    return ok(issued.grant)


@router.post('/logout')
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_csrf(request)
    await identities.logout(request.cookies.get(REFRESH_COOKIE), session=db)
    response.delete_cookie(REFRESH_COOKIE, **cookie_options())
    return ok()


@router.get('/me')
async def me(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    builtin()
    response.headers['Cache-Control'] = 'no-store'
    return ok(identities.view(await actor_from_request(request, db)))


@router.post('/change-password')
async def change_password(payload: PasswordChange, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_csrf(request)
    actor = await actor_from_request(request, db)
    await identities.change_password(db, actor, payload.current_password.get_secret_value(), payload.new_password.get_secret_value())
    response.delete_cookie(REFRESH_COOKIE, **cookie_options())
    return ok()
