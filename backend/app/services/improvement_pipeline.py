from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
import importlib.util


@dataclass
class PipelineResult:
    branch: str
    tests_ok: bool
    lint_ok: bool
    details: list[str]


class ImprovementPipeline:
    def __init__(self, repo_root: str = '.') -> None:
        self.repo_root = repo_root

    def run(self) -> PipelineResult:
        timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        branch_name = f'codex/auto-improve-{timestamp}'

        details: list[str] = []
        if self._is_git_repo():
            self._run_cmd(['git', 'checkout', '-b', branch_name], details)
        else:
            details.append('git repository not detected; branch creation skipped')
        if self._has_module('pytest'):
            tests_ok = self._run_cmd([sys.executable, '-m', 'pytest', '-q'], details)
        else:
            details.append('pytest is not installed; test stage skipped')
            tests_ok = False
        lint_ok = self._run_cmd([sys.executable, '-m', 'compileall', 'app'], details)

        return PipelineResult(branch=branch_name, tests_ok=tests_ok, lint_ok=lint_ok, details=details)

    def _is_git_repo(self) -> bool:
        result = subprocess.run(
            ['git', 'rev-parse', '--is-inside-work-tree'],
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return result.returncode == 0

    @staticmethod
    def _has_module(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    def _run_cmd(self, cmd: list[str], details: list[str]) -> bool:
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except Exception as exc:
            details.append(f"{' '.join(cmd)} -> failed to run: {exc}")
            return False

        details.append(f"{' '.join(cmd)} -> rc={result.returncode}")
        if result.stdout.strip():
            details.append(result.stdout.strip()[:1000])
        if result.stderr.strip():
            details.append(result.stderr.strip()[:1000])
        return result.returncode == 0


improvement_pipeline = ImprovementPipeline(repo_root='.')
