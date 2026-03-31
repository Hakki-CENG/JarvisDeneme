from app.services.memory_service import memory_service


def test_memory_upsert_and_search() -> None:
    key = 'test-memory-key'
    memory_service.upsert(key=key, content='Jarvis can open browser and summarize reports', tags=['browser', 'report'])

    hits = memory_service.search('summarize reports', limit=5)
    keys = {item.key for item in hits}
    assert key in keys
