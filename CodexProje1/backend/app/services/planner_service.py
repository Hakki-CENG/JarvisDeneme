from __future__ import annotations

import json
from dataclasses import dataclass

from app.models.schemas import PlannedStep, TaskPlan, TaskSpec
from app.services.agents.mesh import agent_mesh
from app.services.memory_service import memory_service
from app.services.model_router import model_router
from app.core.settings import settings


@dataclass
class PlannerOutput:
    strategy: str
    steps: list[dict[str, str]]


class PlannerService:
    def build_plan(self, task: TaskSpec) -> TaskPlan:
        plan_data = self._infer_plan(task)
        steps: list[PlannedStep] = []
        for item in plan_data.steps:
            step_title = item.get('title', 'Step').strip() or 'Step'
            description = item.get('description', '').strip() or step_title
            actions = agent_mesh.derive_actions_for_step(task, description)
            steps.append(
                PlannedStep(
                    title=step_title,
                    description=description,
                    actions=actions,
                )
            )

        if not steps:
            fallback_actions = agent_mesh.derive_actions_for_step(task, task.objective)
            steps = [
                PlannedStep(
                    title='Execute objective',
                    description=task.objective,
                    actions=fallback_actions,
                )
            ]

        return TaskPlan(task_id=task.id, strategy=plan_data.strategy, steps=steps)

    def _infer_plan(self, task: TaskSpec) -> PlannerOutput:
        memories = memory_service.search(task.objective, limit=settings.max_memory_items_for_planner)
        memory_block = '\n'.join(
            [
                f'- key={item.key} tags={",".join(item.tags)} summary={item.content[:220]}'
                for item in memories
            ]
        )
        prompt = (
            'Return strict JSON only with shape '
            '{"strategy": string, "steps": [{"title": string, "description": string}]}\n'
            f'Objective: {task.objective}\n'
            f'Constraints: {task.constraints}\n'
            f'Allowed tools: {[t.value for t in task.tools_allowed]}\n'
            f'Relevant memory (can be empty):\n{memory_block or "- none"}\n'
            'The plan must be concise and executable.'
        )
        result = model_router.request_reasoning(prompt, round_name='StructuredPlan')
        text = result['analysis']

        payload = self._extract_json_object(text)
        if not payload:
            return self._fallback_plan(task)

        strategy = str(payload.get('strategy', 'Direct execution strategy')).strip() or 'Direct execution strategy'
        raw_steps = payload.get('steps', [])
        steps: list[dict[str, str]] = []
        if isinstance(raw_steps, list):
            for entry in raw_steps:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get('title', '')).strip()
                description = str(entry.get('description', '')).strip()
                if title or description:
                    steps.append({'title': title or description, 'description': description or title})

        if not steps:
            return self._fallback_plan(task)

        return PlannerOutput(strategy=strategy, steps=steps)

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        try:
            direct = json.loads(text)
            if isinstance(direct, dict):
                return direct
        except Exception:
            pass

        start = text.find('{')
        end = text.rfind('}')
        if start == -1 or end == -1 or end <= start:
            return None

        snippet = text[start : end + 1]
        try:
            loaded = json.loads(snippet)
            return loaded if isinstance(loaded, dict) else None
        except Exception:
            return None

    @staticmethod
    def _fallback_plan(task: TaskSpec) -> PlannerOutput:
        splitters = task.objective.replace(' then ', ',').replace(' ve ', ',')
        raw = [part.strip() for part in splitters.split(',') if part.strip()]
        if not raw:
            raw = [task.objective]
        steps = [{'title': f'Step {idx + 1}', 'description': part} for idx, part in enumerate(raw[:10])]
        return PlannerOutput(strategy='Fallback heuristic plan', steps=steps)


planner_service = PlannerService()
