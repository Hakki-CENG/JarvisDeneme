from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def test_protected_endpoint_requires_token() -> None:
    response = client.get('/tasks')
    assert response.status_code == 401


def test_auth_bootstrap_and_access() -> None:
    current_admin = secret_vault.get_secret('ADMIN_API_TOKEN') or ''
    admin_token = 'bootstrap-admin-token-0123456789'
    user_token = 'bootstrap-user-token-0123456789'
    bootstrap = client.post(
        '/auth/bootstrap',
        json={'admin_token': admin_token, 'user_token': user_token},
        headers={'X-API-Key': current_admin},
    )
    assert bootstrap.status_code == 200

    response = client.get('/auth/me', headers={'X-API-Key': admin_token})
    assert response.status_code == 200
    assert response.json()['role'] in {'ADMIN', 'USER'}


def test_desktop_action_requires_admin_role() -> None:
    current_admin = secret_vault.get_secret('ADMIN_API_TOKEN') or ''
    admin_token = 'role-admin-token'
    user_token = 'role-user-token'
    bootstrap = client.post(
        '/auth/bootstrap',
        json={'admin_token': admin_token, 'user_token': user_token},
        headers={'X-API-Key': current_admin},
    )
    assert bootstrap.status_code == 200

    response = client.post(
        '/desktop/actions',
        headers={'X-API-Key': user_token},
        json={
            'task_id': 'demo-task',
            'action': 'read_screen',
            'parameters': {'path': '.jarvisx_data/demo.png'},
        },
    )
    assert response.status_code == 403
