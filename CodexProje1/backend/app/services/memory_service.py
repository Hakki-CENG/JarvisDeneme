from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.models.schemas import MemoryEntry
from app.services.storage import store


class MemoryService:
    def upsert(self, key: str, content: str, tags: Iterable[str] | None = None) -> MemoryEntry:
        now = datetime.now(timezone.utc)
        normalized_tags = sorted({tag.strip().lower() for tag in (tags or []) if tag.strip()})

        with store.conn() as conn:
            existing = conn.execute(
                'SELECT payload FROM memory_entries WHERE memory_key = ?',
                (key,),
            ).fetchone()

        if existing:
            item = MemoryEntry.model_validate(store.load(existing[0]))
            item.content = content
            item.tags = normalized_tags
            item.updated_at = now
        else:
            item = MemoryEntry(
                key=key,
                content=content,
                tags=normalized_tags,
                created_at=now,
                updated_at=now,
            )

        payload = item.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO memory_entries (id, memory_key, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(memory_key) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                ''',
                (
                    item.id,
                    item.key,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                    store.dump(payload),
                ),
            )
        return item

    def recent(self, limit: int = 20) -> list[MemoryEntry]:
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM memory_entries ORDER BY updated_at DESC LIMIT ?',
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [MemoryEntry.model_validate(store.load(row[0])) for row in rows]

    def search(self, query: str, limit: int = 8) -> list[MemoryEntry]:
        q = query.strip().lower()
        if not q:
            return self.recent(limit=limit)

        tokens = [token for token in q.replace(',', ' ').split() if token]
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM memory_entries ORDER BY updated_at DESC LIMIT 500'
            ).fetchall()

        scored: list[MemoryEntry] = []
        for row in rows:
            item = MemoryEntry.model_validate(store.load(row[0]))
            haystack = f'{item.key} {item.content} {" ".join(item.tags)}'.lower()
            score = 0.0
            for token in tokens:
                if token in haystack:
                    score += 1.0
            if q in haystack:
                score += 2.0
            if score > 0:
                item.score = score
                scored.append(item)

        scored.sort(key=lambda x: (x.score, x.updated_at), reverse=True)
        return scored[: max(1, min(limit, 100))]


memory_service = MemoryService()
