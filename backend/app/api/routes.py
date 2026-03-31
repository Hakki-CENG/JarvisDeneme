from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, WebSocket, WebSocketDisconnect

from app.models.schemas import (
    ActionEnvelope,
    AssistantCommandRequest,
    ApprovalSubmitRequest,
    ImprovementJob,
    ImprovementJobCancelRequest,
    ImprovementJobCreateRequest,
    AuthBootstrapRequest,
    AuthBootstrapResponse,
    AuthSession,
    CancelRequest,
    CodeInsightRequest,
    EmergencyStopRequest,
    ExecutionReport,
    ImprovementProposalV2,
    MemoryAddRequest,
    MemoryEmbedRequest,
    MemoryEmbedResponse,
    MemoryEntry,
    MemoryReindexRequest,
    MemoryShardStats,
    MissionSimulationReport,
    MissionTemplate,
    MemorySearchRequest,
    MissionCreateRequest,
    MissionGraph,
    MissionRecord,
    MissionReplanRequest,
    MissionSummary,
    OpsIncident,
    OpsSLO,
    ModelQuotaResponse,
    KnowledgeGraphQueryRequest,
    RollbackApplyRequest,
    RollbackArtifact,
    RollbackPreviewRequest,
    ProposalDecisionRequest,
    ProposalGenerateRequest,
    ResumeRequest,
    SecretSetRequest,
    SelfImproveReport,
    SelfImproveRunRequest,
    SkillCatalogBootstrapRequest,
    SkillComposeRequest,
    SkillManifest,
    SkillSearchRequest,
    SkillRunRequest,
    SkillRunResult,
    TaskCreateRequest,
    TaskPlan,
    TaskSummary,
    ToolBatchExecutionRequest,
    ToolBatchExecutionResult,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealth,
    ToolManifest,
    ToolPromoteRequest,
    ToolToggleRequest,
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
from app.services.execution_report_service import execution_report_service
from app.services.idempotency_service import idempotency_service
from app.services.metrics_service import metrics_service
from app.services.memory_service import memory_service
from app.services.mission_service import mission_service
from app.services.model_router import model_router
from app.services.ops_service import ops_service
from app.services.plan_verifier_service import plan_verifier_service
from app.services.planner_service import planner_service
from app.services.repositories import repositories
from app.services.rollback_service import rollback_service
from app.services.safety_service import safety_service
from app.services.secret_vault import secret_vault
from app.services.self_improvement import self_improvement_service
from app.services.self_improvement_v2 import self_improvement_proposal_service
from app.services.skill_service import skill_service
from app.services.task_orchestrator import orchestrator
from app.services.tool_fabric import tool_fabric_service
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

    temp_spec = TaskSpec(
        objective=request.objective,
        constraints=request.constraints,
        tools_allowed=request.tools_allowed,
        priority=request.priority,
    )
    return planner_service.build_plan(temp_spec)


@router.post('/tasks/verify')
async def verify_task_plan(request: TaskCreateRequest, _: AuthContext = Depends(auth_service.require_user)):
    from app.models.schemas import TaskSpec

    temp_spec = TaskSpec(
        objective=request.objective,
        constraints=request.constraints,
        tools_allowed=request.tools_allowed,
        priority=request.priority,
    )
    plan = planner_service.build_plan(temp_spec)
    actions = [action for step in plan.steps for action in step.actions]
    return {'plan': plan.model_dump(mode='json'), 'verification': plan_verifier_service.verify_actions(actions)}


@router.get('/tasks', response_model=list[TaskSummary])
async def list_tasks(_: AuthContext = Depends(auth_service.require_user)) -> list[TaskSummary]:
    return orchestrator.list_tasks()


@router.post('/missions', response_model=MissionRecord)
async def create_mission(request: MissionCreateRequest, auth: AuthContext = Depends(auth_service.require_user)) -> MissionRecord:
    record = mission_service.create(request)
    if request.auto_execute:
        task = await orchestrator.create_task(
            TaskCreateRequest(
                objective=request.objective,
                constraints=request.constraints + [f'mission:{record.mission.mission_id}'],
                tools_allowed=request.tools_allowed,
                priority=request.priority,
            )
        )
        mission_service.link_task(record.mission.mission_id, task.id)
        refreshed = mission_service.get(record.mission.mission_id)
        if refreshed:
            record = refreshed

    audit_service.log(
        actor=auth.role,
        action='mission_create',
        details=f'mission_id={record.mission.mission_id} auto_execute={request.auto_execute}',
        request_id=auth.request_id,
    )
    return record


@router.get('/missions', response_model=list[MissionSummary])
async def list_missions(_: AuthContext = Depends(auth_service.require_user)) -> list[MissionSummary]:
    return mission_service.list()


@router.get('/missions/{mission_id}', response_model=MissionRecord)
async def get_mission(mission_id: str, _: AuthContext = Depends(auth_service.require_user)) -> MissionRecord:
    mission = mission_service.get(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail='Mission not found')
    return mission


@router.post('/missions/template', response_model=MissionTemplate)
async def create_mission_template(
    template: MissionTemplate,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> MissionTemplate:
    created = mission_service.create_template(template)
    audit_service.log(actor=auth.role, action='mission_template_create', details=f'template={created.id}')
    return created


@router.get('/missions/{mission_id}/graph', response_model=MissionGraph)
async def get_mission_graph(mission_id: str, _: AuthContext = Depends(auth_service.require_user)) -> MissionGraph:
    graph = mission_service.graph(mission_id)
    if not graph:
        raise HTTPException(status_code=404, detail='Mission not found')
    return graph


@router.post('/missions/{mission_id}/simulate', response_model=MissionSimulationReport)
async def simulate_mission(mission_id: str, _: AuthContext = Depends(auth_service.require_user)) -> MissionSimulationReport:
    report = mission_service.simulate(mission_id)
    if not report:
        raise HTTPException(status_code=404, detail='Mission not found')
    return report


@router.get('/missions/{mission_id}/report', response_model=ExecutionReport)
async def mission_report(mission_id: str, _: AuthContext = Depends(auth_service.require_user)) -> ExecutionReport:
    reports = repositories['execution_reports'].list_by_mission(mission_id, limit=1)
    if not reports:
        raise HTTPException(status_code=404, detail='Execution report not found')
    return reports[0]


@router.post('/missions/{mission_id}/replan', response_model=MissionRecord)
async def replan_mission(
    mission_id: str,
    request: MissionReplanRequest,
    auth: AuthContext = Depends(auth_service.require_user),
) -> MissionRecord:
    mission = mission_service.replan(mission_id, request)
    if not mission:
        raise HTTPException(status_code=404, detail='Mission not found')
    audit_service.log(actor=auth.role, action='mission_replan', details=f'mission_id={mission_id} reason={request.reason}')
    return mission


@router.get('/tasks/{task_id}', response_model=TaskSummary)
async def get_task(task_id: str, _: AuthContext = Depends(auth_service.require_user)) -> TaskSummary:
    task = orchestrator.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@router.get('/tasks/{task_id}/report', response_model=ExecutionReport)
async def get_task_execution_report(task_id: str, _: AuthContext = Depends(auth_service.require_user)) -> ExecutionReport:
    report = execution_report_service.get_by_task(task_id)
    if not report:
        raise HTTPException(status_code=404, detail='Execution report not found')
    return report


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


@router.post('/rollback/preview', response_model=list[RollbackArtifact])
async def rollback_preview(request: RollbackPreviewRequest, _: AuthContext = Depends(auth_service.require_user)) -> list[RollbackArtifact]:
    return rollback_service.preview(request)


@router.post('/rollback/apply')
async def rollback_apply(request: RollbackApplyRequest, auth: AuthContext = Depends(auth_service.require_admin)):
    backup_path = request.backup_path
    target_path = request.target_path
    delete_target = request.delete_target
    artifact_id = request.artifact_id

    if artifact_id:
        artifact = rollback_service.get(artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail='Rollback artifact not found')
        backup_path = artifact.backup_path
        target_path = artifact.target_path
        delete_target = artifact.delete_target

    result = await orchestrator.apply_rollback(
        backup_path=backup_path,
        target_path=target_path,
        delete_target=delete_target,
    )
    if result.success and artifact_id:
        rollback_service.mark_applied(artifact_id)
    label = artifact_id or 'manual'
    audit_service.log(actor=auth.role, action='rollback_apply', details=f'artifact_id={label}')
    return result


@router.post('/self-improve/run', response_model=SelfImproveReport)
async def run_self_improvement(
    request: SelfImproveRunRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> SelfImproveReport:
    audit_service.log(actor=auth.role, action='self_improve_run', details=f'focus={request.focus}')
    return self_improvement_service.run(request.focus)


@router.post('/self-improve/code-insights')
async def self_improve_code_insights(
    request: CodeInsightRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
):
    insights = self_improvement_service.code_insights(max_items=request.max_items)
    audit_service.log(actor=auth.role, action='self_improve_code_insights', details=f'max_items={request.max_items}')
    return {'count': len(insights), 'items': [item.model_dump(mode='json') for item in insights]}


@router.post('/self-improve/proposals', response_model=list[ImprovementProposalV2])
async def self_improve_proposals(
    request: ProposalGenerateRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> list[ImprovementProposalV2]:
    proposals = self_improvement_proposal_service.generate(request)
    audit_service.log(actor=auth.role, action='self_improve_proposals_generate', details=f'count={len(proposals)}')
    return proposals


@router.get('/self-improve/proposals', response_model=list[ImprovementProposalV2])
async def self_improve_proposals_list(
    limit: int = Query(default=50, ge=1, le=200),
    _: AuthContext = Depends(auth_service.require_user),
) -> list[ImprovementProposalV2]:
    return self_improvement_proposal_service.list_recent(limit=limit)


@router.post('/self-improve/proposals/{proposal_id}/approve', response_model=ImprovementProposalV2)
async def self_improve_proposal_approve(
    proposal_id: str,
    request: ProposalDecisionRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> ImprovementProposalV2:
    proposal = self_improvement_proposal_service.approve(proposal_id, request)
    if not proposal:
        raise HTTPException(status_code=404, detail='Proposal not found')
    audit_service.log(actor=auth.role, action='self_improve_proposal_approve', details=f'proposal={proposal_id}')
    return proposal


@router.post('/self-improve/proposals/{proposal_id}/reject', response_model=ImprovementProposalV2)
async def self_improve_proposal_reject(
    proposal_id: str,
    request: ProposalDecisionRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> ImprovementProposalV2:
    proposal = self_improvement_proposal_service.reject(proposal_id, request)
    if not proposal:
        raise HTTPException(status_code=404, detail='Proposal not found')
    audit_service.log(actor=auth.role, action='self_improve_proposal_reject', details=f'proposal={proposal_id}')
    return proposal


@router.post('/self-improve/jobs', response_model=ImprovementJob)
async def create_self_improve_job(
    request: ImprovementJobCreateRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> ImprovementJob:
    job = self_improvement_proposal_service.create_job(request)
    audit_service.log(actor=auth.role, action='self_improve_job_create', details=f'job={job.id} focus={request.focus}')
    return job


@router.get('/self-improve/jobs/{job_id}', response_model=ImprovementJob)
async def get_self_improve_job(job_id: str, _: AuthContext = Depends(auth_service.require_user)) -> ImprovementJob:
    job = self_improvement_proposal_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return job


@router.post('/self-improve/jobs/{job_id}/cancel', response_model=ImprovementJob)
async def cancel_self_improve_job(
    job_id: str,
    request: ImprovementJobCancelRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
) -> ImprovementJob:
    job = self_improvement_proposal_service.cancel_job(job_id, request)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    audit_service.log(actor=auth.role, action='self_improve_job_cancel', details=f'job={job.id}')
    return job


@router.get('/self-improve/report/{report_id}', response_model=SelfImproveReport)
async def get_self_improvement_report(report_id: str, _: AuthContext = Depends(auth_service.require_user)) -> SelfImproveReport:
    report = self_improvement_service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail='Report not found')
    return report


@router.get('/models/quotas', response_model=ModelQuotaResponse)
async def get_model_quotas(_: AuthContext = Depends(auth_service.require_user)) -> ModelQuotaResponse:
    return model_router.quotas()


@router.get('/tools/catalog', response_model=list[ToolManifest])
async def tools_catalog(_: AuthContext = Depends(auth_service.require_user)) -> list[ToolManifest]:
    return tool_fabric_service.list_catalog()


@router.get('/tools/health', response_model=list[ToolHealth])
async def tools_health(_: AuthContext = Depends(auth_service.require_user)) -> list[ToolHealth]:
    return tool_fabric_service.health()


@router.post('/tools/execute', response_model=ToolExecutionResult)
async def tools_execute(request: ToolExecutionRequest, _: AuthContext = Depends(auth_service.require_user)) -> ToolExecutionResult:
    return await tool_fabric_service.execute(request)


@router.post('/tools/batch-execute', response_model=ToolBatchExecutionResult)
async def tools_batch_execute(
    request: ToolBatchExecutionRequest,
    _: AuthContext = Depends(auth_service.require_user),
) -> ToolBatchExecutionResult:
    return await tool_fabric_service.batch_execute(request)


@router.get('/tools/{tool_name}/versions')
async def tools_versions(tool_name: str, _: AuthContext = Depends(auth_service.require_user)):
    return tool_fabric_service.list_versions(tool_name)


@router.post('/tools/{tool_name}/promote')
async def tools_promote(
    tool_name: str,
    request: ToolPromoteRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
):
    promoted = tool_fabric_service.promote(tool_name, request.version)
    if not promoted:
        raise HTTPException(status_code=404, detail='Tool version not found')
    audit_service.log(actor=auth.role, action='tool_promote', details=f'{tool_name}@{request.version}')
    return {'name': tool_name, 'version': request.version, 'promoted': True}


@router.post('/tools/{tool_name}/toggle')
async def tools_toggle(
    tool_name: str,
    request: ToolToggleRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
):
    updated = tool_fabric_service.set_enabled(tool_name, request.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail='Tool not found')
    audit_service.log(actor=auth.role, action='tool_toggle', details=f'{tool_name} enabled={request.enabled}')
    return {'name': tool_name, 'enabled': request.enabled}


@router.get('/skills', response_model=list[SkillManifest])
async def list_skills(_: AuthContext = Depends(auth_service.require_user)) -> list[SkillManifest]:
    return skill_service.list_skills()


@router.post('/skills/register', response_model=SkillManifest)
async def register_skill(
    manifest: SkillManifest,
    _: AuthContext = Depends(auth_service.require_admin),
) -> SkillManifest:
    return skill_service.register_skill(manifest)


@router.post('/skills/search', response_model=list[SkillManifest])
async def search_skills(request: SkillSearchRequest, _: AuthContext = Depends(auth_service.require_user)) -> list[SkillManifest]:
    return skill_service.search_skills(request)


@router.post('/skills/compose', response_model=SkillManifest)
async def compose_skill(request: SkillComposeRequest, _: AuthContext = Depends(auth_service.require_admin)) -> SkillManifest:
    try:
        return skill_service.compose_skill(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/skills/bootstrap')
async def bootstrap_skill_catalog(
    request: SkillCatalogBootstrapRequest,
    auth: AuthContext = Depends(auth_service.require_admin),
):
    result = skill_service.bootstrap_catalog(request)
    audit_service.log(actor=auth.role, action='skills_bootstrap', details=f"created={result.get('created', 0)}")
    return result


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


@router.post('/voice/execute-command')
async def execute_voice_command(request: VoiceCommandRequest, auth: AuthContext = Depends(auth_service.require_user)):
    parsed = voice_service.parse_command(text=request.text, wake_word=request.wake_word)
    command = str(parsed.get('suggested_objective') or parsed.get('command') or '').strip()
    has_wake_word = bool(parsed.get('has_wake_word'))
    intent = str(parsed.get('intent') or '')

    if not has_wake_word or not command:
        return {'status': 'ignored', 'parsed': parsed, 'reason': 'Wake word missing or command is empty'}

    if intent == 'safety_stop':
        state = safety_service.trigger_emergency_stop('Voice command safety stop')
        audit_service.log(actor=auth.role, action='voice_safety_stop', details=command, request_id=auth.request_id)
        return {
            'status': 'safety_stop_triggered',
            'parsed': parsed,
            'safety': {'emergency_stop': state.emergency_stop, 'reason': state.reason, 'updated_at': state.updated_at},
        }

    if intent == 'safety_clear':
        state = safety_service.clear_emergency_stop()
        audit_service.log(actor=auth.role, action='voice_safety_clear', details=command, request_id=auth.request_id)
        return {
            'status': 'safety_stop_cleared',
            'parsed': parsed,
            'safety': {'emergency_stop': state.emergency_stop, 'reason': state.reason, 'updated_at': state.updated_at},
        }

    if intent == 'status_query':
        tasks = orchestrator.list_tasks()
        summary = {
            'total': len(tasks),
            'running': len([task for task in tasks if task.status.value == 'RUNNING']),
            'waiting_approval': len([task for task in tasks if task.status.value == 'WAITING_APPROVAL']),
            'failed': len([task for task in tasks if task.status.value == 'FAILED']),
        }
        safety = safety_service.status()
        return {
            'status': 'status_report',
            'parsed': parsed,
            'summary': summary,
            'safety': {'emergency_stop': safety.emergency_stop, 'reason': safety.reason, 'updated_at': safety.updated_at},
        }

    created = await orchestrator.create_task(TaskCreateRequest(objective=command))
    audit_service.log(actor=auth.role, action='voice_task_created', details=command[:220], request_id=auth.request_id)
    return {'status': 'task_created', 'parsed': parsed, 'task': created.model_dump(mode='json')}


@router.post('/assistant/command')
async def assistant_command(request: AssistantCommandRequest, auth: AuthContext = Depends(auth_service.require_user)):
    parsed = voice_service.parse_command(text=request.text, wake_word=request.wake_word)
    command = str(parsed.get('suggested_objective') or parsed.get('command') or '').strip()
    intent = str(parsed.get('intent') or 'task_request')
    has_wake_word = bool(parsed.get('has_wake_word'))

    query = command or request.text
    memory_hits = memory_service.search(query=query, limit=5) if query else []
    memory_payload = [
        {'key': item.key, 'score': item.score, 'tags': item.tags, 'summary': item.content[:180]}
        for item in memory_hits
    ]

    if request.wake_word and not has_wake_word:
        return {
            'status': 'ignored',
            'acknowledgement': 'Wake word not detected; command ignored.',
            'parsed': parsed,
            'memory_hits': memory_payload,
        }

    if intent == 'safety_stop':
        state = safety_service.trigger_emergency_stop('Assistant command safety stop')
        return {
            'status': 'safety_stop_triggered',
            'acknowledgement': 'Emergency stop activated.',
            'parsed': parsed,
            'memory_hits': memory_payload,
            'safety': {'emergency_stop': state.emergency_stop, 'reason': state.reason, 'updated_at': state.updated_at},
        }

    if intent == 'safety_clear':
        state = safety_service.clear_emergency_stop()
        return {
            'status': 'safety_stop_cleared',
            'acknowledgement': 'Emergency stop cleared.',
            'parsed': parsed,
            'memory_hits': memory_payload,
            'safety': {'emergency_stop': state.emergency_stop, 'reason': state.reason, 'updated_at': state.updated_at},
        }

    if intent == 'status_query':
        tasks = orchestrator.list_tasks()
        summary = {
            'total': len(tasks),
            'running': len([task for task in tasks if task.status.value == 'RUNNING']),
            'waiting_approval': len([task for task in tasks if task.status.value == 'WAITING_APPROVAL']),
            'failed': len([task for task in tasks if task.status.value == 'FAILED']),
        }
        safety = safety_service.status()
        return {
            'status': 'status_report',
            'acknowledgement': 'System status summarized.',
            'parsed': parsed,
            'memory_hits': memory_payload,
            'summary': summary,
            'safety': {'emergency_stop': safety.emergency_stop, 'reason': safety.reason, 'updated_at': safety.updated_at},
        }

    if not command:
        return {
            'status': 'empty_command',
            'acknowledgement': 'No executable command found.',
            'parsed': parsed,
            'memory_hits': memory_payload,
        }

    plan_payload = None
    planning_error = ''
    try:
        from app.models.schemas import TaskSpec

        spec = TaskSpec(objective=command)
        plan = planner_service.build_plan(spec)
        plan_payload = plan.model_dump(mode='json')
    except Exception as exc:
        planning_error = str(exc)

    created_task = None
    status = 'planned'
    acknowledgement = 'Command analyzed and plan is ready.'
    if request.execute:
        created = await orchestrator.create_task(TaskCreateRequest(objective=command))
        created_task = created.model_dump(mode='json')
        status = 'task_created'
        acknowledgement = 'Command queued as task.'

    memory_service.upsert(
        key=f'assistant:command:{auth.request_id or command[:32]}',
        content=(
            f'raw={request.text}\n'
            f'command={command}\n'
            f'intent={intent}\n'
            f'execute={request.execute}\n'
            f'status={status}\n'
            f'planning_error={planning_error}'
        )[:4000],
        tags=['assistant_command', intent, status],
    )
    audit_service.log(actor=auth.role, action='assistant_command', details=f'intent={intent} execute={request.execute}', request_id=auth.request_id)
    return {
        'status': status,
        'acknowledgement': acknowledgement,
        'parsed': parsed,
        'memory_hits': memory_payload,
        'plan': plan_payload,
        'planning_error': planning_error,
        'task': created_task,
    }


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


@router.get('/ops/health/deep')
async def ops_health_deep(_: AuthContext = Depends(auth_service.require_admin)):
    return ops_service.health_deep()


@router.get('/ops/slo', response_model=OpsSLO)
async def ops_slo(_: AuthContext = Depends(auth_service.require_admin)) -> OpsSLO:
    return ops_service.slo()


@router.get('/ops/queue')
async def ops_queue(_: AuthContext = Depends(auth_service.require_admin)):
    return ops_service.queue()


@router.get('/ops/incidents', response_model=list[OpsIncident])
async def ops_incidents(
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthContext = Depends(auth_service.require_admin),
) -> list[OpsIncident]:
    return ops_service.incidents(limit=limit)


@router.get('/ops/secret-usage')
async def ops_secret_usage(
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthContext = Depends(auth_service.require_admin),
):
    return {'items': secret_vault.usage(limit=limit)}


@router.post('/memory/add', response_model=MemoryEntry)
async def memory_add(request: MemoryAddRequest, _: AuthContext = Depends(auth_service.require_admin)) -> MemoryEntry:
    return memory_service.upsert(key=request.key, content=request.content, tags=request.tags)


@router.post('/memory/search', response_model=list[MemoryEntry])
async def memory_search(request: MemorySearchRequest, _: AuthContext = Depends(auth_service.require_user)) -> list[MemoryEntry]:
    return memory_service.search(query=request.query, limit=request.limit)


@router.get('/memory/recent', response_model=list[MemoryEntry])
async def memory_recent(limit: int = Query(default=20, ge=1, le=200), _: AuthContext = Depends(auth_service.require_user)) -> list[MemoryEntry]:
    return memory_service.recent(limit=limit)


@router.post('/memory/embed', response_model=MemoryEmbedResponse)
async def memory_embed(request: MemoryEmbedRequest, _: AuthContext = Depends(auth_service.require_user)) -> MemoryEmbedResponse:
    return memory_service.embed(request.text)


@router.post('/memory/reindex', response_model=list[MemoryShardStats])
async def memory_reindex(request: MemoryReindexRequest, _: AuthContext = Depends(auth_service.require_admin)) -> list[MemoryShardStats]:
    return memory_service.reindex(limit=request.limit)


@router.get('/memory/graph')
async def memory_graph(limit: int = Query(default=50, ge=1, le=500), _: AuthContext = Depends(auth_service.require_user)):
    return memory_service.graph(KnowledgeGraphQueryRequest(limit=limit))


@router.post('/memory/graph/query')
async def memory_graph_query(
    request: KnowledgeGraphQueryRequest,
    _: AuthContext = Depends(auth_service.require_user),
):
    return memory_service.graph(request)


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
