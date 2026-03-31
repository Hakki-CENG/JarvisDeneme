from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def test_assistant_command_ignores_missing_wake_word() -> None:
    response = client.post(
        '/assistant/command',
        headers=auth_headers(),
        json={'text': 'notepad ac', 'execute': False, 'wake_word': 'jarvis'},
    )
    assert response.status_code == 200
    assert response.json()['status'] == 'ignored'


def test_assistant_command_can_create_task() -> None:
    response = client.post(
        '/assistant/command',
        headers=auth_headers(),
        json={'text': 'jarvis notepad ac', 'execute': True, 'wake_word': 'jarvis'},
    )
    assert response.status_code == 200
    assert response.json()['status'] == 'task_created'
    assert response.json().get('task')
