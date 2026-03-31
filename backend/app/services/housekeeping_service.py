from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.settings import settings
from app.services.storage import store


class HousekeepingService:
    def cleanup(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        idem_cutoff = (now - timedelta(hours=settings.idempotency_ttl_hours)).isoformat()
        event_cutoff = (now - timedelta(days=settings.event_retention_days)).isoformat()

        removed_idempotency = 0
        removed_events = 0
        with store.conn() as conn:
            removed_idempotency = conn.execute(
                'DELETE FROM idempotency_keys WHERE created_at < ?',
                (idem_cutoff,),
            ).rowcount
            removed_events = conn.execute(
                'DELETE FROM events WHERE created_at < ?',
                (event_cutoff,),
            ).rowcount

        return {'idempotency_removed': removed_idempotency, 'events_removed': removed_events}


housekeeping_service = HousekeepingService()
