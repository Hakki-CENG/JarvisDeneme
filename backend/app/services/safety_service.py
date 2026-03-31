from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SafetyState:
    emergency_stop: bool = False
    reason: str = ''
    updated_at: str = datetime.now(timezone.utc).isoformat()


class SafetyService:
    def __init__(self) -> None:
        self._state = SafetyState()

    def trigger_emergency_stop(self, reason: str) -> SafetyState:
        self._state.emergency_stop = True
        self._state.reason = reason
        self._state.updated_at = datetime.now(timezone.utc).isoformat()
        return self._state

    def clear_emergency_stop(self) -> SafetyState:
        self._state.emergency_stop = False
        self._state.reason = ''
        self._state.updated_at = datetime.now(timezone.utc).isoformat()
        return self._state

    def status(self) -> SafetyState:
        return self._state


safety_service = SafetyService()
