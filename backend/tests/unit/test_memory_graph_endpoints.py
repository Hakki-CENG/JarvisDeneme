from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN', consumer='test_memory_graph_endpoints') or ''}


def test_memory_embed_reindex_graph_query() -> None:
    add = client.post(
        '/memory/add',
        headers=_admin_headers(),
        json={'key': 'test:memory:1', 'content': 'Jarvis memory graph integration', 'tags': ['jarvis', 'graph']},
    )
    assert add.status_code == 200

    embed = client.post('/memory/embed', headers=_admin_headers(), json={'text': 'jarvis memory'})
    assert embed.status_code == 200
    body = embed.json()
    assert body['dimensions'] == len(body['vector'])

    reindex = client.post('/memory/reindex', headers=_admin_headers(), json={'limit': 200})
    assert reindex.status_code == 200
    assert isinstance(reindex.json(), list)

    graph = client.get('/memory/graph?limit=20', headers=_admin_headers())
    assert graph.status_code == 200
    assert 'nodes' in graph.json()
    assert 'edges' in graph.json()

    query = client.post('/memory/graph/query', headers=_admin_headers(), json={'query': 'jarvis', 'limit': 20})
    assert query.status_code == 200
    assert isinstance(query.json().get('nodes', []), list)

