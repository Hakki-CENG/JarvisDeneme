from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

from app.core.settings import settings
from app.models.schemas import SkillManifest, SkillRunRequest, SkillRunResult


class SkillService:
    def __init__(self) -> None:
        self._skills_dir = settings.data_dir / 'skills'
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        if not any(self._skills_dir.glob('*.json')):
            self.register_skill(
                SkillManifest(
                    skill_id='workflow_summarizer',
                    version='1.0.0',
                    description='Summarizes completed workflow traces into reusable playbooks.',
                    capabilities=['summarize', 'playbook_generation'],
                    risk_level='LOW',
                )
            )

    def list_skills(self) -> list[SkillManifest]:
        manifests: list[SkillManifest] = []
        for file in sorted(self._skills_dir.glob('*.json')):
            try:
                raw = json.loads(file.read_text(encoding='utf-8'))
                manifests.append(SkillManifest.model_validate(raw))
            except Exception:
                continue
        return manifests

    def register_skill(self, manifest: SkillManifest) -> SkillManifest:
        file = self._skills_dir / f'{manifest.skill_id}.json'
        file.write_text(json.dumps(manifest.model_dump(mode='json'), indent=2, ensure_ascii=True), encoding='utf-8')
        return manifest

    def run_skill(self, request: SkillRunRequest) -> SkillRunResult:
        if len(json.dumps(request.payload, ensure_ascii=True)) > settings.max_action_payload_chars:
            return SkillRunResult(skill_id=request.skill_id, success=False, error='Skill payload exceeds max_action_payload_chars')

        manifests = {skill.skill_id: skill for skill in self.list_skills()}
        manifest = manifests.get(request.skill_id)
        if not manifest:
            return SkillRunResult(skill_id=request.skill_id, success=False, error='Skill not found')

        if manifest.risk_level == 'HIGH' and not bool(request.payload.get('approved', False)):
            return SkillRunResult(skill_id=request.skill_id, success=False, error='High-risk skill requires explicit approval flag')

        if manifest.entrypoint:
            return self._run_entrypoint(manifest, request)

        output = {
            'skill_id': manifest.skill_id,
            'version': manifest.version,
            'capabilities': manifest.capabilities,
            'payload': request.payload,
            'note': 'Skill runtime scaffold executed capability contract.',
        }
        return SkillRunResult(skill_id=request.skill_id, success=True, output=output)

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


skill_service = SkillService()
