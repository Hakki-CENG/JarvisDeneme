from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import (
    FallbackDecision,
    MissionCreateRequest,
    MissionGraph,
    MissionSimulationReport,
    MissionTemplate,
    MissionRecord,
    MissionReplanRequest,
    MissionSummary,
    TaskSpec,
)
from app.services.planner_service import planner_service
from app.services.repositories import repositories


class MissionService:
    STATUS_MAP = {
        'PENDING': 'QUEUED',
        'RUNNING': 'RUNNING',
        'WAITING_APPROVAL': 'RUNNING',
        'PAUSED_QUOTA': 'RUNNING',
        'FAILED': 'FAILED',
        'CANCELLED': 'CANCELLED',
        'COMPLETED': 'COMPLETED',
    }
    def __init__(self) -> None:
        self._templates: dict[str, MissionTemplate] = {}

    def create(self, request: MissionCreateRequest) -> MissionRecord:
        spec = TaskSpec(
            objective=request.objective,
            constraints=request.constraints,
            tools_allowed=request.tools_allowed,
            priority=request.priority,
        )
        graph = planner_service.build_mission_graph(spec)
        status = 'QUEUED' if request.auto_execute else 'DRAFT'
        record = MissionRecord(mission=graph, status=status)
        repositories['missions'].save(record)
        return record

    def get(self, mission_id: str) -> MissionRecord | None:
        return repositories['missions'].get(mission_id)

    def list(self) -> list[MissionSummary]:
        return [self.to_summary(item) for item in repositories['missions'].list_all()]

    def link_task(self, mission_id: str, task_id: str) -> MissionRecord | None:
        record = repositories['missions'].get(mission_id)
        if not record:
            return None
        record.task_id = task_id
        if record.status in {'DRAFT', 'QUEUED'}:
            record.status = 'RUNNING'
        record.updated_at = datetime.now(timezone.utc)
        repositories['missions'].save(record)
        return record

    def sync_task_status(self, task_id: str, task_status: str, reason: str = '') -> None:
        record = repositories['missions'].find_by_task(task_id)
        if not record:
            return
        mapped = self.STATUS_MAP.get(task_status.upper(), record.status)
        record.status = mapped
        record.last_error = reason or None
        record.updated_at = datetime.now(timezone.utc)
        repositories['missions'].save(record)

    def replan(self, mission_id: str, request: MissionReplanRequest) -> MissionRecord | None:
        record = repositories['missions'].get(mission_id)
        if not record:
            return None
        spec = TaskSpec(
            id=record.task_id or record.mission.mission_id,
            objective=record.mission.objective,
            constraints=[request.reason],
        )
        graph: MissionGraph = planner_service.build_mission_graph(spec)
        record.mission = graph
        record.updated_at = datetime.now(timezone.utc)
        if record.status in {'FAILED', 'COMPLETED', 'CANCELLED'}:
            record.status = 'QUEUED'
        repositories['missions'].save(record)
        return record

    def graph(self, mission_id: str) -> MissionGraph | None:
        record = repositories['missions'].get(mission_id)
        if not record:
            return None
        return record.mission

    def create_template(self, template: MissionTemplate) -> MissionTemplate:
        self._templates[template.id] = template
        return template

    def simulate(self, mission_id: str) -> MissionSimulationReport | None:
        record = repositories['missions'].get(mission_id)
        if not record:
            return None
        decisions: list[FallbackDecision] = []
        risk_score = 0.0
        for node in record.mission.nodes:
            selected = node.primary_tool or (node.fallback_tools[0] if node.fallback_tools else 'manual_review')
            decisions.append(
                FallbackDecision(
                    node_id=node.id,
                    selected_tool=selected,
                    reason='primary tool selected from mission graph',
                    dry_check_passed=bool(node.dry_check.get('simulated', False)),
                )
            )
            if not node.primary_tool:
                risk_score += 0.2
            if node.fallback_tools:
                risk_score += 0.05

        return MissionSimulationReport(
            mission_id=mission_id,
            feasible=True,
            estimated_steps=len(record.mission.nodes),
            risk_score=min(risk_score, 1.0),
            fallback_decisions=decisions,
            notes=['simulation uses dry-check metadata and fallback chain'],
        )

    @staticmethod
    def to_summary(record: MissionRecord) -> MissionSummary:
        return MissionSummary(
            id=record.mission.mission_id,
            objective=record.mission.objective,
            status=record.status,
            task_id=record.task_id,
            created_at=record.mission.created_at,
            updated_at=record.updated_at,
            last_error=record.last_error,
        )


mission_service = MissionService()
