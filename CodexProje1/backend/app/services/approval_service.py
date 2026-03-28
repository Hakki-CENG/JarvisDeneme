from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.models.schemas import ApprovalDecision, ApprovalRequest, EventMessage
from app.services.event_bus import event_bus
from app.services.repositories import repositories


class ApprovalService:
    def __init__(self) -> None:
        self._decision_events: dict[str, asyncio.Event] = {}

    async def create(self, request: ApprovalRequest) -> ApprovalRequest:
        repositories['approvals'].save(request)
        self._decision_events.setdefault(request.id, asyncio.Event())
        await event_bus.publish(
            EventMessage(type='approval_requested', payload=request.model_dump(mode='json')),
            task_id=request.task_id,
        )
        return request

    async def wait_for_decision(self, approval_id: str, timeout_seconds: int) -> ApprovalRequest | None:
        evt = self._decision_events.setdefault(approval_id, asyncio.Event())
        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout_seconds)
        except TimeoutError:
            self._decision_events.pop(approval_id, None)
            return None
        try:
            return repositories['approvals'].get(approval_id)
        finally:
            self._decision_events.pop(approval_id, None)

    async def decide(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRequest | None:
        approval = repositories['approvals'].get(approval_id)
        if not approval:
            return None

        approval.status = 'APPROVED' if decision == ApprovalDecision.approve else 'REJECTED'
        approval.decided_at = datetime.now(timezone.utc)
        repositories['approvals'].save(approval)

        evt = self._decision_events.setdefault(approval.id, asyncio.Event())
        evt.set()

        await event_bus.publish(
            EventMessage(type='approval_decided', payload=approval.model_dump(mode='json')),
            task_id=approval.task_id,
        )
        return approval

    def list_pending(self) -> list[ApprovalRequest]:
        return repositories['approvals'].list_pending()


approval_service = ApprovalService()
