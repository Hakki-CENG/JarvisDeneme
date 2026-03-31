from app.services.agents.mesh import agent_mesh


def test_extract_url_supports_standard_url_pattern() -> None:
    url = agent_mesh._extract_url('https://example.com/demo?a=1, bunu incele')  # noqa: SLF001
    assert url == 'https://example.com/demo?a=1'


def test_extract_json_object_from_markdown_fence() -> None:
    raw = (
        'Plan output:\n'
        '```json\n'
        '{"actions":[{"action":"wait","parameters":{"seconds":1},"justification":"sync"}]}\n'
        '```'
    )
    payload = agent_mesh._extract_json_object(raw)  # noqa: SLF001
    assert payload is not None
    assert isinstance(payload.get('actions'), list)
