from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.core.settings import settings


@dataclass
class ShellPolicyResult:
    level: str
    reason: str


class PolicyService:
    def __init__(self) -> None:
        self._file_roots = self._parse_paths(settings.allowed_file_roots)
        self._safe_shell_prefixes = self._parse_csv(settings.safe_shell_prefixes)
        self._safe_app_prefixes = self._parse_csv(settings.safe_app_prefixes)
        self._blocked_shell_patterns = self._parse_csv(settings.blocked_shell_patterns)
        self._blocked_url_patterns = self._parse_csv(settings.blocked_url_patterns)
        self._allowed_http_methods = {item.strip().upper() for item in settings.allowed_http_methods.split(',') if item.strip()}
        self._hard_block_shell_regex = [
            re.compile(r'(^|\s)rm\s+-rf\s+(/|~|\*)'),
            re.compile(r'(^|\s)(del|erase)\s+/[fFsS].*'),
            re.compile(r'(^|\s)rd\s+/s\s+/q'),
            re.compile(r'(^|\s)(mkfs|dd\s+if=)'),
        ]

    @staticmethod
    def _parse_csv(raw: str) -> list[str]:
        return [item.strip().lower() for item in raw.split(',') if item.strip()]

    @staticmethod
    def _parse_paths(raw: str) -> list[Path]:
        roots: list[Path] = []
        for item in raw.split(','):
            item = item.strip()
            if not item:
                continue
            roots.append(Path(item).expanduser().resolve())
        return roots

    def is_path_allowed(self, path: str) -> bool:
        target = Path(path).expanduser().resolve()
        if not self._file_roots:
            return False
        for root in self._file_roots:
            if target == root or root in target.parents:
                return True
        return False

    @staticmethod
    def _split_shell_segments(command: str) -> tuple[list[str], list[str]]:
        # Split by common shell control operators; each segment is evaluated separately.
        operators = re.findall(r'(&&|\|\||;|\|)', command)
        parts = [chunk.strip() for chunk in re.split(r'(?:&&|\|\||;|\|)', command) if chunk.strip()]
        return parts, operators

    @staticmethod
    def _matches_prefix(command: str, prefix: str) -> bool:
        if command == prefix:
            return True
        return command.startswith(prefix + ' ')

    def evaluate_shell_command(self, command: str) -> ShellPolicyResult:
        cmd = command.strip().lower()
        if not cmd:
            return ShellPolicyResult(level='blocked', reason='Empty command')
        if len(cmd) > settings.max_shell_command_length:
            return ShellPolicyResult(level='blocked', reason='Command exceeds max_shell_command_length')

        if re.search(r'(`|\$\(|-enc\b|base64|invoke-expression|iex\b)', cmd):
            return ShellPolicyResult(level='blocked', reason='Encoded or obfuscated command pattern detected')

        for regex in self._hard_block_shell_regex:
            if regex.search(cmd):
                return ShellPolicyResult(level='blocked', reason='Hard blocked destructive shell pattern detected')

        segments, operators = self._split_shell_segments(cmd)
        if not segments:
            return ShellPolicyResult(level='blocked', reason='Command parsing produced no executable segment')

        for segment in segments:
            for pattern in self._blocked_shell_patterns:
                if pattern and pattern in segment:
                    return ShellPolicyResult(level='blocked', reason=f'Blocked pattern detected: {pattern}')

        risky_segments: list[str] = []
        for segment in segments:
            if any(self._matches_prefix(segment, prefix) for prefix in self._safe_shell_prefixes):
                continue
            risky_segments.append(segment)

        if risky_segments:
            return ShellPolicyResult(
                level='risky',
                reason=f'Command segment outside safe allowlist: {risky_segments[0][:80]}',
            )

        if '|' in operators:
            return ShellPolicyResult(level='risky', reason='Piped commands require explicit approval')

        return ShellPolicyResult(level='safe', reason='All command segments are allowlisted')

    def evaluate_app_command(self, app_command: str) -> ShellPolicyResult:
        cmd = app_command.strip().lower()
        if not cmd:
            return ShellPolicyResult(level='blocked', reason='Empty app command')

        if re.search(r'[`$;|]', cmd):
            return ShellPolicyResult(level='blocked', reason='App command contains shell control characters')

        for pattern in self._blocked_shell_patterns:
            if pattern and pattern in cmd:
                return ShellPolicyResult(level='blocked', reason=f'Blocked app pattern detected: {pattern}')

        for prefix in self._safe_app_prefixes:
            if self._matches_prefix(cmd, prefix):
                return ShellPolicyResult(level='safe', reason=f'Allowed by app prefix: {prefix}')

        return ShellPolicyResult(level='risky', reason='App command is outside safe app allowlist')

    def evaluate_http_request(self, method: str, url: str) -> ShellPolicyResult:
        normalized_method = method.strip().upper()
        if normalized_method not in self._allowed_http_methods:
            return ShellPolicyResult(level='blocked', reason=f'HTTP method not allowed: {normalized_method}')

        target = url.strip().lower()
        if not target:
            return ShellPolicyResult(level='blocked', reason='URL is empty')

        parsed = urlparse(target)
        if parsed.scheme not in {'http', 'https'}:
            return ShellPolicyResult(level='blocked', reason='Only http/https URLs are allowed')

        for pattern in self._blocked_url_patterns:
            if pattern and pattern in target:
                return ShellPolicyResult(level='blocked', reason=f'Blocked URL pattern: {pattern}')
        return ShellPolicyResult(level='safe', reason='HTTP request policy check passed')


policy_service = PolicyService()
