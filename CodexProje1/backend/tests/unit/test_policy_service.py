from app.services.policy_service import policy_service


def test_block_obfuscated_shell_command() -> None:
    result = policy_service.evaluate_shell_command('powershell -enc aGVsbG8=')
    assert result.level == 'blocked'


def test_safe_shell_prefix_allowed() -> None:
    result = policy_service.evaluate_shell_command('echo hello')
    assert result.level == 'safe'


def test_chained_shell_command_marks_non_allowlisted_segment_risky() -> None:
    result = policy_service.evaluate_shell_command('echo ok && rm -rf /tmp/demo')
    assert result.level in {'risky', 'blocked'}


def test_unknown_app_command_is_risky() -> None:
    result = policy_service.evaluate_app_command('calc.exe')
    assert result.level in {'risky', 'blocked'}


def test_blocked_http_target_rejected() -> None:
    result = policy_service.evaluate_http_request(method='GET', url='http://127.0.0.1:8080')
    assert result.level == 'blocked'
