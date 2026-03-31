from app.core.settings import settings
from app.services.model_router import model_router


def test_long_prompt_is_compressed_to_limit() -> None:
    raw = 'A' * (settings.max_reasoning_prompt_chars + 2400)
    compressed = model_router._compress_prompt(raw)  # noqa: SLF001 - unit test for internal guard behavior
    assert len(compressed) <= settings.max_reasoning_prompt_chars
    assert len(compressed) < len(raw)
