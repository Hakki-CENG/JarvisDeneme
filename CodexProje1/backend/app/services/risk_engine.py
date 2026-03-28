from __future__ import annotations

from dataclasses import dataclass

from app.core.settings import settings
from app.models.schemas import ActionEnvelope, ActionType, RiskReport
from app.services.policy_service import policy_service


@dataclass
class RiskPolicy:
    approval_threshold: float = 0.6


class RiskEngine:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(self, action: ActionEnvelope) -> RiskReport:
        score = 0.1
        reasons: list[str] = []

        if action.action in {ActionType.move_mouse, ActionType.click, ActionType.type_text, ActionType.hotkey}:
            score += 0.15
            reasons.append('Desktop input injection can produce irreversible actions.')

        if action.action == ActionType.clipboard_write:
            score += 0.15
            reasons.append('Clipboard write can leak/overwrite sensitive copied data.')

        if action.action == ActionType.shell_exec:
            score += 0.35
            reasons.append('Shell command execution can change system state.')
            command = str(action.parameters.get('command', '')).lower()
            if any(marker in command for marker in ['rm ', 'del ', 'format', 'reg add', 'winget install', 'choco install']):
                score += 0.35
                reasons.append('Command includes destructive/install/system markers.')
            shell_policy = policy_service.evaluate_shell_command(command)
            if shell_policy.level == 'blocked':
                score = 1.0
                reasons.append(f'Shell policy blocked command: {shell_policy.reason}')
            elif shell_policy.level == 'risky':
                score += 0.25
                reasons.append(f'Shell command outside allowlist: {shell_policy.reason}')

        if action.action == ActionType.file_ops:
            op = str(action.parameters.get('op', '')).lower()
            if op in {'delete', 'remove'}:
                score += 0.55
                reasons.append('File delete operations always require approval.')
            elif op in {'write', 'move', 'rename'}:
                score += 0.25
                reasons.append('File write/move operations can affect user data.')
            if settings.require_approval_for_sensitive_reads and op == 'read':
                src = str(action.parameters.get('src', ''))
                if src and not policy_service.is_path_allowed(src):
                    score += 0.3
                    reasons.append('Read targets a path outside allowed roots.')

        if action.action in {ActionType.open_app, ActionType.focus_window}:
            score += 0.2
            reasons.append('Application/window control affects active user context.')
            if action.action == ActionType.open_app:
                app_command = str(action.parameters.get('app', ''))
                app_policy = policy_service.evaluate_app_command(app_command)
                if app_policy.level == 'blocked':
                    score = 1.0
                    reasons.append(f'App command blocked by policy: {app_policy.reason}')
                elif app_policy.level == 'risky':
                    score += 0.2
                    reasons.append(f'App command outside allowlist: {app_policy.reason}')

        if action.action == ActionType.browser_script:
            score += 0.35
            reasons.append('Browser automation may interact with external websites and data.')

        if action.action == ActionType.http_request:
            score += 0.35
            reasons.append('HTTP request may send data to external network targets.')
            method = str(action.parameters.get('method', 'GET'))
            url = str(action.parameters.get('url', ''))
            http_policy = policy_service.evaluate_http_request(method=method, url=url)
            if http_policy.level == 'blocked':
                score = 1.0
                reasons.append(f'HTTP request blocked by policy: {http_policy.reason}')

        if action.action == ActionType.read_screen:
            score += 0.2
            reasons.append('Screen capture may include sensitive information.')

        if settings.require_approval_for_external_writes and bool(action.parameters.get('external_target')):
            score += 0.4
            reasons.append('Action targets an external service endpoint.')

        score = min(score, 1.0)

        requires_approval = score >= self.policy.approval_threshold or self._policy_forces_approval(action)
        return RiskReport(
            action_id=action.id,
            risk_score=score,
            reasons=reasons,
            requires_approval=requires_approval,
        )

    @staticmethod
    def _policy_forces_approval(action: ActionEnvelope) -> bool:
        if action.action == ActionType.file_ops:
            op = str(action.parameters.get('op', '')).lower()
            if op in {'delete', 'remove'} and settings.require_approval_for_delete:
                return True
            src = str(action.parameters.get('src', ''))
            dst = str(action.parameters.get('dst', ''))
            if src and not policy_service.is_path_allowed(src):
                return True
            if dst and not policy_service.is_path_allowed(dst):
                return True

        if action.action == ActionType.shell_exec:
            command = str(action.parameters.get('command', '')).lower()
            if settings.require_approval_for_install and ('install' in command or 'winget' in command or 'choco' in command):
                return True
            if settings.require_approval_for_system_changes and any(k in command for k in ['reg ', 'powershell set-', 'sc config']):
                return True
            shell_policy = policy_service.evaluate_shell_command(command)
            if shell_policy.level == 'blocked':
                return True
            if shell_policy.level == 'risky' and settings.require_approval_for_unknown_shell_commands:
                return True

        if action.action in {ActionType.open_app, ActionType.focus_window} and settings.require_approval_for_system_changes:
            return True
        if action.action == ActionType.open_app:
            app_command = str(action.parameters.get('app', ''))
            app_policy = policy_service.evaluate_app_command(app_command)
            if app_policy.level != 'safe':
                return True

        if action.action == ActionType.browser_script and settings.require_approval_for_external_writes:
            return True
        if action.action == ActionType.http_request:
            method = str(action.parameters.get('method', 'GET'))
            url = str(action.parameters.get('url', ''))
            http_policy = policy_service.evaluate_http_request(method=method, url=url)
            if http_policy.level != 'safe':
                return True
            if settings.require_approval_for_external_writes and method.upper() != 'GET':
                return True

        return False


risk_engine = RiskEngine()
