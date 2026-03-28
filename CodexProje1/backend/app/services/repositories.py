from __future__ import annotations

from datetime import datetime

from app.models.schemas import (
    ApprovalRequest,
    Checkpoint,
    ExecutionTrace,
    RuntimeSnapshot,
    SelfImproveReport,
    TaskRecord,
    TaskStatus,
)
from app.services.storage import store


class TaskRepository:
    def save(self, task: TaskRecord) -> None:
        payload = task.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO tasks (id, status, objective, created_at, updated_at, payload, last_error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload,
                    last_error=excluded.last_error
                ''',
                (
                    task.spec.id,
                    task.status.value,
                    task.spec.objective,
                    task.spec.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    store.dump(payload),
                    task.last_error,
                ),
            )

    def get(self, task_id: str) -> TaskRecord | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if not row:
            return None
        return TaskRecord.model_validate(store.load(row[0]))

    def list_all(self) -> list[TaskRecord]:
        with store.conn() as conn:
            rows = conn.execute('SELECT payload FROM tasks ORDER BY created_at DESC').fetchall()
        return [TaskRecord.model_validate(store.load(r[0])) for r in rows]

    def update_status(self, task_id: str, status: TaskStatus, error: str | None = None) -> TaskRecord | None:
        task = self.get(task_id)
        if not task:
            return None
        task.status = status
        task.last_error = error
        task.updated_at = datetime.utcnow()
        self.save(task)
        return task


class ApprovalRepository:
    def save(self, approval: ApprovalRequest) -> None:
        payload = approval.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO approvals (id, task_id, action_id, status, payload, requested_at, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    payload=excluded.payload,
                    decided_at=excluded.decided_at
                ''',
                (
                    approval.id,
                    approval.task_id,
                    approval.action_id,
                    approval.status,
                    store.dump(payload),
                    approval.requested_at.isoformat(),
                    approval.decided_at.isoformat() if approval.decided_at else None,
                ),
            )

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM approvals WHERE id = ?', (approval_id,)).fetchone()
        if not row:
            return None
        return ApprovalRequest.model_validate(store.load(row[0]))

    def list_pending(self) -> list[ApprovalRequest]:
        with store.conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM approvals WHERE status = 'PENDING' ORDER BY requested_at ASC"
            ).fetchall()
        return [ApprovalRequest.model_validate(store.load(r[0])) for r in rows]


class CheckpointRepository:
    def save(self, checkpoint: Checkpoint) -> None:
        payload = checkpoint.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO checkpoints (id, task_id, created_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                ''',
                (
                    checkpoint.id,
                    checkpoint.task_id,
                    checkpoint.created_at.isoformat(),
                    store.dump(payload),
                ),
            )

    def list_by_task(self, task_id: str) -> list[Checkpoint]:
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM checkpoints WHERE task_id = ? ORDER BY created_at ASC',
                (task_id,),
            ).fetchall()
        return [Checkpoint.model_validate(store.load(r[0])) for r in rows]


class TraceRepository:
    def save(self, trace: ExecutionTrace) -> None:
        payload = trace.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO traces (id, task_id, created_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                ''',
                (
                    trace.id,
                    trace.task_id,
                    trace.created_at.isoformat(),
                    store.dump(payload),
                ),
            )

    def list_by_task(self, task_id: str) -> list[ExecutionTrace]:
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM traces WHERE task_id = ? ORDER BY created_at ASC',
                (task_id,),
            ).fetchall()
        return [ExecutionTrace.model_validate(store.load(r[0])) for r in rows]


class SelfImproveRepository:
    def save(self, report: SelfImproveReport) -> None:
        payload = report.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO reports (id, created_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                ''',
                (report.id, report.started_at.isoformat(), store.dump(payload)),
            )

    def get(self, report_id: str) -> SelfImproveReport | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM reports WHERE id = ?', (report_id,)).fetchone()
        if not row:
            return None
        return SelfImproveReport.model_validate(store.load(row[0]))


class RuntimeRepository:
    def save(self, snapshot: RuntimeSnapshot) -> None:
        payload = snapshot.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO runtime_states (task_id, updated_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                ''',
                (
                    snapshot.task_id,
                    snapshot.updated_at.isoformat(),
                    store.dump(payload),
                ),
            )

    def get(self, task_id: str) -> RuntimeSnapshot | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM runtime_states WHERE task_id = ?', (task_id,)).fetchone()
        if not row:
            return None
        return RuntimeSnapshot.model_validate(store.load(row[0]))

    def delete(self, task_id: str) -> None:
        with store.conn() as conn:
            conn.execute('DELETE FROM runtime_states WHERE task_id = ?', (task_id,))

    def list_all(self) -> list[RuntimeSnapshot]:
        with store.conn() as conn:
            rows = conn.execute('SELECT payload FROM runtime_states ORDER BY updated_at DESC').fetchall()
        return [RuntimeSnapshot.model_validate(store.load(r[0])) for r in rows]


repositories = {
    'tasks': TaskRepository(),
    'approvals': ApprovalRepository(),
    'checkpoints': CheckpointRepository(),
    'traces': TraceRepository(),
    'self_improve': SelfImproveRepository(),
    'runtime': RuntimeRepository(),
}
