from __future__ import annotations

from threading import Lock

from app.models.schemas import MetricSnapshot, utcnow


class MetricsService:
    def __init__(self) -> None:
        self._snapshot = MetricSnapshot()
        self._lock = Lock()

    def inc(self, field: str, by: int = 1) -> None:
        with self._lock:
            current = getattr(self._snapshot, field, 0)
            setattr(self._snapshot, field, current + by)
            self._snapshot.updated_at = utcnow()

    def get(self) -> MetricSnapshot:
        with self._lock:
            return MetricSnapshot.model_validate(self._snapshot.model_dump(mode='json'))


metrics_service = MetricsService()
