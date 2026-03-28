from __future__ import annotations

from uuid import uuid4

from app.models.schemas import EventMessage
from app.services.storage import store


class EventStoreService:
    def append(self, message: EventMessage, task_id: str | None = None) -> None:
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO events (id, task_id, created_at, payload)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    str(uuid4()),
                    task_id,
                    message.created_at.isoformat(),
                    store.dump(message.model_dump(mode='json')),
                ),
            )

    def list_recent(self, limit: int = 200, task_id: str | None = None) -> list[dict]:
        with store.conn() as conn:
            if task_id:
                rows = conn.execute(
                    'SELECT payload FROM events WHERE task_id = ? ORDER BY created_at DESC LIMIT ?',
                    (task_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT payload FROM events ORDER BY created_at DESC LIMIT ?',
                    (limit,),
                ).fetchall()
        return [store.load(row[0]) for row in rows]


# singleton

event_store_service = EventStoreService()
