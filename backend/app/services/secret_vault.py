from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from app.core.settings import settings
from app.services.storage import store


class SecretVault:
    def __init__(self) -> None:
        self._key_path = settings.data_dir / '.vault_key'
        self._store_path = settings.data_dir / 'secrets.enc'
        self._crypto = None

        key = self._load_or_create_key()
        try:
            from cryptography.fernet import Fernet

            self._crypto = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest()))
        except Exception:
            self._crypto = None
        if self._crypto is None:
            raise RuntimeError('cryptography package is required for secure secret vault encryption')
        with store.conn() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS secret_usage (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    secret_name TEXT NOT NULL,
                    consumer TEXT NOT NULL,
                    request_id TEXT,
                    found INTEGER NOT NULL
                )
                '''
            )

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes()

        key = os.urandom(32)
        self._key_path.write_bytes(key)
        return key

    def _read_store(self) -> dict[str, str]:
        if not self._store_path.exists():
            return {}

        raw = self._store_path.read_bytes()
        decrypted = self._crypto.decrypt(raw)
        return json.loads(decrypted.decode('utf-8'))

    def _write_store(self, data: dict[str, str]) -> None:
        encoded = json.dumps(data, ensure_ascii=True).encode('utf-8')
        encrypted = self._crypto.encrypt(encoded)
        self._store_path.write_bytes(encrypted)

    def set_secret(self, name: str, value: str) -> None:
        data = self._read_store()
        data[name] = value
        self._write_store(data)

    def get_secret(self, name: str, consumer: str = '', request_id: str = '') -> str | None:
        value = self._read_store().get(name)
        self._log_usage(name=name, consumer=consumer, request_id=request_id, found=value is not None)
        return value

    def list_secret_names(self) -> list[str]:
        return sorted(self._read_store().keys())

    @staticmethod
    def _log_usage(name: str, consumer: str, request_id: str, found: bool) -> None:
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO secret_usage (id, created_at, secret_name, consumer, request_id, found)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    str(uuid4()),
                    datetime.now(timezone.utc).isoformat(),
                    name,
                    consumer or 'unknown',
                    request_id or None,
                    1 if found else 0,
                ),
            )

    def usage(self, limit: int = 200) -> list[dict[str, str | int]]:
        with store.conn() as conn:
            rows = conn.execute(
                '''
                SELECT created_at, secret_name, consumer, request_id, found
                FROM secret_usage
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [
            {
                'created_at': row[0],
                'secret_name': row[1],
                'consumer': row[2],
                'request_id': row[3] or '',
                'found': int(row[4]),
            }
            for row in rows
        ]


secret_vault = SecretVault()
