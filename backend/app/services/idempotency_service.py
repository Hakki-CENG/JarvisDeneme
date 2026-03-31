from __future__ import annotations

from datetime import datetime, timezone

from app.services.storage import store


class IdempotencyService:
    def get_task_id(self, idempotency_key: str) -> str | None:
        with store.conn() as conn:
            row = conn.execute(
                'SELECT task_id FROM idempotency_keys WHERE idempotency_key = ?',
                (idempotency_key,),
            ).fetchone()
        return row[0] if row else None

    def bind(self, idempotency_key: str, task_id: str) -> None:
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO idempotency_keys (idempotency_key, task_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET task_id=excluded.task_id
                ''',
                (idempotency_key, task_id, datetime.now(timezone.utc).isoformat()),
            )


idempotency_service = IdempotencyService()
