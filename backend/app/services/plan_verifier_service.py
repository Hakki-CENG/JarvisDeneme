from __future__ import annotations

from app.models.schemas import ActionEnvelope
from app.services.policy_service import policy_service
from app.services.risk_engine import risk_engine


class PlanVerifierService:
    def verify_actions(self, actions: list[ActionEnvelope]) -> dict:
        checks: list[dict] = []
        blocked = 0
        risky = 0

        for action in actions:
            report = risk_engine.evaluate(action)
            verdict = 'safe'
            notes = list(report.reasons)

            if action.action.value == 'shell_exec':
                command = str(action.parameters.get('command', ''))
                shell = policy_service.evaluate_shell_command(command)
                if shell.level == 'blocked':
                    verdict = 'blocked'
                    notes.append(shell.reason)
                elif shell.level == 'risky':
                    verdict = 'risky'
            elif action.action.value == 'open_app':
                app = str(action.parameters.get('app', ''))
                app_policy = policy_service.evaluate_app_command(app)
                if app_policy.level == 'blocked':
                    verdict = 'blocked'
                    notes.append(app_policy.reason)
                elif app_policy.level == 'risky':
                    verdict = 'risky'
            elif action.action.value == 'http_request':
                method = str(action.parameters.get('method', 'GET'))
                url = str(action.parameters.get('url', ''))
                http = policy_service.evaluate_http_request(method=method, url=url)
                if http.level == 'blocked':
                    verdict = 'blocked'
                    notes.append(http.reason)
                elif http.level == 'risky':
                    verdict = 'risky'

            if verdict == 'blocked':
                blocked += 1
            elif verdict == 'risky':
                risky += 1

            checks.append(
                {
                    'action_id': action.id,
                    'action': action.action.value,
                    'risk_score': report.risk_score,
                    'requires_approval': report.requires_approval,
                    'verdict': verdict,
                    'notes': notes[:10],
                }
            )

        return {
            'total': len(actions),
            'blocked': blocked,
            'risky': risky,
            'checks': checks,
        }


plan_verifier_service = PlanVerifierService()
