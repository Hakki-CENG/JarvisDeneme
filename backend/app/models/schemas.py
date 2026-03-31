from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    pending = 'PENDING'
    running = 'RUNNING'
    waiting_approval = 'WAITING_APPROVAL'
    paused_quota = 'PAUSED_QUOTA'
    failed = 'FAILED'
    cancelled = 'CANCELLED'
    completed = 'COMPLETED'


class ActionType(str, Enum):
    move_mouse = 'move_mouse'
    click = 'click'
    type_text = 'type_text'
    hotkey = 'hotkey'
    wait = 'wait'
    open_app = 'open_app'
    focus_window = 'focus_window'
    read_screen = 'read_screen'
    file_ops = 'file_ops'
    shell_exec = 'shell_exec'
    browser_script = 'browser_script'
    http_request = 'http_request'
    clipboard_read = 'clipboard_read'
    clipboard_write = 'clipboard_write'


class TaskSpec(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    objective: str
    constraints: list[str] = Field(default_factory=list)
    tools_allowed: list[ActionType] = Field(default_factory=lambda: list(ActionType))
    priority: int = Field(default=5, ge=1, le=10)
    created_at: datetime = Field(default_factory=utcnow)


class TaskCreateRequest(BaseModel):
    objective: str
    constraints: list[str] = Field(default_factory=list)
    tools_allowed: list[ActionType] = Field(default_factory=lambda: list(ActionType))
    priority: int = Field(default=5, ge=1, le=10)


class TaskSummary(BaseModel):
    id: str
    status: TaskStatus
    objective: str
    priority: int = Field(default=5, ge=1, le=10)
    created_at: datetime
    updated_at: datetime
    last_error: str | None = None


class TaskRecord(BaseModel):
    spec: TaskSpec
    status: TaskStatus = TaskStatus.pending
    updated_at: datetime = Field(default_factory=utcnow)
    last_error: str | None = None
    trace_ids: list[str] = Field(default_factory=list)


class ActionEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    action: ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    justification: str = ''
    risk_score: float = 0.0
    requires_approval: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class ActionResult(BaseModel):
    action_id: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    executed_at: datetime = Field(default_factory=utcnow)


class RuntimeSnapshot(BaseModel):
    task_id: str
    actions: list[ActionEnvelope] = Field(default_factory=list)
    next_action_index: int = 0
    pending_steps: list[str] = Field(default_factory=list)
    step_action_counts: list[int] = Field(default_factory=list)
    current_step_index: int = 0
    completed_actions_in_current_step: int = 0
    replan_attempts: int = 0
    updated_at: datetime = Field(default_factory=utcnow)


class PlannedStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str
    actions: list[ActionEnvelope] = Field(default_factory=list)
    done: bool = False


class TaskPlan(BaseModel):
    task_id: str
    strategy: str
    steps: list[PlannedStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class ApprovalDecision(str, Enum):
    approve = 'APPROVE'
    reject = 'REJECT'


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    action_id: str
    action: ActionType
    reason: str
    impact: str
    rollback: str
    requested_at: datetime = Field(default_factory=utcnow)
    status: Literal['PENDING', 'APPROVED', 'REJECTED'] = 'PENDING'
    decided_at: datetime | None = None


class ApprovalSubmitRequest(BaseModel):
    decision: ApprovalDecision


class RiskReport(BaseModel):
    action_id: str
    risk_score: float
    reasons: list[str]
    requires_approval: bool


class Checkpoint(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    phase: str
    memory_ref: str
    pending_steps: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class ExecutionTrace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    agent: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ResumeRequest(BaseModel):
    note: str = ''


class CancelRequest(BaseModel):
    reason: str = 'Task cancelled by user'


class SelfImproveRunRequest(BaseModel):
    focus: str = 'all'


class VoiceSpeakRequest(BaseModel):
    text: str


class VoiceTranscribeRequest(BaseModel):
    path: str


class VoiceMicRequest(BaseModel):
    timeout_seconds: float = 8.0
    phrase_time_limit: float = 12.0


class VoiceCommandRequest(BaseModel):
    text: str
    wake_word: str = 'jarvis'


class AssistantCommandRequest(BaseModel):
    text: str
    execute: bool = False
    wake_word: str = 'jarvis'


class VisionOcrRequest(BaseModel):
    image_path: str


class SkillWorkflowStep(BaseModel):
    skill_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class SkillManifest(BaseModel):
    skill_id: str
    version: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    risk_level: Literal['LOW', 'MEDIUM', 'HIGH'] = 'LOW'
    kind: Literal['VIRTUAL', 'EXECUTABLE'] = 'EXECUTABLE'
    namespace: str = 'default'
    entrypoint: str | None = None
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    source: str = 'local'
    quality_score: float = 0.5
    success_count: int = 0
    failure_count: int = 0
    avg_latency_ms: float = 0.0
    feedback_score: float = 0.0
    workflow: list['SkillWorkflowStep'] = Field(default_factory=list)


class SkillRunRequest(BaseModel):
    skill_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class SkillRunResult(BaseModel):
    skill_id: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class SkillSearchRequest(BaseModel):
    query: str
    limit: int = 20
    include_virtual: bool = True


class SkillComposeRequest(BaseModel):
    skill_id: str
    version: str = '1.0.0'
    description: str
    steps: list[SkillWorkflowStep] = Field(default_factory=list)
    risk_level: Literal['LOW', 'MEDIUM', 'HIGH'] = 'MEDIUM'
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SkillCatalogBootstrapRequest(BaseModel):
    target_count: int = 5000
    prefix: str = 'autogen'


class CodeInsightRequest(BaseModel):
    max_items: int = 40


class CodeInsightItem(BaseModel):
    file: str
    line: int
    issue: str
    severity: Literal['LOW', 'MEDIUM', 'HIGH']
    suggestion: str


class EmergencyStopRequest(BaseModel):
    reason: str = 'Manual emergency stop'


class SecretSetRequest(BaseModel):
    name: str
    value: str


class RollbackApplyRequest(BaseModel):
    artifact_id: str | None = None
    backup_path: str | None = None
    target_path: str | None = None
    delete_target: str | None = None


class MemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    key: str
    content: str
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MemoryAddRequest(BaseModel):
    key: str
    content: str
    tags: list[str] = Field(default_factory=list)


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 8


class AuthBootstrapRequest(BaseModel):
    admin_token: str
    user_token: str | None = None


class AuthBootstrapResponse(BaseModel):
    status: str
    admin_token_set: bool
    user_token_set: bool


class AuthSession(BaseModel):
    role: Literal['ADMIN', 'USER']
    token_hint: str
    request_id: str = ''


class MetricSnapshot(BaseModel):
    requests_total: int = 0
    requests_blocked: int = 0
    tasks_created: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    approvals_requested: int = 0
    approvals_rejected: int = 0
    model_calls: int = 0
    updated_at: datetime = Field(default_factory=utcnow)


class ImprovementProposal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    gap: str
    proposal: str
    expected_impact: str
    created_at: datetime = Field(default_factory=utcnow)


class SelfImproveReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
    status: Literal['RUNNING', 'COMPLETED', 'FAILED'] = 'RUNNING'
    findings: list[ImprovementProposal] = Field(default_factory=list)
    tests_passed: bool = False
    risk_summary: str = ''
    actions: list[str] = Field(default_factory=list)


class ProviderQuota(BaseModel):
    provider: str
    remaining_requests: int
    reset_at: datetime | None = None
    enabled: bool = True


class ModelQuotaResponse(BaseModel):
    primary: str
    selected_provider: str | None
    providers: list[ProviderQuota]


class EventMessage(BaseModel):
    type: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utcnow)


class ToolRetryPolicy(BaseModel):
    max_attempts: int = Field(default=2, ge=1, le=5)
    backoff_seconds: float = Field(default=1.0, ge=0.0, le=30.0)


class ToolManifest(BaseModel):
    name: str
    version: str = '1.0.0'
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal['LOW', 'MEDIUM', 'HIGH'] = 'LOW'
    idempotent: bool = True
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    retry_policy: ToolRetryPolicy = Field(default_factory=ToolRetryPolicy)
    rollback_hint: str = ''
    enabled: bool = True
    optional: bool = False
    source: str = 'builtin'
    category: str = 'general'
    description: str = ''
    dependencies: list['ToolDependency'] = Field(default_factory=list)


class ToolExecutionRequest(BaseModel):
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    approved: bool = False


class ToolToggleRequest(BaseModel):
    enabled: bool


class ToolExecutionResult(BaseModel):
    name: str
    requested_name: str | None = None
    resolved_version: str | None = None
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    cached: bool = False
    attempts: int = 1
    latency_ms: int = 0
    timestamp: datetime = Field(default_factory=utcnow)


class ToolHealth(BaseModel):
    name: str
    enabled: bool
    circuit_open: bool
    cache_items: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_latency_ms: int = 0
    recent_calls: int = 0


class ToolDependency(BaseModel):
    name: str
    minimum_version: str = '1.0.0'
    required: bool = True


class ToolExecutionTrace(BaseModel):
    tool: str
    version: str = '1.0.0'
    attempts: int = 1
    latency_ms: int = 0
    error_code: str | None = None
    provider: str = 'local'


class ToolManifestV2(BaseModel):
    manifest: ToolManifest
    promoted: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class ToolBatchExecutionRequest(BaseModel):
    requests: list[ToolExecutionRequest] = Field(default_factory=list)
    stop_on_error: bool = False


class ToolBatchExecutionResult(BaseModel):
    success: bool
    results: list[ToolExecutionResult] = Field(default_factory=list)
    failed_count: int = 0
    success_count: int = 0


class ToolPromoteRequest(BaseModel):
    version: str


class MissionNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str
    primary_tool: str | None = None
    fallback_tools: list[str] = Field(default_factory=list)
    tool_selection_rationale: str = ''
    depends_on: list[str] = Field(default_factory=list)
    success_criteria: str = 'Step output validates expected objective'
    dry_check: dict[str, Any] = Field(default_factory=dict)


class MissionGraph(BaseModel):
    mission_id: str = Field(default_factory=lambda: str(uuid4()))
    objective: str
    strategy: str
    nodes: list[MissionNode] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class MissionRecord(BaseModel):
    mission: MissionGraph
    status: Literal['DRAFT', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'] = 'DRAFT'
    task_id: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
    last_error: str | None = None


class MissionCreateRequest(BaseModel):
    objective: str
    constraints: list[str] = Field(default_factory=list)
    tools_allowed: list[ActionType] = Field(default_factory=lambda: list(ActionType))
    priority: int = Field(default=5, ge=1, le=10)
    auto_execute: bool = True


class MissionSummary(BaseModel):
    id: str
    objective: str
    status: Literal['DRAFT', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED']
    task_id: str | None = None
    created_at: datetime
    updated_at: datetime
    last_error: str | None = None


class MissionReplanRequest(BaseModel):
    reason: str = 'manual_replan'


class RollbackArtifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    action_id: str
    action_type: str
    backup_path: str | None = None
    target_path: str | None = None
    delete_target: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    applied_at: datetime | None = None


class RollbackPreviewRequest(BaseModel):
    task_id: str | None = None
    include_applied: bool = False
    limit: int = Field(default=100, ge=1, le=500)


class ExecutionActionLog(BaseModel):
    action_id: str
    action: str
    risk_score: float = 0.0
    requires_approval: bool = False
    success: bool
    error: str | None = None
    changed_resources: list[str] = Field(default_factory=list)
    rollback_artifact_ids: list[str] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=utcnow)


class ExecutionReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    mission_id: str | None = None
    status: Literal['RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'] = 'RUNNING'
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
    duration_ms: int = 0
    tools_used: list[str] = Field(default_factory=list)
    changed_resources: list[str] = Field(default_factory=list)
    rollback_points: list[str] = Field(default_factory=list)
    risk_summary: str = ''
    quota_snapshot: dict[str, Any] = Field(default_factory=dict)
    actions: list[ExecutionActionLog] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ImprovementCategory(str, Enum):
    security = 'security'
    performance = 'performance'
    correctness = 'correctness'
    capability = 'capability'


class ImprovementProposalV2(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    category: ImprovementCategory
    observation: str
    proposal: str
    patch_path: str | None = None
    test_command: str = 'pytest -q'
    test_result: str = ''
    risk_score: float = Field(default=0.5, ge=0.0, le=1.0)
    status: Literal['PENDING', 'APPROVED', 'REJECTED', 'APPLIED', 'FAILED'] = 'PENDING'
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None
    decision_note: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProposalGenerateRequest(BaseModel):
    focus: str = 'all'
    max_items: int = Field(default=5, ge=1, le=25)


class ProposalDecisionRequest(BaseModel):
    note: str = ''


class FallbackDecision(BaseModel):
    node_id: str
    selected_tool: str
    reason: str
    dry_check_passed: bool = True


class MissionTemplate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    objective_pattern: str
    default_constraints: list[str] = Field(default_factory=list)
    default_tools: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class MissionSimulationReport(BaseModel):
    mission_id: str
    feasible: bool = True
    estimated_steps: int = 0
    risk_score: float = 0.0
    fallback_decisions: list[FallbackDecision] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MemoryEmbedRequest(BaseModel):
    text: str


class MemoryEmbedResponse(BaseModel):
    vector: list[float]
    dimensions: int
    strategy: str


class MemoryReindexRequest(BaseModel):
    limit: int = Field(default=1000, ge=1, le=100000)


class MemoryShardStats(BaseModel):
    shard: str
    entries: int
    avg_score: float


class KnowledgeNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    key: str
    label: str
    node_type: str = 'entity'
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeEdge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_key: str
    target_key: str
    relation: str
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphQueryRequest(BaseModel):
    query: str = ''
    node_key: str | None = None
    relation: str | None = None
    limit: int = Field(default=50, ge=1, le=500)


class ValidationSuiteResult(BaseModel):
    command: str
    status: Literal['PASS', 'FAIL', 'SKIPPED'] = 'SKIPPED'
    details: str = ''


class ApplyPackage(BaseModel):
    package_path: str
    patch_path: str
    rationale: str


class ImprovementJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    focus: str = 'all'
    status: Literal['QUEUED', 'RUNNING', 'WAITING_APPROVAL', 'APPROVED', 'REJECTED', 'APPLIED', 'FAILED', 'CANCELLED'] = 'QUEUED'
    proposals: list[str] = Field(default_factory=list)
    validation: ValidationSuiteResult | None = None
    apply_package: ApplyPackage | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    reason: str = ''


class ImprovementJobCreateRequest(BaseModel):
    focus: str = 'all'
    max_items: int = Field(default=5, ge=1, le=25)


class ImprovementJobCancelRequest(BaseModel):
    reason: str = 'cancelled_by_user'


class OpsSLO(BaseModel):
    queue_depth: int
    stuck_tasks: int
    approval_backlog: int
    quota_burn_rate: float


class OpsIncident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    level: Literal['INFO', 'WARN', 'ERROR'] = 'INFO'
    kind: str
    summary: str
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
