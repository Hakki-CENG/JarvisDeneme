from __future__ import annotations

import asyncio

from app.models.schemas import ResumeRequest, TaskStatus
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
        self._runner = asyncio.create_task(self._loop())
        asyncio.create_task(orchestrator.recover_incomplete_tasks())

    async def _loop(self) -> None:
        while True:
            try:
                await self._resume_paused_quota_tasks()
                self._cycle += 1
                if self._cycle % 10 == 0:
                    housekeeping_service.cleanup()
            except Exception:
                # Keep scheduler alive even if one cycle fails.
                pass
            await asyncio.sleep(90)

    async def _resume_paused_quota_tasks(self) -> None:
        if safety_service.status().emergency_stop:
            return
        tasks = orchestrator.list_tasks()
        for task in tasks:
            if task.status == TaskStatus.paused_quota:
                await orchestrator.resume_task(task.id, ResumeRequest(note='auto resume scheduler'))


runtime_scheduler = RuntimeScheduler()
