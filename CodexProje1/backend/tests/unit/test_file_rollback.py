import asyncio
from pathlib import Path

from app.models.schemas import ActionEnvelope, ActionType
from app.services.desktop.windows_engine import WindowsDesktopEngine


def test_write_operation_produces_rollback_snapshot(tmp_path: Path) -> None:
    engine = WindowsDesktopEngine()
    target = tmp_path / 'rollback_demo.txt'
    target.write_text('before', encoding='utf-8')

    action = ActionEnvelope(
        task_id='t1',
        action=ActionType.file_ops,
        parameters={'op': 'write', 'dst': str(target), 'content': 'after'},
        requires_approval=True,
    )

    result = asyncio.run(engine.execute(action))
    assert result.success is True
    backup_path = str(result.output.get('rollback_backup', ''))
    assert backup_path
    assert Path(backup_path).exists()

    rollback = asyncio.run(
        engine.apply_rollback(
            backup_path=backup_path,
            target_path=str(result.output.get('rollback_target')),
            approved=True,
        )
    )
    assert rollback.success is True
    assert target.read_text(encoding='utf-8') == 'before'
