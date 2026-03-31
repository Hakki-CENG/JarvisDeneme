from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from app.core.settings import settings


class SQLiteStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.sqlite_path
        self._init_db()

    @contextmanager
    def conn(self) -> Iterable[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self.conn() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    last_error TEXT
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    decided_at TEXT
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS traces (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS runtime_states (
                    task_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS world_states (
                    task_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    memory_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS execution_reports (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    mission_id TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS rollback_artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    applied_at TEXT,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS improvement_proposals (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS task_queue (
                    task_id TEXT PRIMARY KEY,
                    priority INTEGER NOT NULL,
                    enqueued_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS task_state_transitions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS tool_manifests (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    promoted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS knowledge_nodes (
                    id TEXT PRIMARY KEY,
                    node_key TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0.0,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS knowledge_edges (
                    id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0.0,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS improvement_jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    level TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                '''
            )

            conn.execute('CREATE INDEX IF NOT EXISTS idx_task_queue_enqueued ON task_queue(enqueued_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_state_transitions_task ON task_state_transitions(task_id, created_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tool_manifests_name_version ON tool_manifests(tool_name, version)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_edges_source ON knowledge_edges(source_key)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at)')

    @staticmethod
    def dump(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=True)

    @staticmethod
    def load(raw: str) -> dict[str, Any]:
        return json.loads(raw)


store = SQLiteStore()
