from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN', consumer='test_ops_endpoints') or ''}


def test_ops_endpoints_available() -> None:
    deep = client.get('/ops/health/deep', headers=_admin_headers())
    assert deep.status_code == 200
    assert deep.json()['status'] == 'ok'

    slo = client.get('/ops/slo', headers=_admin_headers())
    assert slo.status_code == 200
    assert 'queue_depth' in slo.json()

    queue = client.get('/ops/queue', headers=_admin_headers())
    assert queue.status_code == 200
    assert isinstance(queue.json(), list)

    incidents = client.get('/ops/incidents', headers=_admin_headers())
    assert incidents.status_code == 200
    assert isinstance(incidents.json(), list)

    secret_usage = client.get('/ops/secret-usage', headers=_admin_headers())
    assert secret_usage.status_code == 200
    assert isinstance(secret_usage.json().get('items', []), list)

