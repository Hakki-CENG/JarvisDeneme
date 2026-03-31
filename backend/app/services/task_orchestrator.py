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
from app.services.execution_report_service import execution_report_service
from app.services.memory_service import memory_service
from app.services.metrics_service import metrics_service
from app.services.mission_service import mission_service
from app.services.model_router import ProviderExhaustedError
from app.services.plan_verifier_service import plan_verifier_service
from app.services.planner_service import planner_service
from app.services.repositories import repositories
from app.services.risk_engine import risk_engine
from app.services.rollback_service import rollback_service
from app.services.safety_service import safety_service
from app.services.world_state_service import world_state_service


@dataclass
class RuntimeState:
    actions: list[ActionEnvelope] = field(default_factory=list)
    next_action_index: int = 0
    pending_steps: list[str] = field(default_factory=list)
    step_action_counts: list[int] = field(default_factory=list)
    current_step_index: int = 0
    completed_actions_in_current_step: int = 0
    replan_attempts: int = 0
    active_worker: asyncio.Task | None = None

    def to_snapshot(self, task_id: str) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            task_id=task_id,
            actions=self.actions,
            next_action_index=self.next_action_index,
            pending_steps=self.pending_steps,
            step_action_counts=self.step_action_counts,
            current_step_index=self.current_step_index,
            completed_actions_in_current_step=self.completed_actions_in_current_step,
            replan_attempts=self.replan_attempts,
            updated_at=datetime.now(timezone.utc),
        )


class TaskOrchestrator:
    _ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.pending: {TaskStatus.running, TaskStatus.failed, TaskStatus.cancelled, TaskStatus.paused_quota},
        TaskStatus.running: {
            TaskStatus.running,
            TaskStatus.waiting_approval,
            TaskStatus.paused_quota,
            TaskStatus.failed,
            TaskStatus.cancelled,
            TaskStatus.completed,
        },
        TaskStatus.waiting_approval: {TaskStatus.running, TaskStatus.failed, TaskStatus.cancelled},
        TaskStatus.paused_quota: {TaskStatus.running, TaskStatus.failed, TaskStatus.cancelled},
        TaskStatus.failed: {TaskStatus.running, TaskStatus.cancelled},
        TaskStatus.cancelled: {TaskStatus.running},
        TaskStatus.completed: {TaskStatus.running},
    }

    def __init__(self) -> None:
        self._desktop_engine = build_desktop_engine()
        self._runtime: dict[str, RuntimeState] = {}
        self._lock = asyncio.Lock()
        self._worker_semaphore = asyncio.Semaphore(max(1, settings.max_parallel_workers))
        self._dispatcher_task: asyncio.Task | None = None
        self._dispatcher_wakeup = asyncio.Event()

    async def create_task(self, request: TaskCreateRequest) -> TaskSummary:
        spec = TaskSpec(
            objective=request.objective,
            constraints=request.constraints,
            tools_allowed=request.tools_allowed,
            priority=request.priority,
        )
        record = TaskRecord(spec=spec)
        repositories['tasks'].save(record)
        repositories['task_state_transitions'].record(
            task_id=spec.id,
            from_status=None,
            to_status=TaskStatus.pending.value,
            reason='task_created',
        )
        metrics_service.inc('tasks_created')
        audit_service.log(actor='system', action='task_created', details=f'task_id={spec.id} objective={spec.objective[:160]}')

        await event_bus.publish(
            EventMessage(type='task_created', payload={'task_id': spec.id, 'objective': spec.objective}),
            task_id=spec.id,
        )

        self.start_dispatcher()
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
        self.start_dispatcher()
        tasks = repositories['tasks'].list_all()
        for task in tasks:
            if task.status in {TaskStatus.pending, TaskStatus.running, TaskStatus.waiting_approval, TaskStatus.paused_quota}:
                await self._start_worker(task.spec.id)

    async def resume_task(self, task_id: str, request: ResumeRequest) -> TaskSummary | None:
        record = repositories['tasks'].get(task_id)
        if not record:
            return None
        if safety_service.status().emergency_stop:
            error_text = f"Cannot resume while emergency stop is active: {safety_service.status().reason or 'no reason'}"
            self._transition_task(record, TaskStatus.failed, error_text)
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

        self._transition_task(record, TaskStatus.cancelled, reason)
        repositories['task_queue'].remove(task_id)
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
            self._runtime[task_id] = runtime
            task = repositories['tasks'].get(task_id)
            priority = task.spec.priority if task else 5
            repositories['task_queue'].enqueue(task_id=task_id, priority=priority)
            self._dispatcher_wakeup.set()

    def start_dispatcher(self) -> None:
        if self._dispatcher_task and not self._dispatcher_task.done():
            return
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self) -> None:
        while True:
            task_id = repositories['task_queue'].dequeue_next(aging_seconds=120)
            if not task_id:
                self._dispatcher_wakeup.clear()
                try:
                    await asyncio.wait_for(self._dispatcher_wakeup.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                continue
            runtime = self._load_runtime(task_id)
            if runtime.active_worker and not runtime.active_worker.done():
                continue
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
                step_action_counts=snapshot.step_action_counts,
                current_step_index=snapshot.current_step_index,
                completed_actions_in_current_step=snapshot.completed_actions_in_current_step,
                replan_attempts=snapshot.replan_attempts,
            )
        return RuntimeState()

    def _save_runtime(self, task_id: str, runtime: RuntimeState) -> None:
        repositories['runtime'].save(runtime.to_snapshot(task_id))

    def _clear_runtime(self, task_id: str) -> None:
        repositories['runtime'].delete(task_id)
        self._runtime.pop(task_id, None)

    @staticmethod
    def _seed_runtime_from_plan(runtime: RuntimeState, plan) -> list[str]:
        runtime.actions = []
        runtime.pending_steps = []
        runtime.step_action_counts = []
        runtime.current_step_index = 0
        runtime.completed_actions_in_current_step = 0
        runtime.next_action_index = 0
        runtime.replan_attempts = 0

        planned_step_titles: list[str] = []
        for step in plan.steps:
            if not step.actions:
                continue
            runtime.actions.extend(step.actions)
            runtime.pending_steps.append(step.description)
            runtime.step_action_counts.append(len(step.actions))
            planned_step_titles.append(step.title)
        return planned_step_titles

    @staticmethod
    def _advance_completed_steps(runtime: RuntimeState) -> None:
        while runtime.current_step_index < len(runtime.step_action_counts):
            required = runtime.step_action_counts[runtime.current_step_index]
            if runtime.completed_actions_in_current_step < required:
                break
            runtime.completed_actions_in_current_step -= required
            runtime.current_step_index += 1
            if runtime.pending_steps:
                runtime.pending_steps.pop(0)

        if runtime.current_step_index >= len(runtime.step_action_counts):
            runtime.completed_actions_in_current_step = 0

    @staticmethod
    def _record_success(runtime: RuntimeState) -> None:
        runtime.next_action_index += 1
        if runtime.current_step_index < len(runtime.step_action_counts):
            runtime.completed_actions_in_current_step += 1
        TaskOrchestrator._advance_completed_steps(runtime)

    @staticmethod
    def _sync_runtime_progress(runtime: RuntimeState) -> None:
        runtime.next_action_index = max(0, min(runtime.next_action_index, len(runtime.actions)))
        if runtime.step_action_counts:
            runtime.current_step_index = max(0, min(runtime.current_step_index, len(runtime.step_action_counts)))
            if runtime.current_step_index >= len(runtime.step_action_counts):
                runtime.completed_actions_in_current_step = 0
            return

        if runtime.actions:
            remaining = max(1, len(runtime.actions) - runtime.next_action_index)
            runtime.step_action_counts = [remaining]
            runtime.current_step_index = 0
            runtime.completed_actions_in_current_step = 0

    @staticmethod
    def _append_replan_actions(runtime: RuntimeState, actions: list[ActionEnvelope]) -> None:
        if not actions:
            return
        runtime.actions.extend(actions)
        if runtime.current_step_index >= len(runtime.step_action_counts):
            runtime.step_action_counts.append(len(actions))

    @staticmethod
    def _insert_recovery_actions(runtime: RuntimeState, recovery_actions: list[ActionEnvelope]) -> None:
        if not recovery_actions:
            return
        insert_at = runtime.next_action_index + 1
        runtime.actions[insert_at:insert_at] = recovery_actions
        runtime.next_action_index += 1

    @staticmethod
    def _is_mutating_action(action: ActionEnvelope) -> bool:
        if action.action.value != 'file_ops':
            return False
        op = str(action.parameters.get('op', '')).lower()
        return op in {'write', 'delete', 'remove', 'move', 'rename'}

    def _transition_task(self, record: TaskRecord, to_status: TaskStatus, reason: str = '') -> bool:
        from_status = record.status
        if from_status == to_status:
            record.updated_at = datetime.now(timezone.utc)
            if reason:
                record.last_error = reason
            elif to_status in {TaskStatus.running, TaskStatus.completed}:
                record.last_error = None
            repositories['tasks'].save(record)
            return True

        allowed = self._ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            audit_service.log(
                actor='state_machine',
                action='invalid_task_transition',
                details=(
                    f'task_id={record.spec.id} from={from_status.value} to={to_status.value} '
                    f'reason={reason[:120]}'
                ),
            )
            return False

        record.status = to_status
        record.updated_at = datetime.now(timezone.utc)
        if reason:
            record.last_error = reason
        elif to_status in {TaskStatus.running, TaskStatus.completed}:
            record.last_error = None
        repositories['tasks'].save(record)
        repositories['task_state_transitions'].record(
            task_id=record.spec.id,
            from_status=from_status.value,
            to_status=to_status.value,
            reason=reason,
        )
        return True

    async def _run_task(self, task_id: str) -> None:
        runtime = self._load_runtime(task_id)
        self._sync_runtime_progress(runtime)
        self._runtime[task_id] = runtime
        async with self._worker_semaphore:
            try:
                record = repositories['tasks'].get(task_id)
                if not record:
                    return

                self._transition_task(record, TaskStatus.running, 'worker_started')
                linked_mission = repositories['missions'].find_by_task(task_id)
                execution_report_service.start(
                    task_id=task_id,
                    mission_id=linked_mission.mission.mission_id if linked_mission else None,
                )
                await event_bus.publish(
                    EventMessage(type='task_status', payload={'task_id': task_id, 'status': record.status.value}),
                    task_id=task_id,
                )

                if not runtime.actions:
                    try:
                        plan = planner_service.build_plan(record.spec)
                    except ProviderExhaustedError as exc:
                        self._transition_task(record, TaskStatus.paused_quota, str(exc))
                        self._save_runtime(task_id, runtime)
                        await event_bus.publish(
                            EventMessage(
                                type='task_status',
                                payload={'task_id': task_id, 'status': record.status.value, 'reason': str(exc)},
                            ),
                            task_id=task_id,
                        )
                        mission_service.sync_task_status(task_id=task_id, task_status='PAUSED_QUOTA', reason=str(exc))
                        return

                    planned_step_titles = self._seed_runtime_from_plan(runtime, plan)
                    if not runtime.actions:
                        self._transition_task(record, TaskStatus.failed, 'Planner produced no executable actions for this objective')
                        metrics_service.inc('tasks_failed')
                        self._remember_task_outcome(record, status='failed', reason=record.last_error)
                        self._finalize_reporting(task_id=task_id, status='FAILED', reason=record.last_error or '')
                        await event_bus.publish(
                            EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                            task_id=task_id,
                        )
                        return

                    verification = plan_verifier_service.verify_actions(runtime.actions)
                    if verification.get('blocked', 0) > 0:
                        self._transition_task(
                            record,
                            TaskStatus.failed,
                            f'Plan verifier blocked {verification.get("blocked", 0)} action(s)',
                        )
                        metrics_service.inc('tasks_failed')
                        self._save_runtime(task_id, runtime)
                        self._remember_task_outcome(record, status='failed', reason=record.last_error)
                        self._finalize_reporting(task_id=task_id, status='FAILED', reason=record.last_error or '')
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
                            'planned_steps': planned_step_titles,
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
                        self._finalize_reporting(task_id=task_id, status='CANCELLED', reason=latest.last_error or 'Task cancelled')
                        return

                    if safety_service.status().emergency_stop:
                        self._transition_task(
                            record,
                            TaskStatus.failed,
                            f"Emergency stop active: {safety_service.status().reason or 'No reason provided'}",
                        )
                        metrics_service.inc('tasks_failed')
                        self._save_runtime(task_id, runtime)
                        self._remember_task_outcome(record, status='failed', reason=record.last_error or '')
                        self._finalize_reporting(task_id=task_id, status='FAILED', reason=record.last_error or '')
                        await event_bus.publish(
                            EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                            task_id=task_id,
                        )
                        return

                    if runtime.next_action_index >= len(runtime.actions):
                        if runtime.pending_steps and runtime.replan_attempts < settings.max_replan_attempts:
                            last_result = ActionResult(
                                action_id='replan-context',
                                success=True,
                                output={'pending': runtime.pending_steps, 'next_action_index': runtime.next_action_index},
                            )
                            runtime.replan_attempts += 1
                            next_actions = agent_mesh.replan(record.spec, runtime.pending_steps, last_result)
                            if not next_actions:
                                break
                            self._append_replan_actions(runtime, next_actions)
                            self._save_runtime(task_id, runtime)
                            continue
                        break

                    action = runtime.actions[runtime.next_action_index]
                    risk = risk_engine.evaluate(action)
                    action.risk_score = risk.risk_score
                    action.requires_approval = risk.requires_approval

                    if risk.requires_approval:
                        self._transition_task(record, TaskStatus.waiting_approval, 'approval_required')

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
                            self._transition_task(record, TaskStatus.failed, 'Approval timed out')
                            metrics_service.inc('tasks_failed')
                            self._save_runtime(task_id, runtime)
                            self._remember_task_outcome(record, status='failed', reason=record.last_error)
                            self._finalize_reporting(task_id=task_id, status='FAILED', reason=record.last_error or '')
                            await event_bus.publish(
                                EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                                task_id=task_id,
                            )
                            return

                        if decided.status != 'APPROVED':
                            metrics_service.inc('approvals_rejected')
                            self._transition_task(record, TaskStatus.failed, 'Action rejected by user approval')
                            metrics_service.inc('tasks_failed')
                            self._save_runtime(task_id, runtime)
                            self._remember_task_outcome(record, status='failed', reason=record.last_error)
                            self._finalize_reporting(task_id=task_id, status='FAILED', reason=record.last_error or '')
                            await event_bus.publish(
                                EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                                task_id=task_id,
                            )
                            return

                        self._transition_task(record, TaskStatus.running, 'approval_granted')

                    result = await self._desktop_engine.execute(action)

                    if result.success and self._is_mutating_action(action):
                        artifacts = rollback_service.register_from_action(task_id=task_id, action=action, output=result.output)
                        if not artifacts:
                            result.success = False
                            result.error = 'Mutation action missing mandatory rollback artifact metadata'
                        else:
                            result.output['_rollback_artifact_ids'] = [item.id for item in artifacts]
                    execution_report_service.record_action(task_id=task_id, action=action, result=result)
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
                        self._record_success(runtime)
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
                            self._insert_recovery_actions(runtime, recovery_actions)
                            self._save_runtime(task_id, runtime)
                            continue

                    self._transition_task(record, TaskStatus.failed, result.error or 'Action execution failed')
                    metrics_service.inc('tasks_failed')
                    self._save_runtime(task_id, runtime)
                    self._remember_task_outcome(record, status='failed', reason=record.last_error or '')
                    self._finalize_reporting(task_id=task_id, status='FAILED', reason=record.last_error or '')
                    await event_bus.publish(
                        EventMessage(type='task_failed', payload={'task_id': task_id, 'reason': record.last_error}),
                        task_id=task_id,
                    )
                    return

                latest = repositories['tasks'].get(task_id)
                if latest and latest.status == TaskStatus.cancelled:
                    self._save_runtime(task_id, runtime)
                    self._finalize_reporting(task_id=task_id, status='CANCELLED', reason=latest.last_error or 'Task cancelled')
                    return

                self._transition_task(record, TaskStatus.completed, 'completed')
                metrics_service.inc('tasks_completed')
                repositories['task_queue'].remove(task_id)
                self._clear_runtime(task_id)
                self._remember_task_outcome(record, status='completed', reason='')
                self._finalize_reporting(task_id=task_id, status='COMPLETED', reason='')

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
                        self._transition_task(latest, TaskStatus.cancelled, reason)
                    elif latest.last_error:
                        reason = latest.last_error
                    self._remember_task_outcome(latest, status='cancelled', reason=reason)
                self._finalize_reporting(task_id=task_id, status='CANCELLED', reason=reason)
                self._save_runtime(task_id, runtime)
                repositories['task_queue'].remove(task_id)
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
    def _finalize_reporting(task_id: str, status: str, reason: str = '') -> None:
        execution_report_service.finalize(task_id=task_id, status=status, reason=reason)
        mission_service.sync_task_status(task_id=task_id, task_status=status, reason=reason)

    @staticmethod
    def _summary(record: TaskRecord | None) -> TaskSummary | None:
        if not record:
            return None
        return TaskSummary(
            id=record.spec.id,
            status=record.status,
            objective=record.spec.objective,
            priority=record.spec.priority,
            created_at=record.spec.created_at,
            updated_at=record.updated_at,
            last_error=record.last_error,
        )


orchestrator = TaskOrchestrator()
