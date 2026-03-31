from fastapi.testclient import TestClient

from app.main import app
from app.services.secret_vault import secret_vault


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {'X-API-Key': secret_vault.get_secret('ADMIN_API_TOKEN') or ''}


def test_generate_and_approve_self_improve_proposal() -> None:
    generated = client.post('/self-improve/proposals', headers=auth_headers(), json={'focus': 'all', 'max_items': 2})
    assert generated.status_code == 200
    proposals = generated.json()
    assert isinstance(proposals, list)
    assert proposals

    proposal_id = proposals[0]['id']
    approved = client.post(
        f'/self-improve/proposals/{proposal_id}/approve',
        headers=auth_headers(),
        json={'note': 'approve in unit test'},
    )
    assert approved.status_code == 200
    assert approved.json()['status'] in {'APPROVED', 'APPLIED'}
