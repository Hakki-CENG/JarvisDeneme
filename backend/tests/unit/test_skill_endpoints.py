from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def admin_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def test_skill_search_endpoint_returns_results() -> None:
    response = client.post('/skills/search', headers=admin_headers(), json={'query': 'workflow', 'limit': 5, 'include_virtual': True})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_self_improve_code_insights_endpoint_requires_admin_and_returns_payload() -> None:
    response = client.post('/self-improve/code-insights', headers=admin_headers(), json={'max_items': 4})
    assert response.status_code == 200
    payload = response.json()
    assert 'count' in payload
    assert 'items' in payload
