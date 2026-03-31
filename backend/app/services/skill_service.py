from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from app.core.settings import settings
from app.models.schemas import (
    SkillCatalogBootstrapRequest,
    SkillComposeRequest,
    SkillManifest,
    SkillRunRequest,
    SkillRunResult,
    SkillSearchRequest,
    SkillWorkflowStep,
)


class SkillService:
    def __init__(self) -> None:
        self._skills_dir = settings.data_dir / 'skills'
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._skills_dir / 'index.json'
        self._stats_path = self._skills_dir / 'stats.json'
        self._cache: dict[str, SkillManifest] = {}
        self._index: dict[str, str] = {}
        self._stats: dict[str, dict[str, float | int]] = {}
        self._cache_loaded = False

        self._load_index()
        self._load_stats()
        self._ensure_seed_catalog()

    def list_skills(self) -> list[SkillManifest]:
        self._ensure_cache_loaded()
        manifests = [self._materialize_with_stats(item) for item in self._cache.values()]
        manifests.sort(key=lambda item: (item.quality_score, item.skill_id), reverse=True)
        return manifests

    def register_skill(self, manifest: SkillManifest) -> SkillManifest:
        self._ensure_cache_loaded()
        normalized = self._normalize_manifest(manifest)
        rel_path = self._manifest_rel_path(normalized.skill_id, normalized.namespace)
        full_path = self._skills_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(json.dumps(normalized.model_dump(mode='json'), indent=2, ensure_ascii=True), encoding='utf-8')

        self._index[normalized.skill_id] = rel_path
        self._cache[normalized.skill_id] = normalized
        self._save_index()

        if normalized.skill_id not in self._stats:
            self._stats[normalized.skill_id] = {'success': 0, 'failure': 0, 'avg_latency_ms': 0.0, 'feedback_score': 0.0}
            self._save_stats()
        return normalized

    def search_skills(self, request: SkillSearchRequest) -> list[SkillManifest]:
        self._ensure_cache_loaded()
        query = request.query.strip().lower()
        local = self.list_skills()

        if not query:
            local_hits = local[: max(1, min(request.limit, 200))]
        else:
            tokens = [t for t in re.split(r'[^a-z0-9_]+', query) if t]
            scored: list[tuple[float, SkillManifest]] = []
            for manifest in local:
                haystack = ' '.join(
                    [
                        manifest.skill_id.lower(),
                        manifest.description.lower(),
                        manifest.namespace.lower(),
                        ' '.join(manifest.capabilities).lower(),
                        ' '.join(manifest.tags).lower(),
                        ' '.join(manifest.aliases).lower(),
                        manifest.source.lower(),
                        manifest.kind.lower(),
                    ]
                )
                score = 0.0
                if query in haystack:
                    score += 3.0
                for token in tokens:
                    if token in manifest.skill_id.lower():
                        score += 1.8
                    elif token in haystack:
                        score += 1.0
                score += manifest.quality_score * 0.8
                score += manifest.feedback_score * 0.2
                if manifest.success_count > 0:
                    fail_penalty = manifest.failure_count / max(manifest.success_count + manifest.failure_count, 1)
                    score += (1 - fail_penalty) * 0.7
                if score > 0:
                    scored.append((score, manifest))

            scored.sort(key=lambda item: item[0], reverse=True)
            local_hits = [item[1] for item in scored[: max(1, min(request.limit, 200))]]

        if not request.include_virtual:
            return local_hits[: request.limit]

        missing = max(request.limit - len(local_hits), 0)
        virtual_hits = self._virtual_skill_matches(query=query, limit=missing)
        return (local_hits + virtual_hits)[: request.limit]

    def compose_skill(self, request: SkillComposeRequest) -> SkillManifest:
        if not request.steps:
            raise ValueError('compose_skill requires at least one workflow step')

        capabilities = list(dict.fromkeys(request.capabilities + ['workflow', 'orchestration']))
        normalized_tags = sorted({item.strip().lower() for item in request.tags if item.strip()})
        namespace = self._namespace_from_skill_id(request.skill_id)
        manifest = SkillManifest(
            skill_id=request.skill_id,
            version=request.version,
            description=request.description,
            capabilities=capabilities,
            risk_level=request.risk_level,
            kind='EXECUTABLE',
            namespace=namespace,
            workflow=request.steps,
            tags=normalized_tags,
            source='composed',
            quality_score=0.62,
        )
        return self.register_skill(manifest)

    def bootstrap_catalog(self, request: SkillCatalogBootstrapRequest) -> dict[str, int | str]:
        target = max(10, min(request.target_count, 50000))
        prefix = (request.prefix or 'autogen').strip().lower() or 'autogen'
        existing_ids = {item.skill_id for item in self.list_skills()}
        created = 0

        domains = [
            'research',
            'ops',
            'security',
            'finance',
            'sales',
            'support',
            'analytics',
            'developer',
            'compliance',
            'quality',
        ]
        verbs = [
            'scan',
            'analyze',
            'monitor',
            'summarize',
            'verify',
            'optimize',
            'triage',
            'report',
            'forecast',
            'synchronize',
            'detect',
            'score',
            'prioritize',
            'aggregate',
            'enrich',
        ]
        objects = [
            'events',
            'logs',
            'tickets',
            'tasks',
            'apis',
            'pipelines',
            'incidents',
            'costs',
            'latency',
            'risks',
            'signals',
            'alerts',
            'workflows',
            'metrics',
            'changes',
        ]

        counter = 0
        shard = 0
        while len(existing_ids) < target:
            progressed = False
            for domain in domains:
                for verb in verbs:
                    for obj in objects:
                        if len(existing_ids) >= target:
                            break
                        skill_id = f'{prefix}_{domain}_{verb}_{obj}_{shard:03d}_{counter:05d}'
                        counter += 1
                        if skill_id in existing_ids:
                            continue
                        manifest = SkillManifest(
                            skill_id=skill_id,
                            version='1.0.0',
                            description=f'{verb.title()} {obj} for {domain} workflows.',
                            capabilities=[verb, obj, domain, 'automation'],
                            risk_level='LOW',
                            kind='VIRTUAL',
                            namespace=prefix,
                            source='catalog_bootstrap',
                            tags=[domain, verb, obj],
                            aliases=[f'{verb}_{obj}', f'{domain}_{verb}'],
                            quality_score=0.45,
                        )
                        self.register_skill(manifest)
                        existing_ids.add(skill_id)
                        created += 1
                        progressed = True
                    if len(existing_ids) >= target:
                        break
                if len(existing_ids) >= target:
                    break
            if not progressed:
                break
            shard += 1

        return {'created': created, 'total': len(existing_ids), 'target': target, 'prefix': prefix}

    def run_skill(self, request: SkillRunRequest) -> SkillRunResult:
        if len(json.dumps(request.payload, ensure_ascii=True)) > settings.max_action_payload_chars:
            return SkillRunResult(skill_id=request.skill_id, success=False, error='Skill payload exceeds max_action_payload_chars')

        self._ensure_cache_loaded()
        manifest = self._cache.get(request.skill_id)
        if not manifest:
            virtual = self._resolve_virtual_skill(request.skill_id)
            if virtual:
                result = self._run_virtual_skill(skill=virtual, request=request)
                self._update_stats(virtual.skill_id, success=result.success, latency_ms=1)
                return result
            return SkillRunResult(skill_id=request.skill_id, success=False, error='Skill not found')

        if manifest.risk_level == 'HIGH' and not bool(request.payload.get('approved', False)):
            return SkillRunResult(skill_id=request.skill_id, success=False, error='High-risk skill requires explicit approval flag')

        started = time.perf_counter()
        if manifest.workflow:
            result = self._run_workflow_skill(manifest=manifest, request=request)
        elif manifest.entrypoint:
            result = self._run_entrypoint(manifest, request)
        else:
            result = SkillRunResult(
                skill_id=request.skill_id,
                success=True,
                output={
                    'skill_id': manifest.skill_id,
                    'version': manifest.version,
                    'kind': manifest.kind,
                    'namespace': manifest.namespace,
                    'capabilities': manifest.capabilities,
                    'payload': request.payload,
                    'note': 'Skill runtime scaffold executed capability contract.',
                },
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self._update_stats(manifest.skill_id, success=result.success, latency_ms=elapsed_ms)
        self._refresh_quality(manifest.skill_id)
        return result

    def _run_workflow_skill(self, manifest: SkillManifest, request: SkillRunRequest) -> SkillRunResult:
        run_trace: list[dict[str, object]] = []
        step_payload = request.payload if isinstance(request.payload, dict) else {}
        for idx, step in enumerate(manifest.workflow):
            payload = dict(step.payload)
            payload.update(step_payload)
            nested = self.run_skill(SkillRunRequest(skill_id=step.skill_id, payload=payload))
            run_trace.append(
                {
                    'step': idx + 1,
                    'skill_id': step.skill_id,
                    'success': nested.success,
                    'error': nested.error,
                    'output': nested.output,
                }
            )
            if not nested.success and step.required:
                return SkillRunResult(
                    skill_id=manifest.skill_id,
                    success=False,
                    output={'trace': run_trace},
                    error=f'Workflow step failed: {step.skill_id}',
                )

        return SkillRunResult(
            skill_id=manifest.skill_id,
            success=True,
            output={
                'skill_id': manifest.skill_id,
                'workflow_steps': len(manifest.workflow),
                'trace': run_trace,
                'note': 'Workflow skill executed composed steps.',
            },
        )

    def _run_entrypoint(self, manifest: SkillManifest, request: SkillRunRequest) -> SkillRunResult:
        entry = Path(str(manifest.entrypoint)).expanduser().resolve()
        if not entry.exists():
            return SkillRunResult(skill_id=manifest.skill_id, success=False, error=f'Entrypoint not found: {entry}')
        if self._skills_dir.resolve() not in entry.parents:
            return SkillRunResult(skill_id=manifest.skill_id, success=False, error='Entrypoint must live under skills directory')

        payload_json = json.dumps(request.payload, ensure_ascii=True)
        try:
            env = {
                'PATH': os.environ.get('PATH', ''),
                'JARVISX_SKILL_ID': manifest.skill_id,
            }
            result = subprocess.run(
                [sys.executable, '-I', str(entry), payload_json],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self._skills_dir),
                env=env,
            )
        except Exception as exc:
            return SkillRunResult(skill_id=manifest.skill_id, success=False, error=str(exc))

        output: dict[str, object] = {
            'stdout': result.stdout[:4000],
            'stderr': result.stderr[:4000],
            'returncode': result.returncode,
            'entrypoint': str(entry),
        }
        return SkillRunResult(skill_id=manifest.skill_id, success=result.returncode == 0, output=output, error=None if result.returncode == 0 else 'Skill entrypoint failed')

    def _update_stats(self, skill_id: str, success: bool, latency_ms: int) -> None:
        state = self._stats.setdefault(skill_id, {'success': 0, 'failure': 0, 'avg_latency_ms': 0.0, 'feedback_score': 0.0})
        if success:
            state['success'] = int(state.get('success', 0)) + 1
        else:
            state['failure'] = int(state.get('failure', 0)) + 1

        prev_avg = float(state.get('avg_latency_ms', 0.0))
        count = int(state.get('success', 0)) + int(state.get('failure', 0))
        state['avg_latency_ms'] = round(((prev_avg * max(count - 1, 0)) + latency_ms) / max(count, 1), 2)
        self._save_stats()

    def _refresh_quality(self, skill_id: str) -> None:
        manifest = self._cache.get(skill_id)
        if not manifest:
            return
        stats = self._stats.get(skill_id, {})
        success = int(stats.get('success', 0))
        failure = int(stats.get('failure', 0))
        total = success + failure
        pass_rate = success / total if total > 0 else 0.5

        latency = float(stats.get('avg_latency_ms', 0.0))
        latency_factor = 1.0 if latency <= 1 else max(0.25, min(1.0, 1200 / max(latency, 200.0)))
        feedback = float(stats.get('feedback_score', 0.0))

        manifest.success_count = success
        manifest.failure_count = failure
        manifest.avg_latency_ms = latency
        manifest.feedback_score = feedback
        manifest.quality_score = round((pass_rate * 0.7) + (latency_factor * 0.2) + (max(min(feedback, 1.0), -1.0) * 0.1), 3)
        self.register_skill(manifest)

    def _ensure_cache_loaded(self) -> None:
        if self._cache_loaded:
            return
        self._load_index()
        self._cache = {}

        if self._index:
            for skill_id, rel_path in self._index.items():
                path = self._skills_dir / rel_path
                if not path.exists():
                    continue
                try:
                    raw = json.loads(path.read_text(encoding='utf-8'))
                    self._cache[skill_id] = self._normalize_manifest(SkillManifest.model_validate(raw))
                except Exception:
                    continue
        else:
            for file in self._skills_dir.rglob('*.json'):
                if file.name in {'index.json', 'stats.json'}:
                    continue
                try:
                    raw = json.loads(file.read_text(encoding='utf-8'))
                    manifest = self._normalize_manifest(SkillManifest.model_validate(raw))
                except Exception:
                    continue
                self._cache[manifest.skill_id] = manifest
                self._index[manifest.skill_id] = str(file.relative_to(self._skills_dir))
            self._save_index()

        self._cache_loaded = True

    def _load_index(self) -> None:
        if not self._index_path.exists():
            self._index = {}
            return
        try:
            raw = json.loads(self._index_path.read_text(encoding='utf-8'))
            self._index = {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
        except Exception:
            self._index = {}

    def _save_index(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=2, ensure_ascii=True), encoding='utf-8')

    def _load_stats(self) -> None:
        if not self._stats_path.exists():
            self._stats = {}
            return
        try:
            raw = json.loads(self._stats_path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                self._stats = raw
            else:
                self._stats = {}
        except Exception:
            self._stats = {}

    def _save_stats(self) -> None:
        self._stats_path.write_text(json.dumps(self._stats, indent=2, ensure_ascii=True), encoding='utf-8')

    @staticmethod
    def _manifest_rel_path(skill_id: str, namespace: str) -> str:
        digest = hashlib.sha1(skill_id.encode('utf-8')).hexdigest()
        safe_ns = re.sub(r'[^a-z0-9_.-]+', '_', namespace.lower()) or 'default'
        return str(Path(safe_ns) / digest[:2] / f'{digest}.json')

    @staticmethod
    def _namespace_from_skill_id(skill_id: str) -> str:
        token = re.split(r'[:_]', skill_id.lower())[0]
        return token or 'default'

    def _materialize_with_stats(self, manifest: SkillManifest) -> SkillManifest:
        stats = self._stats.get(manifest.skill_id, {})
        manifest.success_count = int(stats.get('success', manifest.success_count))
        manifest.failure_count = int(stats.get('failure', manifest.failure_count))
        manifest.avg_latency_ms = float(stats.get('avg_latency_ms', manifest.avg_latency_ms))
        manifest.feedback_score = float(stats.get('feedback_score', manifest.feedback_score))
        return manifest

    @staticmethod
    def _normalize_manifest(manifest: SkillManifest) -> SkillManifest:
        if not manifest.namespace:
            manifest.namespace = SkillService._namespace_from_skill_id(manifest.skill_id)
        if manifest.kind == 'VIRTUAL':
            manifest.entrypoint = None
        return manifest

    @staticmethod
    def _virtual_skill_matches(query: str, limit: int) -> list[SkillManifest]:
        if limit <= 0:
            return []

        domains = ['research', 'ops', 'security', 'sales', 'support', 'analytics', 'dev', 'compliance']
        actions = ['scan', 'analyze', 'summarize', 'monitor', 'optimize', 'verify', 'enrich', 'forecast']
        tokens = [token for token in re.split(r'[^a-z0-9_]+', query.lower()) if token]
        if tokens:
            domains = [item for item in domains if any(token in item for token in tokens)] or domains
            actions = [item for item in actions if any(token in item for token in tokens)] or actions

        virtual: list[SkillManifest] = []
        for domain in domains:
            for action in actions:
                if len(virtual) >= limit:
                    return virtual
                virtual.append(
                    SkillManifest(
                        skill_id=f'virtual::{domain}::{action}',
                        version='1.0.0',
                        description=f'Virtual skill ({action}) for {domain} pipelines.',
                        capabilities=[action, domain, 'virtual'],
                        risk_level='LOW',
                        kind='VIRTUAL',
                        namespace='virtual',
                        source='virtual',
                        tags=[domain, action, 'virtual'],
                        quality_score=0.35,
                    )
                )
        return virtual

    @staticmethod
    def _resolve_virtual_skill(skill_id: str) -> SkillManifest | None:
        parts = skill_id.split('::')
        if len(parts) != 3 or parts[0] != 'virtual':
            return None
        domain, action = parts[1], parts[2]
        if not domain or not action:
            return None
        return SkillManifest(
            skill_id=skill_id,
            version='1.0.0',
            description=f'Virtual skill ({action}) for {domain} domain.',
            capabilities=[action, domain, 'virtual'],
            risk_level='LOW',
            kind='VIRTUAL',
            namespace='virtual',
            source='virtual',
            tags=[domain, action, 'virtual'],
            quality_score=0.33,
        )

    @staticmethod
    def _run_virtual_skill(skill: SkillManifest, request: SkillRunRequest) -> SkillRunResult:
        return SkillRunResult(
            skill_id=skill.skill_id,
            success=True,
            output={
                'skill_id': skill.skill_id,
                'virtual': True,
                'domain': skill.tags[0] if skill.tags else '',
                'action': skill.tags[1] if len(skill.tags) > 1 else '',
                'payload': request.payload,
                'note': 'Virtual skill scaffold executed. Bind this ID to a concrete entrypoint for production action.',
            },
        )

    def _ensure_seed_catalog(self) -> None:
        existing = {item.skill_id for item in self.list_skills()}
        if 'workflow_summarizer' not in existing:
            self.register_skill(
                SkillManifest(
                    skill_id='workflow_summarizer',
                    version='1.0.0',
                    description='Summarizes completed workflow traces into reusable playbooks.',
                    capabilities=['summarize', 'playbook_generation'],
                    risk_level='LOW',
                    namespace='core',
                    tags=['core', 'summary'],
                    source='seed',
                    quality_score=0.8,
                )
            )
        if 'mission_controller' not in existing:
            self.register_skill(
                SkillManifest(
                    skill_id='mission_controller',
                    version='1.0.0',
                    description='Coordinates search, analysis, and reporting skills as a workflow.',
                    capabilities=['orchestration', 'workflow', 'coordination'],
                    risk_level='MEDIUM',
                    namespace='core',
                    source='seed',
                    tags=['core', 'workflow'],
                    quality_score=0.78,
                    workflow=[
                        SkillWorkflowStep(skill_id='workflow_summarizer', payload={'mode': 'brief'}, required=True),
                    ],
                )
            )


skill_service = SkillService()
