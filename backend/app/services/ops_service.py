from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.schemas import OpsIncident, OpsSLO, TaskStatus
from app.services.approval_service import approval_service
from app.services.model_router import model_router
from app.services.repositories import repositories
from app.services.safety_service import safety_service
from app.services.storage import store
from app.services.task_orchestrator import orchestrator
from app.services.tool_fabric import tool_fabric_service


class OpsService:
    def health_deep(self) -> dict:
        tasks = orchestrator.list_tasks()
        tool_health = tool_fabric_service.health()
        quotas = model_router.quotas().model_dump(mode='json')
        safety = safety_service.status()
        return {
            'status': 'ok',
            'components': {
                'orchestrator': {'tasks_total': len(tasks), 'running': len([t for t in tasks if t.status == TaskStatus.running])},
                'tool_fabric': {
                    'catalog_size': len(tool_fabric_service.list_catalog()),
                    'circuit_open_tools': len([item for item in tool_health if item.circuit_open]),
                },
                'safety': {'emergency_stop': safety.emergency_stop, 'reason': safety.reason},
                'models': quotas,
            },
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def slo(self) -> OpsSLO:
        tasks = orchestrator.list_tasks()
        queue = repositories['task_queue'].list_all()
        pending_approvals = approval_service.list_pending()
        providers = model_router.quotas().providers
        quota_total = max(len(providers) * 300, 1)
        quota_left = sum(max(provider.remaining_requests, 0) for provider in providers)
        burn_rate = round(max(0.0, min(1.0, 1 - (quota_left / quota_total))), 4)
        now = datetime.now(timezone.utc)
        stuck = 0
        for task in tasks:
            if task.status not in {TaskStatus.pending, TaskStatus.running, TaskStatus.waiting_approval, TaskStatus.paused_quota}:
                continue
            age = (now - task.updated_at).total_seconds()
            if age > 600:
                stuck += 1
        return OpsSLO(
            queue_depth=len(queue),
            stuck_tasks=stuck,
            approval_backlog=len(pending_approvals),
            quota_burn_rate=burn_rate,
        )

    def queue(self) -> list[dict]:
        return repositories['task_queue'].list_all()

    def incidents(self, limit: int = 100) -> list[OpsIncident]:
        with store.conn() as conn:
            rows = conn.execute(
                '''
                SELECT payload
                FROM incidents
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [OpsIncident.model_validate(store.load(row[0])) for row in rows]

    def add_incident(self, incident: OpsIncident) -> OpsIncident:
        payload = incident.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO incidents (id, level, kind, summary, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    incident.id or str(uuid4()),
                    incident.level,
                    incident.kind,
                    incident.summary,
                    incident.created_at.isoformat(),
                    store.dump(payload),
                ),
            )
        return incident


ops_service = OpsService()

