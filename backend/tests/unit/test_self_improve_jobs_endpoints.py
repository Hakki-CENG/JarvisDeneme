from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN', consumer='test_self_improve_jobs') or ''}


def test_create_get_cancel_self_improve_job() -> None:
    created = client.post('/self-improve/jobs', headers=_admin_headers(), json={'focus': 'all', 'max_items': 2})
    assert created.status_code == 200
    payload = created.json()
    assert payload['id']
    assert payload['status'] in {'WAITING_APPROVAL', 'RUNNING', 'APPLIED', 'REJECTED'}

    fetched = client.get(f"/self-improve/jobs/{payload['id']}", headers=_admin_headers())
    assert fetched.status_code == 200
    assert fetched.json()['id'] == payload['id']

    cancelled = client.post(
        f"/self-improve/jobs/{payload['id']}/cancel",
        headers=_admin_headers(),
        json={'reason': 'unit_test_cancel'},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()['status'] in {'CANCELLED', 'APPLIED', 'REJECTED'}

