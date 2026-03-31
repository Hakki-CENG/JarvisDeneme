from app.models.schemas import ActionEnvelope, ActionType
from app.services.task_orchestrator import RuntimeState, TaskOrchestrator


def _wait_action() -> ActionEnvelope:
    return ActionEnvelope(task_id='task-runtime-test', action=ActionType.wait, parameters={'seconds': 1})


def test_recovery_actions_inserted_before_remaining_queue() -> None:
    first = _wait_action()
    second = _wait_action()
    recovery = _wait_action()
    runtime = RuntimeState(
        actions=[first, second],
        next_action_index=0,
        pending_steps=['step-1'],
        step_action_counts=[2],
    )

    TaskOrchestrator._insert_recovery_actions(runtime, [recovery])  # noqa: SLF001

    assert runtime.next_action_index == 1
    assert runtime.actions[1].id == recovery.id
    assert runtime.actions[2].id == second.id


def test_record_success_advances_step_after_required_actions() -> None:
    runtime = RuntimeState(
        actions=[_wait_action(), _wait_action()],
        next_action_index=0,
        pending_steps=['step-1'],
        step_action_counts=[2],
        current_step_index=0,
        completed_actions_in_current_step=0,
    )

    TaskOrchestrator._record_success(runtime)  # noqa: SLF001
    assert runtime.pending_steps == ['step-1']

    TaskOrchestrator._record_success(runtime)  # noqa: SLF001
    assert runtime.pending_steps == []
    assert runtime.current_step_index == 1
