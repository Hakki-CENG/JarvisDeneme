from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.models.schemas import ImprovementProposal, SelfImproveReport, SkillManifest
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


self_improvement_service = SelfImprovementService()
