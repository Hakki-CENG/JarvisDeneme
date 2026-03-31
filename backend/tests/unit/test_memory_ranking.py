from uuid import uuid4

from app.services.memory_service import memory_service


def test_memory_search_prioritizes_exact_phrase_hit() -> None:
    suffix = uuid4().hex
    exact_phrase = f'orion-{suffix} mission briefing'
    exact_key = f'memory-exact-{suffix}'
    loose_key = f'memory-loose-{suffix}'

    memory_service.upsert(key=exact_key, content=exact_phrase, tags=['mission'])
    memory_service.upsert(key=loose_key, content=f'orion update {suffix}', tags=['mission'])

    hits = memory_service.search(exact_phrase, limit=5)

    assert hits
    assert hits[0].key == exact_key
