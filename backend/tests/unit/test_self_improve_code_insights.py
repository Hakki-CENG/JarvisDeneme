from app.services.self_improvement import self_improvement_service


def test_code_insights_respects_requested_limit() -> None:
    items = self_improvement_service.code_insights(max_items=5)
    assert len(items) <= 5
    for item in items:
        assert item.file
        assert item.line >= 1
        assert item.issue
