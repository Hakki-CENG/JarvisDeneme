from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import ActionEnvelope, RollbackArtifact, RollbackPreviewRequest
from app.services.repositories import repositories


class RollbackService:
    def register_from_action(self, task_id: str, action: ActionEnvelope, output: dict) -> list[RollbackArtifact]:
        if not isinstance(output, dict):
            return []

        backup_path = output.get('rollback_backup')
        target_path = output.get('rollback_target')
        delete_target = output.get('rollback_delete_target')

        if not any([backup_path, target_path, delete_target]):
            return []

        artifact = RollbackArtifact(
            task_id=task_id,
            action_id=action.id,
            action_type=action.action.value,
            backup_path=str(backup_path) if backup_path else None,
            target_path=str(target_path) if target_path else None,
            delete_target=str(delete_target) if delete_target else None,
        )
        repositories['rollback_artifacts'].save(artifact)
        return [artifact]

    def preview(self, request: RollbackPreviewRequest) -> list[RollbackArtifact]:
        return repositories['rollback_artifacts'].list(
            task_id=request.task_id,
            include_applied=request.include_applied,
            limit=request.limit,
        )

    def list_by_task(self, task_id: str) -> list[RollbackArtifact]:
        return repositories['rollback_artifacts'].list_by_task(task_id)

    def get(self, artifact_id: str) -> RollbackArtifact | None:
        return repositories['rollback_artifacts'].get(artifact_id)

    def mark_applied(self, artifact_id: str) -> RollbackArtifact | None:
        artifact = repositories['rollback_artifacts'].get(artifact_id)
        if not artifact:
            return None
        artifact.applied_at = datetime.now(timezone.utc)
        repositories['rollback_artifacts'].save(artifact)
        return artifact


rollback_service = RollbackService()
