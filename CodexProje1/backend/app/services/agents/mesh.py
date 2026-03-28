from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.core.settings import settings
from app.models.schemas import ActionEnvelope, ActionResult, ActionType, ExecutionTrace, TaskSpec
from app.services.model_router import model_router


@dataclass
class DeliberationOutput:
    traces: list[ExecutionTrace]
    actions: list[ActionEnvelope]
    pending_steps: list[str]


class AgentMesh:
    AGENTS = ('Planner', 'Researcher', 'Critic', 'Coder', 'Verifier')

    def deliberate(self, task: TaskSpec) -> DeliberationOutput:
        traces: list[ExecutionTrace] = []

        objective = task.objective.strip()
        pending_steps = self._make_subtasks(objective)

        # Maximum reasoning mode: each round is always executed.
        for round_no in range(settings.max_reasoning_rounds):
            for agent in self.AGENTS:
                prompt = (
                    f'Task={objective}\n'
                    f'Constraints={task.constraints}\n'
                    f'Round={round_no + 1}/{settings.max_reasoning_rounds}\n'
                    f'Agent={agent}\n'
                    f'PendingSteps={pending_steps}'
                )
                result = model_router.request_reasoning(prompt, round_name=f'{agent}-R{round_no + 1}')
                traces.append(
                    ExecutionTrace(
                        task_id=task.id,
                        agent=agent,
                        summary=result['analysis'],
                        details={'provider': result['provider'], 'round': result['round']},
                    )
                )

        actions = self._derive_actions(task, pending_steps)
        return DeliberationOutput(traces=traces, actions=actions, pending_steps=pending_steps)

    @staticmethod
    def _make_subtasks(objective: str) -> list[str]:
        raw_parts = [p.strip() for p in objective.replace(' then ', ',').replace(' ve ', ',').split(',')]
        subtasks = [p for p in raw_parts if p]
        if not subtasks:
            subtasks = [objective]
        return subtasks[: settings.max_subtasks]

    def _derive_actions(self, task: TaskSpec, steps: list[str]) -> list[ActionEnvelope]:
        actions: list[ActionEnvelope] = []
        model_actions = self._model_action_candidates(task, steps)
        actions.extend(model_actions)
        objective_lower = task.objective.lower()
        detected_url = self._extract_url(task.objective) or 'https://example.com'

        if any(word in objective_lower for word in ['browser', 'chrome', 'tarayıcı', 'web']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.open_app,
                    parameters={'app': 'start chrome'},
                    justification='Objective references browser/web usage.',
                )
            )

        if any(word in objective_lower for word in ['scrape', 'extract', 'crawl', 'browser script', 'web data']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.browser_script,
                    parameters={
                        'url': detected_url,
                        'script': '() => ({ title: document.title, links: Array.from(document.links).slice(0,5).map(a => a.href) })',
                        'headless': True,
                        'screenshot_path': '.jarvisx_data/browser_script.png',
                    },
                    justification='Objective requires structured browser script execution.',
                )
            )

        if any(word in objective_lower for word in ['yaz', 'type', 'metin', 'message']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.type_text,
                    parameters={'text': task.objective[:140]},
                    justification='Objective requires text input.',
                )
            )

        if any(word in objective_lower for word in ['dosya', 'file', 'kaydet', 'save']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.file_ops,
                    parameters={
                        'op': 'write',
                        'dst': '.jarvisx_data/task_note.txt',
                        'content': f'Task objective: {task.objective}\nSteps: {steps}',
                    },
                    justification='Task includes file operation semantics.',
                )
            )

        if any(word in objective_lower for word in ['terminal', 'komut', 'shell', 'cmd', 'powershell']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.shell_exec,
                    parameters={'command': 'echo Jarvis-X task shell step', 'timeout_seconds': 20},
                    justification='Objective requests command execution.',
                )
            )
        if any(word in objective_lower for word in ['bekle', 'wait', 'pause']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.wait,
                    parameters={'seconds': 2},
                    justification='Objective includes waiting semantics.',
                )
            )
        if any(word in objective_lower for word in ['webhook', 'api çağır', 'http request']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.http_request,
                    parameters={'method': 'GET', 'url': detected_url},
                    justification='Objective implies external HTTP interaction.',
                )
            )
        if any(word in objective_lower for word in ['clipboard', 'pano']):
            actions.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=ActionType.clipboard_read,
                    parameters={},
                    justification='Objective references clipboard context.',
                )
            )

        if not actions:
            actions.extend(
                [
                    ActionEnvelope(
                        task_id=task.id,
                        action=ActionType.read_screen,
                        parameters={'path': '.jarvisx_data/screen_capture.png'},
                        justification='Default first step is capturing UI context.',
                    ),
                    ActionEnvelope(
                        task_id=task.id,
                        action=ActionType.shell_exec,
                        parameters={'command': 'echo Task acknowledged by Jarvis-X', 'timeout_seconds': 20},
                        justification='Default traceable execution step.',
                    ),
                ]
            )

        allowed = set(task.tools_allowed)
        dedup: list[ActionEnvelope] = []
        seen: set[str] = set()
        for action in actions:
            if action.action not in allowed:
                continue
            sig = f'{action.action.value}:{json.dumps(action.parameters, sort_keys=True, ensure_ascii=True)}'
            if sig in seen:
                continue
            seen.add(sig)
            dedup.append(action)
        return dedup

    @staticmethod
    def _extract_url(text: str) -> str | None:
        match = re.search(r'https?://\\S+', text)
        if not match:
            return None
        return match.group(0).rstrip('.,)')

    def derive_actions_for_step(self, task: TaskSpec, step: str) -> list[ActionEnvelope]:
        temp_spec = TaskSpec(
            id=task.id,
            objective=step,
            constraints=task.constraints,
            tools_allowed=task.tools_allowed,
            created_at=task.created_at,
        )
        return self._derive_actions(temp_spec, [step])

    def _model_action_candidates(self, task: TaskSpec, steps: list[str]) -> list[ActionEnvelope]:
        prompt = (
            'Return strict JSON only with this shape: '
            '{"actions":[{"action":"<one_of_ActionType>","parameters":{},"justification":"..."}]}\n'
            f'Objective={task.objective}\n'
            f'Steps={steps}\n'
            f'AllowedTools={[item.value for item in task.tools_allowed]}\n'
            'Keep actions minimal and executable.'
        )
        try:
            result = model_router.request_reasoning(prompt, round_name='ActionSynthesis')
        except Exception:
            return []

        payload = self._extract_json_object(result.get('analysis', ''))
        if not payload:
            return []
        raw_actions = payload.get('actions', [])
        if not isinstance(raw_actions, list):
            return []

        generated: list[ActionEnvelope] = []
        for item in raw_actions[:16]:
            if not isinstance(item, dict):
                continue
            raw_action = str(item.get('action', '')).strip()
            if not raw_action:
                continue
            try:
                action_type = ActionType(raw_action)
            except Exception:
                continue
            params = item.get('parameters', {})
            if not isinstance(params, dict):
                params = {}
            generated.append(
                ActionEnvelope(
                    task_id=task.id,
                    action=action_type,
                    parameters=params,
                    justification=str(item.get('justification', 'model_suggested')),
                )
            )
        return generated

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        start = text.find('{')
        end = text.rfind('}')
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def replan(
        self,
        task: TaskSpec,
        pending_steps: list[str],
        last_result: ActionResult,
    ) -> list[ActionEnvelope]:
        if not pending_steps:
            return []

        prompt = (
            f'Task={task.objective}\n'
            f'PendingSteps={pending_steps}\n'
            f'LastActionSuccess={last_result.success}\n'
            f'LastActionError={last_result.error or ""}\n'
            'Generate concise next-step strategy.'
        )
        model_router.request_reasoning(prompt, round_name='Replan')
        return self.derive_actions_for_step(task, pending_steps[0])


agent_mesh = AgentMesh()
