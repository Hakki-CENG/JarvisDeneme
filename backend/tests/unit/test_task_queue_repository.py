from datetime import datetime, timedelta, timezone

from app.services.repositories import repositories
from app.services.storage import store


def test_task_queue_dequeue_with_aging_policy() -> None:
    queue = repositories['task_queue']
    with store.conn() as conn:
        conn.execute('DELETE FROM task_queue')
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        conn.execute(
            'INSERT INTO task_queue (task_id, priority, enqueued_at, attempts) VALUES (?, ?, ?, ?)',
            ('low_old', 9, old_time, 0),
        )
        conn.execute(
            'INSERT INTO task_queue (task_id, priority, enqueued_at, attempts) VALUES (?, ?, ?, ?)',
            ('high_new', 2, datetime.now(timezone.utc).isoformat(), 0),
        )

    first = queue.dequeue_next(aging_seconds=120)
    second = queue.dequeue_next(aging_seconds=120)

    assert first in {'low_old', 'high_new'}
    assert second in {'low_old', 'high_new'}
    assert first != second

