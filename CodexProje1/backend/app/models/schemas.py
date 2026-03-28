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
    created_at: datetime = Field(default_factory=utcnow)


class TaskCreateRequest(BaseModel):
    objective: str
    constraints: list[str] = Field(default_factory=list)
    tools_allowed: list[ActionType] = Field(default_factory=lambda: list(ActionType))


class TaskSummary(BaseModel):
    id: str
    status: TaskStatus
    objective: str
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


class VisionOcrRequest(BaseModel):
    image_path: str


class SkillManifest(BaseModel):
    skill_id: str
    version: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    risk_level: Literal['LOW', 'MEDIUM', 'HIGH'] = 'LOW'
    entrypoint: str | None = None


class SkillRunRequest(BaseModel):
    skill_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class SkillRunResult(BaseModel):
    skill_id: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class EmergencyStopRequest(BaseModel):
    reason: str = 'Manual emergency stop'


class SecretSetRequest(BaseModel):
    name: str
    value: str


class RollbackApplyRequest(BaseModel):
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
