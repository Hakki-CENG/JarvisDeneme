from uuid import uuid4

from app.models.schemas import (
    SkillCatalogBootstrapRequest,
    SkillComposeRequest,
    SkillManifest,
    SkillRunRequest,
    SkillSearchRequest,
    SkillWorkflowStep,
)
from app.services.skill_service import skill_service


def test_skill_search_can_return_virtual_results() -> None:
    request = SkillSearchRequest(query='xxyyzz_unlikely_query', limit=4, include_virtual=True)
    hits = skill_service.search_skills(request)
    assert hits
    assert len(hits) <= 4
    assert any(item.skill_id.startswith('virtual::') for item in hits)


def test_compose_and_run_workflow_skill() -> None:
    suffix = uuid4().hex[:8]
    base_a = f'unit_base_a_{suffix}'
    base_b = f'unit_base_b_{suffix}'
    flow = f'unit_flow_{suffix}'

    skill_service.register_skill(
        SkillManifest(
            skill_id=base_a,
            version='1.0.0',
            description='unit test base skill a',
            capabilities=['unit', 'a'],
            risk_level='LOW',
        )
    )
    skill_service.register_skill(
        SkillManifest(
            skill_id=base_b,
            version='1.0.0',
            description='unit test base skill b',
            capabilities=['unit', 'b'],
            risk_level='LOW',
        )
    )

    composed = skill_service.compose_skill(
        SkillComposeRequest(
            skill_id=flow,
            description='unit workflow',
            steps=[
                SkillWorkflowStep(skill_id=base_a, payload={'step': 'a'}, required=True),
                SkillWorkflowStep(skill_id=base_b, payload={'step': 'b'}, required=True),
            ],
            risk_level='LOW',
        )
    )
    assert composed.skill_id == flow
    result = skill_service.run_skill(SkillRunRequest(skill_id=flow, payload={'source': 'unit'}))
    assert result.success is True
    assert len(result.output.get('trace', [])) == 2


def test_bootstrap_catalog_scales_with_unique_prefix() -> None:
    before = len(skill_service.list_skills())
    prefix = f'unit_{uuid4().hex[:6]}'
    result = skill_service.bootstrap_catalog(SkillCatalogBootstrapRequest(target_count=before + 20, prefix=prefix))
    assert int(result['total']) >= before
    assert int(result['created']) >= 1
