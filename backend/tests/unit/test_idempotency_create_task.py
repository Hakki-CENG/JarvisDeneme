from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def test_create_task_idempotency_replay() -> None:
    key = 'idem-test-1'
    payload = {'objective': 'idempotency test objective'}

    first = client.post('/tasks', json=payload, headers={**auth_headers(), 'Idempotency-Key': key})
    second = client.post('/tasks', json=payload, headers={**auth_headers(), 'Idempotency-Key': key})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']
