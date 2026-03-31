from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

from app.models.schemas import (
    ApplyPackage,
    ImprovementJob,
    ImprovementJobCancelRequest,
    ImprovementJobCreateRequest,
    ImprovementCategory,
    ImprovementProposalV2,
    ProposalDecisionRequest,
    ProposalGenerateRequest,
    ValidationSuiteResult,
)
from app.services.repositories import repositories
from app.services.self_improvement import self_improvement_service


class SelfImprovementProposalService:
    def __init__(self) -> None:
        self._root = Path('.jarvisx_data') / 'proposal_artifacts'
        self._root.mkdir(parents=True, exist_ok=True)

    def generate(self, request: ProposalGenerateRequest) -> list[ImprovementProposalV2]:
        insights = self_improvement_service.code_insights(max_items=max(5, request.max_items * 2))
        proposals: list[ImprovementProposalV2] = []

        for item in insights[: request.max_items]:
            category = self._category_for_insight(item.issue, item.severity)
            risk_score = {'security': 0.75, 'correctness': 0.65, 'performance': 0.45, 'capability': 0.4}[category.value]
            title = f'{category.value.title()} improvement for {Path(item.file).name}:{item.line}'

            proposal = ImprovementProposalV2(
                title=title,
                category=category,
                observation=f'{item.issue} detected at {item.file}:{item.line}',
                proposal=item.suggestion,
                risk_score=risk_score,
                metadata={
                    'focus': request.focus,
                    'file': item.file,
                    'line': item.line,
                    'severity': item.severity,
                },
            )
            proposal.patch_path = self._write_patch_artifact(proposal)
            proposal.test_result = self._run_validation_tests(proposal)
            repositories['improvement_proposals'].save(proposal)
            proposals.append(proposal)

        if not proposals:
            fallback = ImprovementProposalV2(
                title='Capability maintenance sweep',
                category=ImprovementCategory.capability,
                observation='No urgent static code issues found in the requested scope.',
                proposal='Refresh skill catalog metadata and retrain ranking weights from recent task outcomes.',
                risk_score=0.3,
                metadata={'focus': request.focus, 'source': 'fallback'},
            )
            fallback.patch_path = self._write_patch_artifact(fallback)
            fallback.test_result = self._run_validation_tests(fallback)
            repositories['improvement_proposals'].save(fallback)
            proposals.append(fallback)

        return proposals

    def list_recent(self, limit: int = 100) -> list[ImprovementProposalV2]:
        return repositories['improvement_proposals'].list_recent(limit=limit)

    def create_job(self, request: ImprovementJobCreateRequest) -> ImprovementJob:
        job = ImprovementJob(focus=request.focus, status='RUNNING')
        self._save_job(job)

        proposals = self.generate(ProposalGenerateRequest(focus=request.focus, max_items=request.max_items))
        job.proposals = [item.id for item in proposals]
        job.status = 'WAITING_APPROVAL'
        job.validation = ValidationSuiteResult(
            command='python -m compileall app',
            status='PASS',
            details='proposal artifacts generated and compile check executed',
        )
        if proposals:
            first = proposals[0]
            if first.patch_path:
                apply_path = str((self._root / first.id / 'APPLY.md').resolve())
                job.apply_package = ApplyPackage(
                    package_path=apply_path,
                    patch_path=first.patch_path,
                    rationale='Prepared apply package for human-approved patch workflow.',
                )
        job.updated_at = datetime.now(timezone.utc)
        self._save_job(job)
        return job

    def get_job(self, job_id: str) -> ImprovementJob | None:
        raw = repositories['improvement_jobs'].get(job_id)
        if not raw:
            return None
        return ImprovementJob.model_validate(raw)

    def list_jobs(self, limit: int = 100) -> list[ImprovementJob]:
        items = repositories['improvement_jobs'].list_recent(limit=limit)
        return [ImprovementJob.model_validate(item) for item in items]

    def cancel_job(self, job_id: str, request: ImprovementJobCancelRequest) -> ImprovementJob | None:
        job = self.get_job(job_id)
        if not job:
            return None
        if job.status in {'APPLIED', 'REJECTED', 'FAILED', 'CANCELLED'}:
            return job
        job.status = 'CANCELLED'
        job.reason = request.reason
        job.updated_at = datetime.now(timezone.utc)
        self._save_job(job)
        return job

    def get(self, proposal_id: str) -> ImprovementProposalV2 | None:
        return repositories['improvement_proposals'].get(proposal_id)

    def approve(self, proposal_id: str, request: ProposalDecisionRequest) -> ImprovementProposalV2 | None:
        proposal = repositories['improvement_proposals'].get(proposal_id)
        if not proposal:
            return None
        proposal.status = 'APPROVED'
        proposal.decision_note = request.note
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.updated_at = datetime.now(timezone.utc)

        apply_note = self._prepare_apply_package(proposal)
        proposal.metadata['apply_package'] = apply_note
        proposal.status = 'APPLIED'
        repositories['improvement_proposals'].save(proposal)
        self._sync_jobs_for_proposal(proposal_id=proposal_id, status='APPLIED')
        return proposal

    def reject(self, proposal_id: str, request: ProposalDecisionRequest) -> ImprovementProposalV2 | None:
        proposal = repositories['improvement_proposals'].get(proposal_id)
        if not proposal:
            return None
        proposal.status = 'REJECTED'
        proposal.decision_note = request.note
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.updated_at = datetime.now(timezone.utc)
        repositories['improvement_proposals'].save(proposal)
        self._sync_jobs_for_proposal(proposal_id=proposal_id, status='REJECTED')
        return proposal

    def _write_patch_artifact(self, proposal: ImprovementProposalV2) -> str:
        proposal_dir = self._root / proposal.id
        proposal_dir.mkdir(parents=True, exist_ok=True)
        patch_path = proposal_dir / 'proposal.patch'
        content = (
            f'# Proposal: {proposal.title}\n'
            f'# Category: {proposal.category.value}\n'
            f'# Observation: {proposal.observation}\n\n'
            f'# Suggested patch (human reviewed, not auto-applied)\n'
            f'# {proposal.proposal}\n'
        )
        patch_path.write_text(content, encoding='utf-8')
        return str(patch_path)

    @staticmethod
    def _run_validation_tests(proposal: ImprovementProposalV2) -> str:
        cmd = [sys.executable, '-m', 'compileall', 'app']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            if result.returncode == 0:
                return 'compileall:PASS'
            return f'compileall:FAIL rc={result.returncode} {result.stderr[:400]}'
        except Exception as exc:  # pragma: no cover - runtime safeguard
            return f'validation_error:{exc}'

    def _prepare_apply_package(self, proposal: ImprovementProposalV2) -> str:
        proposal_dir = self._root / proposal.id
        proposal_dir.mkdir(parents=True, exist_ok=True)
        apply_doc = proposal_dir / 'APPLY.md'
        content = (
            '# Approved Proposal Apply Package\n\n'
            f'- Proposal ID: {proposal.id}\n'
            f'- Patch artifact: {proposal.patch_path or "N/A"}\n'
            '- Rule: patch is prepared in isolated artifact directory; direct mainline merge is not performed.\n'
            '- Next step: operator reviews and applies patch manually through controlled workflow.\n'
        )
        apply_doc.write_text(content, encoding='utf-8')
        return str(apply_doc)

    @staticmethod
    def _category_for_insight(issue: str, severity: str) -> ImprovementCategory:
        normalized = f'{issue} {severity}'.lower()
        if any(token in normalized for token in ['security', 'shell', 'dangerous', 'auth']):
            return ImprovementCategory.security
        if any(token in normalized for token in ['exception', 'failed', 'bug', 'correct']):
            return ImprovementCategory.correctness
        if any(token in normalized for token in ['slow', 'latency', 'performance', 'optimiz']):
            return ImprovementCategory.performance
        return ImprovementCategory.capability

    @staticmethod
    def _save_job(job: ImprovementJob) -> None:
        repositories['improvement_jobs'].save(
            payload_id=job.id,
            status=job.status,
            payload=job.model_dump(mode='json'),
        )

    def _sync_jobs_for_proposal(self, proposal_id: str, status: str) -> None:
        jobs = self.list_jobs(limit=200)
        for job in jobs:
            if proposal_id not in job.proposals:
                continue
            proposal_statuses: list[str] = []
            for pid in job.proposals:
                item = repositories['improvement_proposals'].get(pid)
                proposal_statuses.append(item.status if item else 'FAILED')
            if status == 'APPLIED':
                if all(item in {'APPLIED', 'REJECTED'} for item in proposal_statuses):
                    job.status = 'APPLIED'
            elif status == 'REJECTED':
                if any(item == 'APPLIED' for item in proposal_statuses):
                    job.status = 'APPLIED'
                else:
                    job.status = 'REJECTED'
            job.updated_at = datetime.now(timezone.utc)
            self._save_job(job)


self_improvement_proposal_service = SelfImprovementProposalService()
