from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def test_mission_create_and_list() -> None:
    create = client.post(
        '/missions',
        headers=auth_headers(),
        json={'objective': 'research latest retrieval agents', 'auto_execute': False, 'priority': 4},
    )
    assert create.status_code == 200
    payload = create.json()
    assert payload['mission']['mission_id']
    assert payload['status'] in {'DRAFT', 'QUEUED'}

    listed = client.get('/missions', headers=auth_headers())
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)
    assert any(item['id'] == payload['mission']['mission_id'] for item in listed.json())
