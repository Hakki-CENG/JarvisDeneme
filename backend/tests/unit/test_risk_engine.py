from app.models.schemas import ActionEnvelope, ActionType
from app.services.risk_engine import RiskEngine


def test_delete_file_operation_requires_approval() -> None:
    engine = RiskEngine()
    action = ActionEnvelope(task_id='t1', action=ActionType.file_ops, parameters={'op': 'delete', 'src': 'a.txt'})

    report = engine.evaluate(action)

    assert report.requires_approval is True
    assert report.risk_score >= 0.6


def test_type_text_is_low_risk_without_forced_policy() -> None:
    engine = RiskEngine()
    action = ActionEnvelope(task_id='t1', action=ActionType.type_text, parameters={'text': 'hello'})

    report = engine.evaluate(action)

    assert report.risk_score < 0.6
