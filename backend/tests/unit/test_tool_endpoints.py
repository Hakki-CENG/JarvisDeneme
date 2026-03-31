from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def test_tools_catalog_health_and_dry_run() -> None:
    catalog = client.get('/tools/catalog', headers=auth_headers())
    assert catalog.status_code == 200
    assert isinstance(catalog.json(), list)

    health = client.get('/tools/health', headers=auth_headers())
    assert health.status_code == 200
    assert isinstance(health.json(), list)

    dry_run = client.post(
        '/tools/execute',
        headers=auth_headers(),
        json={'name': 'wikipedia.search', 'payload': {'query': 'jarvis'}, 'dry_run': True},
    )
    assert dry_run.status_code == 200
    assert dry_run.json()['success'] is True

    batch = client.post(
        '/tools/batch-execute',
        headers=auth_headers(),
        json={
            'requests': [
                {'name': 'wikipedia.search', 'payload': {'query': 'jarvis'}, 'dry_run': True},
                {'name': 'wikidata.lookup', 'payload': {'query': 'jarvis'}, 'dry_run': True},
            ],
            'stop_on_error': True,
        },
    )
    assert batch.status_code == 200
    assert batch.json()['success'] is True

    versions = client.get('/tools/wikipedia.search/versions', headers=auth_headers())
    assert versions.status_code == 200
    assert isinstance(versions.json(), list)
    assert versions.json()

    promote = client.post('/tools/wikipedia.search/promote', headers=auth_headers(), json={'version': '1.0.0'})
    assert promote.status_code == 200
    assert promote.json()['promoted'] is True


def test_optional_tool_toggle() -> None:
    disable = client.post('/tools/adapter.geosentinel/toggle', headers=auth_headers(), json={'enabled': False})
    assert disable.status_code == 200
    assert disable.json()['enabled'] is False

    enable = client.post('/tools/adapter.geosentinel/toggle', headers=auth_headers(), json={'enabled': True})
    assert enable.status_code == 200
    assert enable.json()['enabled'] is True
