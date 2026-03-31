from app.services.voice import voice_service


def test_parse_command_detects_safety_stop_intent() -> None:
    parsed = voice_service.parse_command('Jarvis acil durdur')
    assert parsed['has_wake_word'] is True
    assert parsed['intent'] == 'safety_stop'


def test_parse_command_extracts_url_and_objective() -> None:
    parsed = voice_service.parse_command('jarvis https://example.com raporunu oku')
    entities = parsed.get('entities', {})
    assert isinstance(entities, dict)
    assert entities.get('url') == 'https://example.com'
    assert parsed.get('suggested_objective') == 'https://example.com raporunu oku'
