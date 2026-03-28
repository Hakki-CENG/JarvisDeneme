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

    @staticmethod
    def dump(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=True)

    @staticmethod
    def load(raw: str) -> dict[str, Any]:
        return json.loads(raw)


store = SQLiteStore()
