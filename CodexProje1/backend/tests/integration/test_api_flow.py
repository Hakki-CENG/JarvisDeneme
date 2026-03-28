from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def wait_for_terminal_state(task_id: str, timeout: float = 8.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        response = client.get(f'/tasks/{task_id}', headers=auth_headers())
        assert response.status_code == 200
        status = response.json()['status']
        if status in {'COMPLETED', 'FAILED', 'PAUSED_QUOTA'}:
            return status
        time.sleep(0.2)
    return client.get(f'/tasks/{task_id}', headers=auth_headers()).json()['status']


def setup_module() -> None:
    token = secret_vault.get_secret('ADMIN_API_TOKEN') or ''
    client.post(
        '/auth/bootstrap',
        json={'admin_token': 'integration-admin-token-0123456789', 'user_token': 'integration-user-token-0123456789'},
        headers={'X-API-Key': token},
    )


def test_task_lifecycle_and_checkpoints() -> None:
    create_response = client.post('/tasks', json={'objective': 'screen oku ve shell komutu çalıştır'}, headers=auth_headers())
    assert create_response.status_code == 200

    task_id = create_response.json()['id']
    status = wait_for_terminal_state(task_id)
    assert status in {'COMPLETED', 'PAUSED_QUOTA', 'FAILED'}

    checkpoints = client.get(f'/checkpoints/{task_id}', headers=auth_headers())
    assert checkpoints.status_code == 200
    assert isinstance(checkpoints.json(), list)


def test_safety_emergency_stop_toggle() -> None:
    stop_response = client.post('/safety/emergency-stop', json={'reason': 'integration test'}, headers=auth_headers())
    assert stop_response.status_code == 200
    assert stop_response.json()['emergency_stop'] is True

    clear_response = client.post('/safety/emergency-clear', headers=auth_headers())
    assert clear_response.status_code == 200
    assert clear_response.json()['emergency_stop'] is False


def test_task_cancel_endpoint() -> None:
    create_response = client.post('/tasks', json={'objective': 'terminal komutu çalıştır ve bekle'}, headers=auth_headers())
    assert create_response.status_code == 200
    task_id = create_response.json()['id']

    cancel_response = client.post(f'/tasks/{task_id}/cancel', json={'reason': 'integration cancel'}, headers=auth_headers())
    assert cancel_response.status_code == 200
    assert cancel_response.json()['status'] in {'CANCELLED', 'COMPLETED', 'FAILED'}
