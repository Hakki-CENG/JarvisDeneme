from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from app.services.storage import store


class AuditService:
    def __init__(self) -> None:
        with store.conn() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS audits (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    request_id TEXT,
                    details TEXT NOT NULL
                )
                '''
            )

    @staticmethod
    def _sanitize(details: str) -> str:
        text = details
        text = re.sub(r'(?i)(api[_-]?key|token|authorization)\\s*[:=]\\s*[^\\s,;]+', r'\\1=[REDACTED]', text)
        text = re.sub(r'Bearer\\s+[A-Za-z0-9._\\-]+', 'Bearer [REDACTED]', text)
        return text[:2000]

    def log(self, actor: str, action: str, details: str, request_id: str = '') -> None:
        sanitized = self._sanitize(details)
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO audits (id, created_at, actor, action, request_id, details)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    str(uuid4()),
                    datetime.now(timezone.utc).isoformat(),
                    actor,
                    action,
                    request_id,
                    sanitized,
                ),
            )

    def latest(self, limit: int = 50) -> list[dict[str, str]]:
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT created_at, actor, action, request_id, details FROM audits ORDER BY created_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [
            {
                'created_at': row[0],
                'actor': row[1],
                'action': row[2],
                'request_id': row[3] or '',
                'details': row[4],
            }
            for row in rows
        ]


audit_service = AuditService()
