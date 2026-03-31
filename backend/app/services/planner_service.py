from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.models.schemas import MissionGraph, MissionNode, PlannedStep, TaskPlan, TaskSpec
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

    def build_mission_graph(self, task: TaskSpec) -> MissionGraph:
        plan = self.build_plan(task)
        nodes: list[MissionNode] = []
        previous_node_id: str | None = None

        for idx, step in enumerate(plan.steps, start=1):
            primary_tool = None
            fallback_tools: list[str] = []
            for action in step.actions:
                mapped = self._map_action_to_tool(action.action.value)
                if not mapped:
                    continue
                if not primary_tool:
                    primary_tool = mapped
                    continue
                if mapped != primary_tool and mapped not in fallback_tools:
                    fallback_tools.append(mapped)

            node = MissionNode(
                title=step.title or f'Step {idx}',
                description=step.description,
                primary_tool=primary_tool,
                fallback_tools=fallback_tools[:3],
                tool_selection_rationale=(
                    f'Primary tool selected from first executable action; '
                    f'fallback chain derived from remaining actions ({len(fallback_tools[:3])} alternatives).'
                ),
                depends_on=[previous_node_id] if previous_node_id else [],
                success_criteria=f'Complete step {idx}: {step.description[:160]}',
                dry_check={
                    'simulated': True,
                    'decision': 'EXECUTE' if step.actions else 'SKIP',
                    'action_count': len(step.actions),
                    'notes': 'Pre-check validates planned actions and tool availability.',
                },
            )
            nodes.append(node)
            previous_node_id = node.id

        if not nodes:
            node = MissionNode(
                title='Execute objective',
                description=task.objective,
                primary_tool='desktop.action',
                fallback_tools=['wikipedia.search'],
                tool_selection_rationale='Fallback mission graph uses desktop.action primary and wikipedia.search as retrieval fallback.',
                success_criteria='Task objective acknowledged and executed.',
                dry_check={'simulated': True, 'decision': 'EXECUTE', 'action_count': 1},
            )
            nodes.append(node)

        return MissionGraph(
            objective=task.objective,
            strategy=plan.strategy,
            nodes=nodes,
        )

    def _infer_plan(self, task: TaskSpec) -> PlannerOutput:
        memories = memory_service.search(task.objective, limit=settings.max_memory_items_for_planner)
        pattern_memories = self._collect_outcome_patterns(task.objective)
        memory_block = '\n'.join(
            [
                f'- key={item.key} tags={",".join(item.tags)} summary={item.content[:220]}'
                for item in memories
            ]
        )
        pattern_block = '\n'.join(pattern_memories[:12])
        prompt = (
            'Return strict JSON only with shape '
            '{"strategy": string, "steps": [{"title": string, "description": string}]}\n'
            f'Objective: {task.objective}\n'
            f'Constraints: {task.constraints}\n'
            f'Allowed tools: {[t.value for t in task.tools_allowed]}\n'
            f'Relevant memory (can be empty):\n{memory_block or "- none"}\n'
            f'Outcome patterns from past tasks:\n{pattern_block or "- no direct pattern found"}\n'
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

        fenced_blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)```', text, flags=re.IGNORECASE)
        for block in fenced_blocks:
            parsed = PlannerService._first_json_object(block)
            if parsed is not None:
                return parsed

        return PlannerService._first_json_object(text)

    @staticmethod
    def _first_json_object(text: str) -> dict | None:
        decoder = json.JSONDecoder()
        for idx, char in enumerate(text):
            if char != '{':
                continue
            try:
                parsed, _ = decoder.raw_decode(text[idx:])
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    @staticmethod
    def _fallback_plan(task: TaskSpec) -> PlannerOutput:
        splitters = task.objective.replace(' then ', ',').replace(' ve ', ',')
        raw = [part.strip() for part in splitters.split(',') if part.strip()]
        if not raw:
            raw = [task.objective]
        steps = [{'title': f'Step {idx + 1}', 'description': part} for idx, part in enumerate(raw[:10])]
        return PlannerOutput(strategy='Fallback heuristic plan', steps=steps)

    @staticmethod
    def _collect_outcome_patterns(objective: str) -> list[str]:
        candidates = memory_service.search(query=objective, limit=12)
        patterns: list[str] = []
        for item in candidates:
            text = item.content.replace('\n', ' ')[:220]
            if 'status=' in text.lower() or 'reason=' in text.lower() or 'outcome' in item.key.lower():
                patterns.append(f'- {item.key}: {text}')
        if patterns:
            return patterns

        fallback = memory_service.recent(limit=8)
        for item in fallback:
            if 'task:' in item.key.lower() and ('failed' in item.content.lower() or 'completed' in item.content.lower()):
                snippet = item.content[:180].replace('\n', ' ')
                patterns.append(f'- {item.key}: {snippet}')
        return patterns

    @staticmethod
    def _map_action_to_tool(action: str) -> str:
        mapping = {
            'http_request': 'http.request',
            'browser_script': 'browser.script',
            'shell_exec': 'shell.exec',
            'file_ops': 'filesystem.ops',
            'read_screen': 'desktop.capture',
            'open_app': 'desktop.app',
            'focus_window': 'desktop.window',
            'type_text': 'desktop.input',
            'click': 'desktop.input',
            'move_mouse': 'desktop.input',
            'clipboard_read': 'desktop.clipboard',
            'clipboard_write': 'desktop.clipboard',
            'wait': 'runtime.wait',
        }
        return mapping.get(action, 'desktop.action')


planner_service = PlannerService()
