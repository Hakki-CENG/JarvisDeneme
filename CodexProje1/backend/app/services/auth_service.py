from __future__ import annotations

import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from fastapi import Header, HTTPException, Request, status

from app.core.settings import settings
from app.models.schemas import AuthBootstrapRequest, AuthBootstrapResponse, AuthSession
from app.services.audit_service import audit_service
from app.services.secret_vault import secret_vault


@dataclass
class AuthContext:
    role: str
    token: str
    request_id: str = ''


class AuthService:
    def __init__(self) -> None:
        self._rate_lock = Lock()
        self._bucket: dict[tuple[str, str], int] = defaultdict(int)
        self._active_window = self._minute_window()
        self._bootstrap_if_needed()

    @staticmethod
    def _minute_window() -> str:
        return datetime.utcnow().strftime('%Y%m%d%H%M')

    def _bootstrap_if_needed(self) -> None:
        if self._admin_token() and self._user_token():
            return

        admin = settings.admin_api_token or secret_vault.get_secret('ADMIN_API_TOKEN')
        user = settings.user_api_token or secret_vault.get_secret('USER_API_TOKEN')
        if admin and user:
            return

        # One-time local bootstrap token generation.
        generated_admin = secrets.token_urlsafe(32)
        generated_user = secrets.token_urlsafe(32)
        secret_vault.set_secret('ADMIN_API_TOKEN', generated_admin)
        secret_vault.set_secret('USER_API_TOKEN', generated_user)
        marker = settings.data_dir / 'INITIAL_ADMIN_TOKEN.txt'
        if not marker.exists():
            marker.write_text(
                (
                    'Jarvis-X initial admin token (rotate ASAP):\n'
                    f'{generated_admin}\n'
                ),
                encoding='utf-8',
            )

    def _admin_token(self) -> str:
        return settings.admin_api_token or secret_vault.get_secret('ADMIN_API_TOKEN') or ''

    def _user_token(self) -> str:
        return settings.user_api_token or secret_vault.get_secret('USER_API_TOKEN') or ''

    def _token_role(self, token: str) -> str | None:
        if token == self._admin_token() and token:
            return 'ADMIN'
        if token == self._user_token() and token:
            return 'USER'
        return None

    def _check_rate_limit(self, ip: str, token: str) -> None:
        window = self._minute_window()
        with self._rate_lock:
            if window != self._active_window:
                self._bucket.clear()
                self._active_window = window

            key = (ip, token)
            self._bucket[key] += 1
            if self._bucket[key] > settings.rate_limit_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail='Rate limit exceeded for this API token',
                )

    def verify_token(self, token: str, ip: str, required_role: str = 'USER', request_id: str = '') -> AuthContext:
        role = self._token_role(token)
        if not role:
            audit_service.log(actor='anonymous', action='auth_failed', details='Invalid API token', request_id=request_id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid API token')

        self._check_rate_limit(ip=ip, token=token)

        if required_role == 'ADMIN' and role != 'ADMIN':
            audit_service.log(actor=role, action='auth_forbidden', details='Admin role required', request_id=request_id)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin role required')

        return AuthContext(role=role, token=token, request_id=request_id)

    async def require_user(self, request: Request, x_api_key: str | None = Header(default=None)) -> AuthContext:
        if not x_api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing X-API-Key header')
        ip = request.client.host if request.client else 'unknown'
        request_id = getattr(request.state, 'request_id', '')
        return self.verify_token(token=x_api_key, ip=ip, required_role='USER', request_id=request_id)

    async def require_admin(self, request: Request, x_api_key: str | None = Header(default=None)) -> AuthContext:
        if not x_api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing X-API-Key header')
        ip = request.client.host if request.client else 'unknown'
        request_id = getattr(request.state, 'request_id', '')
        return self.verify_token(token=x_api_key, ip=ip, required_role='ADMIN', request_id=request_id)

    def authorize_ws(self, token: str | None, ip: str) -> bool:
        if not token:
            return False
        try:
            self.verify_token(token=token, ip=ip, required_role='USER')
            return True
        except HTTPException:
            return False

    def bootstrap(self, payload: AuthBootstrapRequest, current_token: str | None = None) -> AuthBootstrapResponse:
        active_admin = self._admin_token()
        if active_admin and current_token != active_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin token required to rotate credentials')

        admin_token = payload.admin_token.strip()
        if len(admin_token) < 24:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Admin token must be at least 24 chars')

        user_token = (payload.user_token or secrets.token_urlsafe(32)).strip()
        if len(user_token) < 24:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='User token must be at least 24 chars')
        if admin_token == user_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Admin and user tokens must differ')

        secret_vault.set_secret('ADMIN_API_TOKEN', admin_token)
        secret_vault.set_secret('USER_API_TOKEN', user_token)
        audit_service.log(actor='system', action='auth_bootstrap', details='API tokens rotated')
        return AuthBootstrapResponse(status='ok', admin_token_set=True, user_token_set=True)

    def current_session(self, context: AuthContext) -> AuthSession:
        token_hint = context.token[:4] + '...' + context.token[-4:]
        return AuthSession(role=context.role, token_hint=token_hint, request_id=context.request_id)


auth_service = AuthService()
