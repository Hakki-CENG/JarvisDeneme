from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def _wait_status(task_id: str, timeout: float = 8.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        response = client.get(f'/tasks/{task_id}', headers=auth_headers())
        if response.status_code != 200:
            time.sleep(0.2)
            continue
        status = response.json().get('status', '')
        if status in {'COMPLETED', 'FAILED', 'PAUSED_QUOTA', 'CANCELLED'}:
            return status
        time.sleep(0.2)
    response = client.get(f'/tasks/{task_id}', headers=auth_headers())
    return response.json().get('status', '') if response.status_code == 200 else 'UNKNOWN'


def test_task_execution_report_and_rollback_preview_endpoints() -> None:
    created = client.post('/tasks', headers=auth_headers(), json={'objective': 'dosya kaydet ve kısa bekle'})
    assert created.status_code == 200
    task_id = created.json()['id']

    _wait_status(task_id)

    report = client.get(f'/tasks/{task_id}/report', headers=auth_headers())
    assert report.status_code == 200
    payload = report.json()
    assert payload['task_id'] == task_id
    assert 'tools_used' in payload

    rollback_preview = client.post('/rollback/preview', headers=auth_headers(), json={'task_id': task_id, 'limit': 20})
    assert rollback_preview.status_code == 200
    assert isinstance(rollback_preview.json(), list)
