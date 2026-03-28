from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.settings import settings
from app.models.schemas import (
    ActionEnvelope,
    ActionResult,
    ApprovalRequest,
    Checkpoint,
    EventMessage,
    ResumeRequest,
    RuntimeSnapshot,
    TaskCreateRequest,
    TaskRecord,
    TaskSpec,
    TaskStatus,
    TaskSummary,
)
from app.services.agents.mesh import agent_mesh
from app.services.approval_service import approval_service
from app.services.audit_service import audit_service
from app.services.desktop.windows_engine import build_desktop_engine
from app.services.event_bus import event_bus
from app.services.memory_service import memory_service
from app.services.metrics_service import metrics_service
from app.services.model_router import ProviderExhaustedError
from app.services.plan_verifier_service import plan_verifier_service
from app.services.planner_service import planner_service
from app.services.repositories import repositories
from app.services.risk_engine import risk_engine
from app.services.safety_service import safety_service
from app.services.world_state_service import world_state_service


@dataclass
class RuntimeState:
    actions: list[ActionEnvelope] = field(default_factory=list)
    next_action_index: int = 0
    pending_steps: list[str] = field(default_factory=list)
    replan_attempts: int = 0
    active_worker: asyncio.Task | None = None

    def to_snapshot(self, task_id: str) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            task_id=task_id,
            actions=self.actions,
            next_action_index=self.next_action_index,
            pending_steps=self.pending_steps,
            replan_attempts=self.replan_attempts,
            updated_at=datetime.now(timezone.utc),
        )


class TaskOrchestrator:
    def __init__(self) -> None:
        self._desktop_engine = build_desktop_engine()
        self._runtime: dict[str, RuntimeState] = {}
        self._lock = asyncio.Lock()
        self._worker_semaphore = asyncio.Semaphore(max(1, settings.max_parallel_workers))

    async def create_task(self, request: TaskCreateRequest) -> TaskSummary:
        spec = TaskSpec(
            objective=request.objective,
            constraints=request.constraints,
            tools_allowed=request.tools_allowed,
        )
        record = TaskRecord(spec=spec)
        repositories['tasks'].save(record)
        metrics_service.inc('tasks_created')
        audit_service.log(actor='system', action='task_created', details=f'task_id={spec.id} objective={spec.objective[:160]}')

        await event_bus.publish(
            EventMessage(type='task_created', payload={'task_id': spec.id, 'objective': spec.objective}),
            task_id=spec.id,
        )

        await self._start_worker(spec.id)
        return self._summary(record)

    def get_task(self, task_id: str) -> TaskSummary | None:
        record = repositories['tasks'].get(task_id)
        return self._summary(record) if record else None

    def list_tasks(self) -> list[TaskSummary]:
        return [self._summary(item) for item in repositories['tasks'].list_all()]

    def list_checkpoints(self, task_id: str) -> list[Checkpoint]:
        return repositories['checkpoints'].list_by_task(task_id)

    async def recover_incomplete_tasks(self) -> None:
        tasks = repositories['tasks'].list_all()
        for task in tasks:
            if task.status in {TaskStatus.pending, TaskStatus.running, TaskStatus.waiting_approval, TaskStatus.paused_quota}:
                await self._start_worker(task.spec.id)

    async def resume_task(self, task_id: str, request: ResumeRequest) -> TaskSummary | None:
        record = repositories['tasks'].get(task_id)
        if not record:
            return None
        if safety_service.status().emergency_stop:
            record.status = TaskStatus.failed
            record.last_error = f"Cannot resume while emergency stop is active: {safety_service.status().reason or 'no reason'}"
            record.updated_at = datetime.now(timezone.utc)
            repositories['tasks'].save(record)
            await event_bus.publish(
                EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                task_id=task_id,
            )
            return self._summary(record)

        await event_bus.publish(
            EventMessage(
                type='task_resume_requested',
                payload={'task_id': task_id, 'note': request.note},
            ),
            task_id=task_id,
        )

        await self._start_worker(task_id)
        latest = repositories['tasks'].get(task_id)
        return self._summary(latest) if latest else None

    async def cancel_task(self, task_id: str, reason: str = 'Task cancelled by user') -> TaskSummary | None:
        record = repositories['tasks'].get(task_id)
        if not record:
            return None
        if record.status in {TaskStatus.completed, TaskStatus.failed}:
            return self._summary(record)

        runtime = self._load_runtime(task_id)
        if runtime.active_worker and not runtime.active_worker.done():
            runtime.active_worker.cancel()

        record.status = TaskStatus.cancelled
        record.last_error = reason
        record.updated_at = datetime.now(timezone.utc)
        repositories['tasks'].save(record)
        self._save_runtime(task_id, runtime)
        world_state_service.update(task_id, {'phase': 'cancelled', 'status': 'CANCELLED', 'reason': reason})
        memory_service.upsert(
            key=f'task:{task_id}:cancelled',
            content=f'Objective={record.spec.objective}\nReason={reason}\nStatus=CANCELLED',
            tags=['task', 'cancelled'],
        )
        await event_bus.publish(
            EventMessage(type='task_cancelled', payload={'task_id': task_id, 'reason': reason}),
            task_id=task_id,
        )
        return self._summary(record)

    async def execute_manual_action(self, action: ActionEnvelope) -> ActionResult:
        if safety_service.status().emergency_stop:
            return ActionResult(
                action_id=action.id,
                success=False,
                error=f"Emergency stop active: {safety_service.status().reason or 'No reason provided'}",
            )

        risk = risk_engine.evaluate(action)
        action.risk_score = risk.risk_score
        action.requires_approval = risk.requires_approval

        if risk.requires_approval:
            approval = ApprovalRequest(
                task_id=action.task_id,
                action_id=action.id,
                action=action.action,
                reason='Manual desktop action exceeded risk threshold.',
                impact='Action may alter files/system/app state.',
                rollback='Review generated rollback notes before approving.',
            )
            await approval_service.create(approval)
            metrics_service.inc('approvals_requested')
            decided = await approval_service.wait_for_decision(approval.id, timeout_seconds=settings.approval_timeout_seconds)
            if not decided or decided.status != 'APPROVED':
                if decided and decided.status == 'REJECTED':
                    metrics_service.inc('approvals_rejected')
                return ActionResult(action_id=action.id, success=False, error='Manual action approval rejected or timed out.')

        result = await self._desktop_engine.execute(action)
        await event_bus.publish(
            EventMessage(type='manual_action_result', payload=result.model_dump(mode='json')),
            task_id=action.task_id,
        )
        return result

    async def apply_rollback(
        self,
        backup_path: str | None,
        target_path: str | None,
        delete_target: str | None = None,
    ) -> ActionResult:
        if safety_service.status().emergency_stop:
            return ActionResult(action_id='rollback', success=False, error='Rollback blocked: emergency stop is active')
        result = await self._desktop_engine.apply_rollback(
            backup_path=backup_path,
            target_path=target_path,
            delete_target=delete_target,
            approved=True,
        )
        await event_bus.publish(EventMessage(type='rollback_result', payload=result.model_dump(mode='json')))
        return result

    async def _start_worker(self, task_id: str) -> None:
        async with self._lock:
            runtime = self._load_runtime(task_id)
            if runtime.active_worker and not runtime.active_worker.done():
                return
            runtime.active_worker = asyncio.create_task(self._run_task(task_id))
            self._runtime[task_id] = runtime

    def _load_runtime(self, task_id: str) -> RuntimeState:
        runtime = self._runtime.get(task_id)
        if runtime:
            return runtime

        snapshot = repositories['runtime'].get(task_id)
        if snapshot:
            return RuntimeState(
                actions=snapshot.actions,
                next_action_index=snapshot.next_action_index,
                pending_steps=snapshot.pending_steps,
                replan_attempts=snapshot.replan_attempts,
            )
        return RuntimeState()

    def _save_runtime(self, task_id: str, runtime: RuntimeState) -> None:
        repositories['runtime'].save(runtime.to_snapshot(task_id))

    def _clear_runtime(self, task_id: str) -> None:
        repositories['runtime'].delete(task_id)
        self._runtime.pop(task_id, None)

    async def _run_task(self, task_id: str) -> None:
        runtime = self._load_runtime(task_id)
        self._runtime[task_id] = runtime
        async with self._worker_semaphore:
            try:
                record = repositories['tasks'].get(task_id)
                if not record:
                    return

                record.status = TaskStatus.running
                record.updated_at = datetime.now(timezone.utc)
                repositories['tasks'].save(record)
                await event_bus.publish(
                    EventMessage(type='task_status', payload={'task_id': task_id, 'status': record.status.value}),
                    task_id=task_id,
                )

                if not runtime.actions:
                    try:
                        plan = planner_service.build_plan(record.spec)
                    except ProviderExhaustedError as exc:
                        record.status = TaskStatus.paused_quota
                        record.last_error = str(exc)
                        record.updated_at = datetime.now(timezone.utc)
                        repositories['tasks'].save(record)
                        self._save_runtime(task_id, runtime)
                        await event_bus.publish(
                            EventMessage(
                                type='task_status',
                                payload={'task_id': task_id, 'status': record.status.value, 'reason': str(exc)},
                            ),
                            task_id=task_id,
                        )
                        return

                    runtime.pending_steps = [step.description for step in plan.steps]
                    runtime.actions = [action for step in plan.steps for action in step.actions]
                    if not runtime.actions:
                        record.status = TaskStatus.failed
                        record.last_error = 'Planner produced no executable actions for this objective'
                        record.updated_at = datetime.now(timezone.utc)
                        repositories['tasks'].save(record)
                        metrics_service.inc('tasks_failed')
                        self._remember_task_outcome(record, status='failed', reason=record.last_error)
                        await event_bus.publish(
                            EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                            task_id=task_id,
                        )
                        return

                    verification = plan_verifier_service.verify_actions(runtime.actions)
                    if verification.get('blocked', 0) > 0:
                        record.status = TaskStatus.failed
                        record.last_error = f'Plan verifier blocked {verification.get("blocked", 0)} action(s)'
                        record.updated_at = datetime.now(timezone.utc)
                        repositories['tasks'].save(record)
                        metrics_service.inc('tasks_failed')
                        self._save_runtime(task_id, runtime)
                        self._remember_task_outcome(record, status='failed', reason=record.last_error)
                        await event_bus.publish(
                            EventMessage(
                                type='task_failed',
                                payload={
                                    'task_id': task_id,
                                    'reason': record.last_error,
                                    'verification': verification,
                                },
                            ),
                            task_id=task_id,
                        )
                        return

                    # Add deliberation traces as a quality layer on top of structured plan output.
                    try:
                        deliberation = agent_mesh.deliberate(record.spec)
                    except ProviderExhaustedError:
                        deliberation = None
                    if deliberation:
                        for trace in deliberation.traces:
                            repositories['traces'].save(trace)
                            record.trace_ids.append(trace.id)
                    self._save_runtime(task_id, runtime)
                    world_state_service.update(
                        task_id,
                        {
                            'phase': 'deliberation',
                            'strategy': plan.strategy,
                            'planned_steps': [step.title for step in plan.steps],
                            'planned_actions': [a.action.value for a in runtime.actions],
                            'pending_steps': runtime.pending_steps,
                        },
                    )

                    repositories['checkpoints'].save(
                        Checkpoint(
                            task_id=task_id,
                            phase='deliberation_completed',
                            memory_ref='agent_mesh',
                            pending_steps=runtime.pending_steps,
                        )
                    )
                    repositories['tasks'].save(record)

                    await event_bus.publish(
                        EventMessage(
                            type='deliberation_ready',
                            payload={'task_id': task_id, 'actions': [a.model_dump(mode='json') for a in runtime.actions]},
                        ),
                        task_id=task_id,
                    )

                while True:
                    latest = repositories['tasks'].get(task_id)
                    if latest and latest.status == TaskStatus.cancelled:
                        self._save_runtime(task_id, runtime)
                        return

                    if safety_service.status().emergency_stop:
                        record.status = TaskStatus.failed
                        record.last_error = f"Emergency stop active: {safety_service.status().reason or 'No reason provided'}"
                        record.updated_at = datetime.now(timezone.utc)
                        repositories['tasks'].save(record)
                        metrics_service.inc('tasks_failed')
                        self._save_runtime(task_id, runtime)
                        self._remember_task_outcome(record, status='failed', reason=record.last_error or '')
                        await event_bus.publish(
                            EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                            task_id=task_id,
                        )
                        return

                    if runtime.next_action_index >= len(runtime.actions):
                        if runtime.pending_steps and runtime.replan_attempts < settings.max_replan_attempts:
                            last_result = ActionResult(action_id='replan-context', success=True, output={'pending': runtime.pending_steps})
                            runtime.replan_attempts += 1
                            next_actions = agent_mesh.replan(record.spec, runtime.pending_steps, last_result)
                            if not next_actions:
                                break
                            runtime.actions.extend(next_actions)
                            self._save_runtime(task_id, runtime)
                            continue
                        break

                    action = runtime.actions[runtime.next_action_index]
                    risk = risk_engine.evaluate(action)
                    action.risk_score = risk.risk_score
                    action.requires_approval = risk.requires_approval

                    if risk.requires_approval:
                        record.status = TaskStatus.waiting_approval
                        record.updated_at = datetime.now(timezone.utc)
                        repositories['tasks'].save(record)

                        approval = ApprovalRequest(
                            task_id=task_id,
                            action_id=action.id,
                            action=action.action,
                            reason='Risk policy requires explicit user approval.',
                            impact='This action may modify system/app/files.',
                            rollback='Execution logs include rollback notes where possible.',
                        )
                        await approval_service.create(approval)
                        metrics_service.inc('approvals_requested')

                        await event_bus.publish(
                            EventMessage(
                                type='task_status',
                                payload={
                                    'task_id': task_id,
                                    'status': record.status.value,
                                    'approval_id': approval.id,
                                    'action_id': action.id,
                                    'risk_score': risk.risk_score,
                                },
                            ),
                            task_id=task_id,
                        )

                        decided = await approval_service.wait_for_decision(approval.id, timeout_seconds=settings.approval_timeout_seconds)
                        if not decided:
                            record.status = TaskStatus.failed
                            record.last_error = 'Approval timed out'
                            record.updated_at = datetime.now(timezone.utc)
                            repositories['tasks'].save(record)
                            metrics_service.inc('tasks_failed')
                            self._save_runtime(task_id, runtime)
                            self._remember_task_outcome(record, status='failed', reason=record.last_error)
                            await event_bus.publish(
                                EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                                task_id=task_id,
                            )
                            return

                        if decided.status != 'APPROVED':
                            metrics_service.inc('approvals_rejected')
                            record.status = TaskStatus.failed
                            record.last_error = 'Action rejected by user approval'
                            record.updated_at = datetime.now(timezone.utc)
                            repositories['tasks'].save(record)
                            metrics_service.inc('tasks_failed')
                            self._save_runtime(task_id, runtime)
                            self._remember_task_outcome(record, status='failed', reason=record.last_error)
                            await event_bus.publish(
                                EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                                task_id=task_id,
                            )
                            return

                        record.status = TaskStatus.running
                        record.updated_at = datetime.now(timezone.utc)
                        repositories['tasks'].save(record)

                    result = await self._desktop_engine.execute(action)
                    await event_bus.publish(
                        EventMessage(type='action_result', payload=result.model_dump(mode='json')),
                        task_id=task_id,
                    )
                    world_state_service.update(
                        task_id,
                        {
                            'last_action_id': action.id,
                            'last_action': action.action.value,
                            'last_action_success': result.success,
                            'last_action_error': result.error or '',
                            'last_action_output': result.output,
                            'pending_steps': runtime.pending_steps,
                        },
                    )

                    if result.success:
                        if runtime.pending_steps:
                            runtime.pending_steps = runtime.pending_steps[1:]
                        runtime.next_action_index += 1
                        self._save_runtime(task_id, runtime)
                        repositories['checkpoints'].save(
                            Checkpoint(
                                task_id=task_id,
                                phase=f'action_{runtime.next_action_index}',
                                memory_ref=action.id,
                                pending_steps=runtime.pending_steps,
                            )
                        )
                        continue

                    # Failure path with limited replan recovery attempts.
                    if runtime.replan_attempts < settings.max_replan_attempts:
                        runtime.replan_attempts += 1
                        recovery_actions = agent_mesh.replan(record.spec, runtime.pending_steps, result)
                        if recovery_actions:
                            runtime.actions.extend(recovery_actions)
                            runtime.next_action_index += 1
                            self._save_runtime(task_id, runtime)
                            continue

                    record.status = TaskStatus.failed
                    record.last_error = result.error or 'Action execution failed'
                    record.updated_at = datetime.now(timezone.utc)
                    repositories['tasks'].save(record)
                    metrics_service.inc('tasks_failed')
                    self._save_runtime(task_id, runtime)
                    self._remember_task_outcome(record, status='failed', reason=record.last_error or '')
                    await event_bus.publish(
                        EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                        task_id=task_id,
                    )
                    return

                latest = repositories['tasks'].get(task_id)
                if latest and latest.status == TaskStatus.cancelled:
                    self._save_runtime(task_id, runtime)
                    return

                record.status = TaskStatus.completed
                record.updated_at = datetime.now(timezone.utc)
                repositories['tasks'].save(record)
                metrics_service.inc('tasks_completed')
                self._clear_runtime(task_id)
                self._remember_task_outcome(record, status='completed', reason='')

                repositories['checkpoints'].save(
                    Checkpoint(task_id=task_id, phase='completed', memory_ref='task_done', pending_steps=[])
                )
                await event_bus.publish(
                    EventMessage(type='task_completed', payload={'task_id': task_id}),
                    task_id=task_id,
                )
                world_state_service.update(task_id, {'phase': 'completed', 'status': 'COMPLETED', 'pending_steps': []})
            except asyncio.CancelledError:
                latest = repositories['tasks'].get(task_id)
                reason = 'Task cancelled'
                if latest:
                    if latest.status != TaskStatus.cancelled:
                        latest.status = TaskStatus.cancelled
                        latest.last_error = reason
                        latest.updated_at = datetime.now(timezone.utc)
                        repositories['tasks'].save(latest)
                    elif latest.last_error:
                        reason = latest.last_error
                    self._remember_task_outcome(latest, status='cancelled', reason=reason)
                self._save_runtime(task_id, runtime)
                await event_bus.publish(
                    EventMessage(type='task_cancelled', payload={'task_id': task_id, 'reason': reason}),
                    task_id=task_id,
                )
                world_state_service.update(task_id, {'phase': 'cancelled', 'status': 'CANCELLED', 'reason': reason})
                return

    @staticmethod
    def _remember_task_outcome(record: TaskRecord, status: str, reason: str) -> None:
        key = f'task:{record.spec.id}:outcome'
        content = (
            f'Objective={record.spec.objective}\n'
            f'Status={status}\n'
            f'Reason={reason}\n'
            f'Constraints={record.spec.constraints}'
        )
        tags = ['task', status] + [str(item).lower() for item in record.spec.constraints[:4]]
        memory_service.upsert(key=key, content=content, tags=tags)

    @staticmethod
    def _summary(record: TaskRecord | None) -> TaskSummary | None:
        if not record:
            return None
        return TaskSummary(
            id=record.spec.id,
            status=record.status,
            objective=record.spec.objective,
            created_at=record.spec.created_at,
            updated_at=record.updated_at,
            last_error=record.last_error,
        )


orchestrator = TaskOrchestrator()
