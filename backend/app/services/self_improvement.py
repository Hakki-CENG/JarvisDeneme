from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re

from app.models.schemas import CodeInsightItem, ImprovementProposal, SelfImproveReport, SkillCatalogBootstrapRequest, SkillManifest
from app.services.audit_service import audit_service
from app.services.improvement_pipeline import improvement_pipeline
from app.services.memory_service import memory_service
from app.services.repositories import repositories
from app.services.skill_service import skill_service


class SelfImprovementService:
    def run(self, focus: str = 'all') -> SelfImproveReport:
        report = SelfImproveReport(status='RUNNING')
        repositories['self_improve'].save(report)

        findings: list[ImprovementProposal] = []
        tasks = repositories['tasks'].list_all()
        traces = [trace for task in tasks for trace in repositories['traces'].list_by_task(task.spec.id)]
        focus_normalized = focus.strip().lower()

        failed_tasks = [task for task in tasks if task.status.value == 'FAILED']
        if failed_tasks:
            findings.append(
                ImprovementProposal(
                    gap='Frequent failures in high-risk desktop operations',
                    proposal='Add pre-execution simulation and richer rollback scripts before real execution.',
                    expected_impact='Lower failure rate and safer autonomous operation.',
                )
            )

        waiting_approval = [task for task in tasks if task.status.value == 'WAITING_APPROVAL']
        if waiting_approval:
            findings.append(
                ImprovementProposal(
                    gap='Approval wait is slowing throughput',
                    proposal='Introduce grouped approval bundles for related low-level actions.',
                    expected_impact='Reduced interaction friction without bypassing user control.',
                )
            )

        audits = audit_service.latest(limit=200)
        auth_fail_count = sum(1 for item in audits if item.get('action') == 'auth_failed')
        if auth_fail_count >= 10:
            findings.append(
                ImprovementProposal(
                    gap='Frequent auth failures observed in audit logs',
                    proposal='Add temporary token lockout and IP cooldown for brute-force mitigation.',
                    expected_impact='Lower attack surface and cleaner audit noise.',
                )
            )

        if traces:
            agent_counts = Counter(trace.agent for trace in traces)
            top_agent, top_count = agent_counts.most_common(1)[0]
            findings.append(
                ImprovementProposal(
                    gap=f'Execution load concentrated on agent={top_agent}',
                    proposal='Introduce adaptive routing to balance agent responsibilities per task type.',
                    expected_impact=f'More stable reasoning quality under high load (observed {top_count} traces).',
                )
            )

        code_findings = self.code_insights(max_items=40)
        if code_findings:
            findings.append(
                ImprovementProposal(
                    gap=f'Codebase contains {len(code_findings)} maintainability/security hints',
                    proposal='Prioritize high severity code insights and apply targeted refactors.',
                    expected_impact='Higher long-term stability and faster autonomous iteration.',
                )
            )

        if not findings:
            findings.append(
                ImprovementProposal(
                    gap='No urgent operational gaps detected',
                    proposal='Add domain-specific skills from previous successful task traces.',
                    expected_impact='Higher first-pass success rate for similar tasks.',
                )
            )

        report.findings = findings
        pipeline = improvement_pipeline.run()
        report.tests_passed = pipeline.tests_ok and pipeline.lint_ok
        report.risk_summary = (
            'No automatic merge performed. User approval required for integration. '
            f'Candidate branch: {pipeline.branch}'
        )
        report.actions = ['Generated improvement proposals', f'Prepared candidate branch: {pipeline.branch}'] + pipeline.details

        created_from_tasks = self._mine_skills_from_success_tasks(tasks)
        if created_from_tasks > 0:
            report.actions.append(f'Auto-registered skills from successful task patterns: {created_from_tasks}')

        current_skill_total = len(skill_service.list_skills())
        if focus_normalized in {'all', 'skills', 'scale', 'jarvis'} and current_skill_total < 5000:
            bootstrap = skill_service.bootstrap_catalog(SkillCatalogBootstrapRequest(target_count=5000, prefix='jarvis'))
            report.actions.append(f"Skill catalog scaled: +{bootstrap['created']} (total={bootstrap['total']})")

        generated_dir = Path('.jarvisx_data/improvement_artifacts')
        generated_dir.mkdir(parents=True, exist_ok=True)
        summary_path = generated_dir / f'self_improve_{report.id}.md'
        summary_lines = ['# Self Improvement Report', f'Report ID: {report.id}', f'Focus: {focus}', '']
        for finding in findings:
            summary_lines.extend(
                [
                    f'## Gap: {finding.gap}',
                    f'- Proposal: {finding.proposal}',
                    f'- Expected Impact: {finding.expected_impact}',
                    '',
                ]
            )
        summary_lines.append('## Pipeline')
        summary_lines.extend([f'- {line}' for line in pipeline.details])
        if code_findings:
            summary_lines.append('')
            summary_lines.append('## Code Insights')
            for item in code_findings[:25]:
                summary_lines.append(f'- [{item.severity}] {item.file}:{item.line} -> {item.issue} | {item.suggestion}')
        summary_path.write_text('\\n'.join(summary_lines), encoding='utf-8')
        report.actions.append(f'Wrote artifact: {summary_path}')
        memory_service.upsert(
            key=f'self-improve:{report.id}',
            content='\\n'.join(summary_lines)[:4000],
            tags=['self_improve', focus, report.status.lower()],
        )

        # Ensure a reusable optimization skill exists after each run.
        existing = {skill.skill_id for skill in skill_service.list_skills()}
        if 'auto_optimizer' not in existing:
            skill_service.register_skill(
                manifest=SkillManifest(
                    skill_id='auto_optimizer',
                    version='1.0.0',
                    description='Analyzes traces and suggests optimization deltas for future runs.',
                    capabilities=['trace_analysis', 'optimization_proposal'],
                    risk_level='LOW',
                )
            )
            report.actions.append('Registered skill: auto_optimizer')

        report.status = 'COMPLETED'
        report.ended_at = datetime.now(timezone.utc)

        repositories['self_improve'].save(report)
        return report

    def get_report(self, report_id: str) -> SelfImproveReport | None:
        return repositories['self_improve'].get(report_id)

    @staticmethod
    def code_insights(max_items: int = 40) -> list[CodeInsightItem]:
        target_limit = max(1, min(max_items, 400))
        roots = [Path('app'), Path('frontend/src'), Path('../frontend/src')]
        patterns = [
            (re.compile(r'\bTODO\b', re.IGNORECASE), 'TODO marker found', 'LOW', 'Convert TODO into tracked issue or implement directly.'),
            (re.compile(r'\bFIXME\b', re.IGNORECASE), 'FIXME marker found', 'MEDIUM', 'Resolve or guard with explicit fallback behavior.'),
            (re.compile(r'except\s+Exception\s*:\s*pass'), 'Silent exception swallow', 'HIGH', 'Log the exception or return explicit error path.'),
            (re.compile(r'while\s+True\s*:'), 'Potential infinite loop', 'MEDIUM', 'Ensure bounded sleeps, cancellation, and health logging.'),
            (re.compile(r'subprocess\.(Popen|run)\(.*shell=True'), 'Shell execution with shell=True', 'HIGH', 'Prefer argument arrays and strict policy validation.'),
        ]

        items: list[CodeInsightItem] = []
        for root in roots:
            if not root.exists():
                continue
            for file in root.rglob('*'):
                if file.suffix not in {'.py', '.ts', '.tsx'}:
                    continue
                try:
                    lines = file.read_text(encoding='utf-8').splitlines()
                except Exception:
                    continue
                for line_no, line in enumerate(lines, start=1):
                    for regex, issue, severity, suggestion in patterns:
                        if regex.search(line):
                            items.append(
                                CodeInsightItem(
                                    file=str(file),
                                    line=line_no,
                                    issue=issue,
                                    severity=severity,  # type: ignore[arg-type]
                                    suggestion=suggestion,
                                )
                            )
                            break
                    if len(items) >= target_limit:
                        return items
        return items

    @staticmethod
    def _mine_skills_from_success_tasks(tasks: list) -> int:
        existing = {skill.skill_id for skill in skill_service.list_skills()}
        created = 0
        for task in tasks:
            if task.status.value != 'COMPLETED':
                continue
            objective = (task.spec.objective or '').strip()
            if not objective:
                continue
            normalized = re.sub(r'[^a-z0-9]+', '_', objective.lower()).strip('_')
            if not normalized:
                continue
            skill_id = f'task_skill_{normalized[:48]}'
            if skill_id in existing:
                continue
            manifest = SkillManifest(
                skill_id=skill_id,
                version='1.0.0',
                description=f'Auto-generated skill from successful objective: {objective[:180]}',
                capabilities=['autogenerated', 'task_pattern', 'execution'],
                risk_level='LOW',
                source='task_mining',
                tags=['autogen', 'task', 'success'],
                aliases=[normalized[:24]],
                quality_score=0.58,
            )
            skill_service.register_skill(manifest)
            existing.add(skill_id)
            created += 1
            if created >= 200:
                break
        return created


self_improvement_service = SelfImprovementService()
