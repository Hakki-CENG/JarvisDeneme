from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.services.storage import store


class WorldStateService:
    def update(self, task_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get(task_id)
        merged = {**current, **patch, 'updated_at': datetime.now(timezone.utc).isoformat()}
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO world_states (task_id, updated_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                ''',
                (
                    task_id,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(merged, ensure_ascii=True),
                ),
            )
        return merged

    def get(self, task_id: str) -> dict[str, Any]:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM world_states WHERE task_id = ?', (task_id,)).fetchone()
        if not row:
            return {}
        return json.loads(row[0])


world_state_service = WorldStateService()
