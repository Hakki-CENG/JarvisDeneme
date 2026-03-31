from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.schemas import (
    ApprovalRequest,
    Checkpoint,
    ExecutionReport,
    ExecutionTrace,
    ImprovementProposalV2,
    MissionRecord,
    RollbackArtifact,
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


class MissionRepository:
    def save(self, mission: MissionRecord) -> None:
        payload = mission.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO missions (id, status, task_id, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    task_id=excluded.task_id,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                ''',
                (
                    mission.mission.mission_id,
                    mission.status,
                    mission.task_id,
                    mission.mission.created_at.isoformat(),
                    mission.updated_at.isoformat(),
                    store.dump(payload),
                ),
            )

    def get(self, mission_id: str) -> MissionRecord | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM missions WHERE id = ?', (mission_id,)).fetchone()
        if not row:
            return None
        return MissionRecord.model_validate(store.load(row[0]))

    def list_all(self) -> list[MissionRecord]:
        with store.conn() as conn:
            rows = conn.execute('SELECT payload FROM missions ORDER BY created_at DESC').fetchall()
        return [MissionRecord.model_validate(store.load(r[0])) for r in rows]

    def find_by_task(self, task_id: str) -> MissionRecord | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM missions WHERE task_id = ? ORDER BY updated_at DESC LIMIT 1', (task_id,)).fetchone()
        if not row:
            return None
        return MissionRecord.model_validate(store.load(row[0]))


class ExecutionReportRepository:
    def save(self, report: ExecutionReport) -> None:
        payload = report.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO execution_reports (id, task_id, mission_id, created_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                ''',
                (
                    report.id,
                    report.task_id,
                    report.mission_id,
                    report.started_at.isoformat(),
                    store.dump(payload),
                ),
            )

    def get(self, report_id: str) -> ExecutionReport | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM execution_reports WHERE id = ?', (report_id,)).fetchone()
        if not row:
            return None
        return ExecutionReport.model_validate(store.load(row[0]))

    def get_by_task(self, task_id: str) -> ExecutionReport | None:
        with store.conn() as conn:
            row = conn.execute(
                'SELECT payload FROM execution_reports WHERE task_id = ? ORDER BY created_at DESC LIMIT 1',
                (task_id,),
            ).fetchone()
        if not row:
            return None
        return ExecutionReport.model_validate(store.load(row[0]))

    def list_recent(self, limit: int = 50) -> list[ExecutionReport]:
        with store.conn() as conn:
            rows = conn.execute('SELECT payload FROM execution_reports ORDER BY created_at DESC LIMIT ?', (max(1, min(limit, 200)),)).fetchall()
        return [ExecutionReport.model_validate(store.load(r[0])) for r in rows]

    def list_by_mission(self, mission_id: str, limit: int = 50) -> list[ExecutionReport]:
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM execution_reports WHERE mission_id = ? ORDER BY created_at DESC LIMIT ?',
                (mission_id, max(1, min(limit, 200))),
            ).fetchall()
        return [ExecutionReport.model_validate(store.load(r[0])) for r in rows]


class RollbackArtifactRepository:
    def save(self, artifact: RollbackArtifact) -> None:
        payload = artifact.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO rollback_artifacts (id, task_id, action_id, created_at, applied_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    applied_at=excluded.applied_at,
                    payload=excluded.payload
                ''',
                (
                    artifact.id,
                    artifact.task_id,
                    artifact.action_id,
                    artifact.created_at.isoformat(),
                    artifact.applied_at.isoformat() if artifact.applied_at else None,
                    store.dump(payload),
                ),
            )

    def get(self, artifact_id: str) -> RollbackArtifact | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM rollback_artifacts WHERE id = ?', (artifact_id,)).fetchone()
        if not row:
            return None
        return RollbackArtifact.model_validate(store.load(row[0]))

    def list(self, task_id: str | None = None, include_applied: bool = False, limit: int = 100) -> list[RollbackArtifact]:
        query = 'SELECT payload FROM rollback_artifacts'
        params: list[object] = []
        where: list[str] = []
        if task_id:
            where.append('task_id = ?')
            params.append(task_id)
        if not include_applied:
            where.append('applied_at IS NULL')
        if where:
            query += ' WHERE ' + ' AND '.join(where)
        query += ' ORDER BY created_at DESC LIMIT ?'
        params.append(max(1, min(limit, 500)))
        with store.conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [RollbackArtifact.model_validate(store.load(r[0])) for r in rows]

    def list_by_task(self, task_id: str) -> list[RollbackArtifact]:
        return self.list(task_id=task_id, include_applied=True, limit=500)


class ImprovementProposalRepository:
    def save(self, proposal: ImprovementProposalV2) -> None:
        payload = proposal.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO improvement_proposals (id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                ''',
                (
                    proposal.id,
                    proposal.status,
                    proposal.created_at.isoformat(),
                    proposal.updated_at.isoformat(),
                    store.dump(payload),
                ),
            )

    def get(self, proposal_id: str) -> ImprovementProposalV2 | None:
        with store.conn() as conn:
            row = conn.execute('SELECT payload FROM improvement_proposals WHERE id = ?', (proposal_id,)).fetchone()
        if not row:
            return None
        return ImprovementProposalV2.model_validate(store.load(row[0]))

    def list_recent(self, limit: int = 100) -> list[ImprovementProposalV2]:
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM improvement_proposals ORDER BY updated_at DESC LIMIT ?',
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [ImprovementProposalV2.model_validate(store.load(r[0])) for r in rows]


class TaskQueueRepository:
    def enqueue(self, task_id: str, priority: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO task_queue (task_id, priority, enqueued_at, attempts)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(task_id) DO UPDATE SET
                    priority=MIN(task_queue.priority, excluded.priority),
                    enqueued_at=MIN(task_queue.enqueued_at, excluded.enqueued_at)
                ''',
                (task_id, max(1, min(priority, 10)), now),
            )

    def dequeue_next(self, aging_seconds: int = 120) -> str | None:
        with store.conn() as conn:
            rows = conn.execute('SELECT task_id, priority, enqueued_at FROM task_queue').fetchall()
            if not rows:
                return None

            now = datetime.now(timezone.utc)
            ranked: list[tuple[int, str, str]] = []
            for task_id, priority, enqueued_at in rows:
                try:
                    queued_at = datetime.fromisoformat(enqueued_at)
                except Exception:
                    queued_at = now
                age = max((now - queued_at).total_seconds(), 0.0)
                aging_bonus = int(age // max(1, aging_seconds))
                effective_priority = max(1, int(priority) - aging_bonus)
                ranked.append((effective_priority, str(enqueued_at), str(task_id)))

            ranked.sort(key=lambda item: (item[0], item[1], item[2]))
            selected_id = ranked[0][2]
            conn.execute('DELETE FROM task_queue WHERE task_id = ?', (selected_id,))
            return selected_id

    def remove(self, task_id: str) -> None:
        with store.conn() as conn:
            conn.execute('DELETE FROM task_queue WHERE task_id = ?', (task_id,))

    def list_all(self) -> list[dict[str, str | int | float]]:
        with store.conn() as conn:
            rows = conn.execute('SELECT task_id, priority, enqueued_at, attempts FROM task_queue ORDER BY enqueued_at ASC').fetchall()
        now = datetime.now(timezone.utc)
        items: list[dict[str, str | int | float]] = []
        for row in rows:
            enqueued_at = str(row[2])
            try:
                queued_at = datetime.fromisoformat(enqueued_at)
                age_seconds = max((now - queued_at).total_seconds(), 0.0)
            except Exception:
                age_seconds = 0.0
            items.append(
                {
                    'task_id': str(row[0]),
                    'priority': int(row[1]),
                    'enqueued_at': enqueued_at,
                    'attempts': int(row[3]),
                    'age_seconds': age_seconds,
                }
            )
        return items


class TaskStateTransitionRepository:
    def record(self, task_id: str, from_status: str | None, to_status: str, reason: str = '') -> None:
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO task_state_transitions (id, task_id, from_status, to_status, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    str(uuid4()),
                    task_id,
                    from_status,
                    to_status,
                    reason[:600],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_by_task(self, task_id: str, limit: int = 100) -> list[dict[str, str]]:
        with store.conn() as conn:
            rows = conn.execute(
                '''
                SELECT created_at, from_status, to_status, reason
                FROM task_state_transitions
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (task_id, max(1, min(limit, 500))),
            ).fetchall()
        return [
            {'created_at': row[0], 'from_status': row[1] or '', 'to_status': row[2], 'reason': row[3] or ''}
            for row in rows
        ]


class ToolManifestRepository:
    def save(self, manifest_payload: dict, tool_name: str, version: str, promoted: bool = False) -> None:
        with store.conn() as conn:
            existing = conn.execute(
                'SELECT id FROM tool_manifests WHERE tool_name = ? AND version = ? ORDER BY created_at DESC LIMIT 1',
                (tool_name, version),
            ).fetchone()
            if existing:
                conn.execute(
                    '''
                    UPDATE tool_manifests
                    SET promoted = ?, payload = ?
                    WHERE id = ?
                    ''',
                    (1 if promoted else 0, store.dump(manifest_payload), existing[0]),
                )
            else:
                conn.execute(
                    '''
                    INSERT INTO tool_manifests (id, tool_name, version, promoted, created_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        str(uuid4()),
                        tool_name,
                        version,
                        1 if promoted else 0,
                        datetime.now(timezone.utc).isoformat(),
                        store.dump(manifest_payload),
                    ),
                )
            if promoted:
                conn.execute(
                    'UPDATE tool_manifests SET promoted = 0 WHERE tool_name = ? AND version != ?',
                    (tool_name, version),
                )

    def list_versions(self, tool_name: str) -> list[dict]:
        with store.conn() as conn:
            rows = conn.execute(
                '''
                SELECT version, promoted, created_at, payload
                FROM tool_manifests
                WHERE tool_name = ?
                ORDER BY created_at DESC
                ''',
                (tool_name,),
            ).fetchall()
        items: list[dict] = []
        for row in rows:
            payload = store.load(row[3])
            payload['version'] = row[0]
            payload['promoted'] = bool(row[1])
            payload['created_at'] = row[2]
            items.append(payload)
        return items

    def get_promoted(self, tool_name: str) -> dict | None:
        with store.conn() as conn:
            row = conn.execute(
                '''
                SELECT version, payload
                FROM tool_manifests
                WHERE tool_name = ? AND promoted = 1
                ORDER BY created_at DESC
                LIMIT 1
                ''',
                (tool_name,),
            ).fetchone()
        if not row:
            return None
        payload = store.load(row[1])
        payload['version'] = row[0]
        payload['promoted'] = True
        return payload

    def promote(self, tool_name: str, version: str) -> bool:
        with store.conn() as conn:
            exists = conn.execute(
                'SELECT id FROM tool_manifests WHERE tool_name = ? AND version = ? LIMIT 1',
                (tool_name, version),
            ).fetchone()
            if not exists:
                return False
            conn.execute('UPDATE tool_manifests SET promoted = 0 WHERE tool_name = ?', (tool_name,))
            conn.execute(
                'UPDATE tool_manifests SET promoted = 1 WHERE tool_name = ? AND version = ?',
                (tool_name, version),
            )
            return True


class GenericPayloadRepository:
    def __init__(self, table: str) -> None:
        self._table = table

    def save(self, payload_id: str, status: str, payload: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with store.conn() as conn:
            conn.execute(
                f'''
                INSERT INTO {self._table} (id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                ''',
                (payload_id, status, now, now, store.dump(payload)),
            )

    def get(self, payload_id: str) -> dict | None:
        with store.conn() as conn:
            row = conn.execute(f'SELECT payload FROM {self._table} WHERE id = ?', (payload_id,)).fetchone()
        if not row:
            return None
        return store.load(row[0])

    def list_recent(self, limit: int = 100) -> list[dict]:
        with store.conn() as conn:
            rows = conn.execute(
                f'SELECT payload FROM {self._table} ORDER BY updated_at DESC LIMIT ?',
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [store.load(row[0]) for row in rows]


repositories = {
    'tasks': TaskRepository(),
    'approvals': ApprovalRepository(),
    'checkpoints': CheckpointRepository(),
    'traces': TraceRepository(),
    'self_improve': SelfImproveRepository(),
    'runtime': RuntimeRepository(),
    'missions': MissionRepository(),
    'execution_reports': ExecutionReportRepository(),
    'rollback_artifacts': RollbackArtifactRepository(),
    'improvement_proposals': ImprovementProposalRepository(),
    'task_queue': TaskQueueRepository(),
    'task_state_transitions': TaskStateTransitionRepository(),
    'tool_manifests': ToolManifestRepository(),
    'improvement_jobs': GenericPayloadRepository('improvement_jobs'),
}
