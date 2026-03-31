from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.settings import settings
from app.services.audit_service import audit_service
from app.services.hotkey_guard import hotkey_guard
from app.services.metrics_service import metrics_service
from app.services.runtime_scheduler import runtime_scheduler

app = FastAPI(title=settings.app_name, version='0.1.0')
allowed_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(',') if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ['http://localhost:5173'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(router)


@app.on_event('startup')
async def startup() -> None:
    hotkey_guard.start()
    runtime_scheduler.start()


@app.middleware('http')
async def request_middleware(request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    metrics_service.inc('requests_total')
    start = perf_counter()
    response = await call_next(request)
    elapsed_ms = int((perf_counter() - start) * 1000)
    response.headers['X-Request-Id'] = request_id
    audit_service.log(
        actor='http',
        action='request',
        details=f'{request.method} {request.url.path} status={response.status_code} elapsed_ms={elapsed_ms}',
        request_id=request_id,
    )
    if response.status_code in {401, 403, 429}:
        metrics_service.inc('requests_blocked')
    return response


@app.get('/health')
async def health():
    return {'status': 'ok', 'app': settings.app_name}
