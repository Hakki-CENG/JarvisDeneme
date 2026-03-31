from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import ActionEnvelope, ActionResult, ExecutionActionLog, ExecutionReport
from app.services.model_router import model_router
from app.services.repositories import repositories
from app.services.rollback_service import rollback_service


class ExecutionReportService:
    def start(self, task_id: str, mission_id: str | None = None) -> ExecutionReport:
        existing = repositories['execution_reports'].get_by_task(task_id)
        if existing and existing.status == 'RUNNING':
            if mission_id and not existing.mission_id:
                existing.mission_id = mission_id
                repositories['execution_reports'].save(existing)
            return existing

        report = ExecutionReport(task_id=task_id, mission_id=mission_id, status='RUNNING')
        repositories['execution_reports'].save(report)
        return report

    def record_action(self, task_id: str, action: ActionEnvelope, result: ActionResult) -> ExecutionReport:
        report = repositories['execution_reports'].get_by_task(task_id) or self.start(task_id=task_id)
        artifact_ids: list[str] = []
        pre_registered = result.output.get('_rollback_artifact_ids')
        if isinstance(pre_registered, list) and pre_registered:
            artifact_ids = [str(item) for item in pre_registered]
        else:
            artifacts = rollback_service.register_from_action(task_id=task_id, action=action, output=result.output)
            if artifacts:
                artifact_ids = [item.id for item in artifacts]

        changed_resources = self._extract_changed_resources(output=result.output)
        entry = ExecutionActionLog(
            action_id=action.id,
            action=action.action.value,
            risk_score=action.risk_score,
            requires_approval=action.requires_approval,
            success=result.success,
            error=result.error,
            changed_resources=changed_resources,
            rollback_artifact_ids=artifact_ids,
            executed_at=result.executed_at,
        )
        report.actions.append(entry)

        if action.action.value not in report.tools_used:
            report.tools_used.append(action.action.value)

        for item in changed_resources:
            if item not in report.changed_resources:
                report.changed_resources.append(item)
        for artifact_id in artifact_ids:
            if artifact_id not in report.rollback_points:
                report.rollback_points.append(artifact_id)

        repositories['execution_reports'].save(report)
        return report

    def finalize(self, task_id: str, status: str, reason: str = '') -> ExecutionReport | None:
        report = repositories['execution_reports'].get_by_task(task_id)
        if not report:
            return None

        report.status = status if status in {'COMPLETED', 'FAILED', 'CANCELLED'} else 'FAILED'
        report.ended_at = datetime.now(timezone.utc)
        report.duration_ms = int((report.ended_at - report.started_at).total_seconds() * 1000)

        quotas = model_router.quotas().model_dump(mode='json')
        report.quota_snapshot = quotas
        risk_sentence = (
            f'actions={len(report.actions)} rollback_points={len(report.rollback_points)} '
            f'with {len([item for item in report.actions if item.requires_approval])} approval-gated action(s)'
        )
        report.risk_summary = risk_sentence
        if reason:
            report.notes.append(reason)

        repositories['execution_reports'].save(report)
        return report

    def get_by_task(self, task_id: str) -> ExecutionReport | None:
        return repositories['execution_reports'].get_by_task(task_id)

    @staticmethod
    def _extract_changed_resources(output: dict) -> list[str]:
        if not isinstance(output, dict):
            return []

        keys = ['path', 'src', 'dst', 'url', 'rollback_target', 'rollback_delete_target']
        resources: list[str] = []
        for key in keys:
            value = output.get(key)
            if not value:
                continue
            normalized = str(value)
            if normalized not in resources:
                resources.append(normalized)

        if output.get('status_code') and output.get('url'):
            marker = f"HTTP:{output.get('status_code')}:{output.get('url')}"
            if marker not in resources:
                resources.append(marker)

        return resources


execution_report_service = ExecutionReportService()
