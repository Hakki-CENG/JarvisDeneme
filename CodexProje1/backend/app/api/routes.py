from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, WebSocket, WebSocketDisconnect

from app.models.schemas import (
    ActionEnvelope,
    ApprovalSubmitRequest,
    AuthBootstrapRequest,
    AuthBootstrapResponse,
    AuthSession,
    CancelRequest,
    EmergencyStopRequest,
    MemoryAddRequest,
    MemoryEntry,
    MemorySearchRequest,
    ModelQuotaResponse,
    RollbackApplyRequest,
    ResumeRequest,
    SecretSetRequest,
    SelfImproveReport,
    SelfImproveRunRequest,
    SkillManifest,
    SkillRunRequest,
    SkillRunResult,
    TaskCreateRequest,
    TaskPlan,
    TaskSummary,
    VisionOcrRequest,
    VoiceCommandRequest,
    VoiceMicRequest,
    VoiceSpeakRequest,
    VoiceTranscribeRequest,
)
from app.services.approval_service import approval_service
from app.services.audit_service import audit_service
from app.services.auth_service import AuthContext, auth_service
from app.services.event_bus import event_bus
from app.services.event_store_service import event_store_service
from app.services.idempotency_service import idempotency_service
from app.services.metrics_service import metrics_service
from app.services.memory_service import memory_service
from app.services.model_router import model_router
from app.services.plan_verifier_service import plan_verifier_service
from app.services.planner_service import planner_service
from app.services.repositories import repositories
from app.services.safety_service import safety_service
from app.services.secret_vault import secret_vault
from app.services.self_improvement import self_improvement_service
from app.services.skill_service import skill_service
from app.services.task_orchestrator import orchestrator
from app.services.vision import vision_service
from app.services.voice import voice_service
from app.services.world_state_service import world_state_service

router = APIRouter()


@router.post('/auth/bootstrap', response_model=AuthBootstrapResponse)
async def bootstrap_auth(payload: AuthBootstrapRequest, x_api_key: str | None = Header(default=None)) -> AuthBootstrapResponse:
    return auth_service.bootstrap(payload, current_token=x_api_key)


@router.get('/auth/me', response_model=AuthSession)
async def auth_me(auth: AuthContext = Depends(auth_service.require_user)) -> AuthSession:
    return auth_service.current_session(auth)


@router.post('/tasks', response_model=TaskSummary)
async def create_task(
    request: TaskCreateRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    auth: AuthContext = Depends(auth_service.require_user),
) -> TaskSummary:
    if idempotency_key:
        existing_task_id = idempotency_service.get_task_id(idempotency_key)
        if existing_task_id:
            existing = orchestrator.get_task(existing_task_id)
            if existing:
                response.headers['X-Idempotent-Replay'] = 'true'
                return existing

    audit_service.log(actor=auth.role, action='task_create_request', details=request.objective[:220], request_id=auth.request_id)
    created = await orchestrator.create_task(request)
    if idempotency_key:
        idempotency_service.bind(idempotency_key=idempotency_key, task_id=created.id)
    return created


@router.post('/tasks/plan', response_model=TaskPlan)
async def preview_task_plan(request: TaskCreateRequest, _: AuthContext = Depends(auth_service.require_user)) -> TaskPlan:
    from app.models.schemas import TaskSpec

    temp_spec = TaskSpec(objective=request.objective, constraints=request.constraints, tools_allowed=request.tools_allowed)
    return planner_service.build_plan(temp_spec)


@router.post('/tasks/verify')
async def verify_task_plan(request: TaskCreateRequest, _: AuthContext = Depends(auth_service.require_user)):
    from app.models.schemas import TaskSpec

    temp_spec = TaskSpec(objective=request.objective, constraints=request.constraints, tools_allowed=request.tools_allowed)
    plan = planner_service.build_plan(temp_spec)
    actions = [action for step in plan.steps for action in step.actions]
    return {'plan': plan.model_dump(mode='json'), 'verification': plan_verifier_service.verify_actions(actions)}


@router.get('/tasks', response_model=list[TaskSummary])
async def list_tasks(_: AuthContext = Depends(auth_service.require_user)) -> list[TaskSummary]:
    return orchestrator.list_tasks()


@router.get('/tasks/{task_id}', response_model=TaskSummary)
async def get_task(task_id: str, _: AuthContext = Depends(auth_service.require_user)) -> TaskSummary:
    task = orchestrator.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@router.post('/tasks/{task_id}/resume', response_model=TaskSummary)
async def resume_task(task_id: str, request: ResumeRequest, _: AuthContext = Depends(auth_service.require_user)) -> TaskSummary:
    task = await orchestrator.resume_task(task_id, request)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@router.post('/tasks/{task_id}/cancel', response_model=TaskSummary)
async def cancel_task(task_id: str, request: CancelRequest, _: AuthContext = Depends(auth_service.require_user)) -> TaskSummary:
    task = await orchestrator.cancel_task(task_id, request.reason)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@router.get('/checkpoints/{task_id}')
async def list_checkpoints(task_id: str, _: AuthContext = Depends(auth_service.require_user)):
    return orchestrator.list_checkpoints(task_id)


@router.get('/traces/{task_id}')
async def list_traces(task_id: str, _: AuthContext = Depends(auth_service.require_user)):
    return repositories['traces'].list_by_task(task_id)


@router.get('/world-state/{task_id}')
async def world_state(task_id: str, _: AuthContext = Depends(auth_service.require_user)):
    return world_state_service.get(task_id)


@router.post('/approvals/{approval_id}')
async def submit_approval(
    approval_id: str,
    request: ApprovalSubmitRequest,
    auth: AuthContext = Depends(auth_service.require_user),
):
    result = await approval_service.decide(approval_id, request.decision)
    if not result:
        raise HTTPException(status_code=404, detail='Approval request not found')
    audit_service.log(actor=auth.role, action='approval_decision', details=f'approval={approval_id} decision={request.decision}')
    return result


@router.get('/approvals/pending')
async def pending_approvals(_: AuthContext = Depends(auth_service.require_user)):
    return approval_service.list_pending()


@router.post('/desktop/actions')
async def execute_desktop_action(action: ActionEnvelope, _: AuthContext = Depends(auth_service.require_admin)):
    return await orchestrator.execute_manual_action(action)


@router.post('/desktop/rollback')
async def apply_desktop_rollback(request: RollbackApplyRequest, _: AuthContext = Depends(auth_service.require_admin)):
    return await orchestrator.apply_rollback(
        backup_path=request.backup_path,
        target_path=request.target_path,
        delete_target=request.delete_target,
    )


@router.post('/self-improve/run', response_model=SelfImproveReport)
async def run_self_improvement(
    request: SelfImproveRunRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> SelfImproveReport:
    audit_service.log(actor=auth.role, action='self_improve_run', details=f'focus={request.focus}')
    return self_improvement_service.run(request.focus)


@router.get('/self-improve/report/{report_id}', response_model=SelfImproveReport)
async def get_self_improvement_report(report_id: str, _: AuthContext = Depends(auth_service.require_user)) -> SelfImproveReport:
    report = self_improvement_service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail='Report not found')
    return report


@router.get('/models/quotas', response_model=ModelQuotaResponse)
async def get_model_quotas(_: AuthContext = Depends(auth_service.require_user)) -> ModelQuotaResponse:
    return model_router.quotas()


@router.get('/skills', response_model=list[SkillManifest])
async def list_skills(_: AuthContext = Depends(auth_service.require_user)) -> list[SkillManifest]:
    return skill_service.list_skills()


@router.post('/skills/register', response_model=SkillManifest)
async def register_skill(
    manifest: SkillManifest,
    _: AuthContext = Depends(auth_service.require_admin),
) -> SkillManifest:
    return skill_service.register_skill(manifest)


@router.post('/skills/run', response_model=SkillRunResult)
async def run_skill(request: SkillRunRequest, _: AuthContext = Depends(auth_service.require_user)) -> SkillRunResult:
    return skill_service.run_skill(request)


@router.get('/safety/status')
async def safety_status(_: AuthContext = Depends(auth_service.require_user)):
    return safety_service.status()


@router.post('/safety/emergency-stop')
async def emergency_stop(request: EmergencyStopRequest, auth: AuthContext = Depends(auth_service.require_user)):
    state = safety_service.trigger_emergency_stop(request.reason)
    audit_service.log(actor=auth.role, action='emergency_stop', details=request.reason)
    return state


@router.post('/safety/emergency-clear')
async def emergency_clear(auth: AuthContext = Depends(auth_service.require_user)):
    state = safety_service.clear_emergency_stop()
    audit_service.log(actor=auth.role, action='emergency_clear', details='manual clear')
    return state


@router.get('/secrets')
async def list_secrets(_: AuthContext = Depends(auth_service.require_admin)):
    return {'keys': secret_vault.list_secret_names()}


@router.post('/secrets')
async def set_secret(request: SecretSetRequest, _: AuthContext = Depends(auth_service.require_admin)):
    secret_vault.set_secret(request.name, request.value)
    return {'status': 'ok', 'name': request.name}


@router.post('/voice/transcribe')
async def transcribe_voice(request: VoiceTranscribeRequest, _: AuthContext = Depends(auth_service.require_user)):
    return {'text': voice_service.transcribe_file(request.path)}


@router.post('/voice/transcribe-mic')
async def transcribe_voice_mic(request: VoiceMicRequest, _: AuthContext = Depends(auth_service.require_user)):
    return {'text': voice_service.transcribe_microphone(request.timeout_seconds, request.phrase_time_limit)}


@router.post('/voice/speak')
async def speak_voice(request: VoiceSpeakRequest, _: AuthContext = Depends(auth_service.require_user)):
    return {'status': voice_service.speak(request.text)}


@router.post('/voice/parse-command')
async def parse_voice_command(request: VoiceCommandRequest, _: AuthContext = Depends(auth_service.require_user)):
    return voice_service.parse_command(text=request.text, wake_word=request.wake_word)


@router.post('/vision/ocr')
async def ocr_vision(request: VisionOcrRequest, _: AuthContext = Depends(auth_service.require_user)):
    return vision_service.ocr_image(request.image_path)


@router.post('/vision/ocr-layout')
async def ocr_vision_layout(request: VisionOcrRequest, _: AuthContext = Depends(auth_service.require_user)):
    return vision_service.ocr_layout(request.image_path)


@router.post('/vision/analyze')
async def vision_analyze(request: VisionOcrRequest, _: AuthContext = Depends(auth_service.require_user)):
    return vision_service.analyze_scene(request.image_path)


@router.get('/metrics')
async def metrics(_: AuthContext = Depends(auth_service.require_admin)):
    return metrics_service.get()


@router.get('/audit/logs')
async def audit_logs(limit: int = Query(default=50, ge=1, le=500), _: AuthContext = Depends(auth_service.require_admin)):
    return audit_service.latest(limit=limit)


@router.get('/events')
async def events(
    limit: int = Query(default=200, ge=1, le=1000),
    task_id: str | None = Query(default=None),
    _: AuthContext = Depends(auth_service.require_user),
):
    return event_store_service.list_recent(limit=limit, task_id=task_id)


@router.post('/memory/add', response_model=MemoryEntry)
async def memory_add(request: MemoryAddRequest, _: AuthContext = Depends(auth_service.require_admin)) -> MemoryEntry:
    return memory_service.upsert(key=request.key, content=request.content, tags=request.tags)


@router.post('/memory/search', response_model=list[MemoryEntry])
async def memory_search(request: MemorySearchRequest, _: AuthContext = Depends(auth_service.require_user)) -> list[MemoryEntry]:
    return memory_service.search(query=request.query, limit=request.limit)


@router.get('/memory/recent', response_model=list[MemoryEntry])
async def memory_recent(limit: int = Query(default=20, ge=1, le=200), _: AuthContext = Depends(auth_service.require_user)) -> list[MemoryEntry]:
    return memory_service.recent(limit=limit)


@router.websocket('/ws/live')
async def ws_live(websocket: WebSocket, task_id: str | None = Query(default=None), token: str | None = Query(default=None)):
    if not token:
        protocols = websocket.headers.get('sec-websocket-protocol', '')
        for item in [part.strip() for part in protocols.split(',') if part.strip()]:
            if item.startswith('token.'):
                token = item.removeprefix('token.')
                break
    ip = websocket.client.host if websocket.client else 'unknown'
    if not auth_service.authorize_ws(token=token, ip=ip):
        await websocket.close(code=4401)
        return

    await event_bus.connect(websocket, task_id=task_id)
    try:
        while True:
            # Keep websocket alive and allow client pings.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await event_bus.disconnect(websocket)
