from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from app.core.settings import settings


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

    def get_secret(self, name: str) -> str | None:
        return self._read_store().get(name)

    def list_secret_names(self) -> list[str]:
        return sorted(self._read_store().keys())


secret_vault = SecretVault()
