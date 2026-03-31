from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.models.schemas import ResumeRequest, TaskStatus
from app.services.audit_service import audit_service
from app.services.housekeeping_service import housekeeping_service
from app.services.safety_service import safety_service
from app.services.task_orchestrator import orchestrator


class RuntimeScheduler:
    def __init__(self) -> None:
        self._runner: asyncio.Task | None = None
        self._cycle = 0

    def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        orchestrator.start_dispatcher()
        self._runner = asyncio.create_task(self._loop())
        asyncio.create_task(orchestrator.recover_incomplete_tasks())

    async def _loop(self) -> None:
        while True:
            try:
                await self._resume_paused_quota_tasks()
                await self._watchdog_recover_stalled_tasks()
                self._cycle += 1
                if self._cycle % 10 == 0:
                    housekeeping_service.cleanup()
            except Exception as exc:
                # Keep scheduler alive even if one cycle fails.
                audit_service.log(
                    actor='scheduler',
                    action='runtime_scheduler_cycle_error',
                    details=f'{type(exc).__name__}: {exc}',
                )
            await asyncio.sleep(90)

    async def _resume_paused_quota_tasks(self) -> None:
        if safety_service.status().emergency_stop:
            return
        tasks = orchestrator.list_tasks()
        for task in tasks:
            if task.status == TaskStatus.paused_quota:
                await orchestrator.resume_task(task.id, ResumeRequest(note='auto resume scheduler'))

    async def _watchdog_recover_stalled_tasks(self) -> None:
        if safety_service.status().emergency_stop:
            return
        now = datetime.now(timezone.utc)
        tasks = orchestrator.list_tasks()
        for task in tasks:
            if task.status not in {TaskStatus.pending, TaskStatus.running}:
                continue
            age_seconds = (now - task.updated_at).total_seconds()
            if age_seconds <= 600:
                continue
            audit_service.log(
                actor='scheduler',
                action='watchdog_stalled_task',
                details=f'task_id={task.id} age_seconds={int(age_seconds)} -> requeue',
            )
            await orchestrator.resume_task(task.id, ResumeRequest(note='watchdog stalled task requeue'))


runtime_scheduler = RuntimeScheduler()
