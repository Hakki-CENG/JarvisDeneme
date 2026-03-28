from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.models.schemas import ActionEnvelope, ActionResult


class DesktopEngine(ABC):
    @abstractmethod
    async def execute(self, action: ActionEnvelope) -> ActionResult:
        raise NotImplementedError

    @abstractmethod
    async def apply_rollback(
        self,
        backup_path: str | None,
        target_path: str | None,
        delete_target: str | None = None,
        approved: bool = False,
    ) -> ActionResult:
        raise NotImplementedError


class SimulatedDesktopEngine(DesktopEngine):
    async def execute(self, action: ActionEnvelope) -> ActionResult:
        return ActionResult(
            action_id=action.id,
            success=True,
            output={
                'simulated': True,
                'action': action.action,
                'parameters': action.parameters,
            },
        )

    async def apply_rollback(
        self,
        backup_path: str | None,
        target_path: str | None,
        delete_target: str | None = None,
        approved: bool = False,
    ) -> ActionResult:
        return ActionResult(
            action_id='rollback',
            success=True,
            output={
                'simulated': True,
                'backup_path': backup_path,
                'target_path': target_path,
                'delete_target': delete_target,
                'approved': approved,
            },
        )


def ensure_directory(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
