from app.services.planner_service import planner_service


def test_planner_extracts_json_wrapped_in_code_fence() -> None:
    raw = (
        'Structured response:\n'
        '```json\n'
        '{"strategy":"focused","steps":[{"title":"A","description":"B"}]}\n'
        '```'
    )
    payload = planner_service._extract_json_object(raw)  # noqa: SLF001
    assert payload is not None
    assert payload.get('strategy') == 'focused'
