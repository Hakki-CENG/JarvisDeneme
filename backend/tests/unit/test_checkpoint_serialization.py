from app.models.schemas import Checkpoint


def test_checkpoint_roundtrip() -> None:
    checkpoint = Checkpoint(task_id='task-1', phase='action_1', memory_ref='mem-1', pending_steps=['a', 'b'])

    payload = checkpoint.model_dump(mode='json')
    restored = Checkpoint.model_validate(payload)

    assert restored.task_id == checkpoint.task_id
    assert restored.pending_steps == ['a', 'b']
