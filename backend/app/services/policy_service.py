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
    policy_id: str = ''


@dataclass(frozen=True)
class PolicyProfile:
    name: str
    block_pipe_operator: bool
    treat_unknown_shell_as_blocked: bool
    allow_unknown_http_domain: bool


class PolicyService:
    def __init__(self) -> None:
        self._profile = self._resolve_profile(settings.policy_profile)
        self._file_roots = self._parse_paths(settings.allowed_file_roots)
        self._safe_shell_prefixes = self._parse_csv(settings.safe_shell_prefixes)
        self._safe_app_prefixes = self._parse_csv(settings.safe_app_prefixes)
        self._blocked_shell_patterns = self._parse_csv(settings.blocked_shell_patterns)
        self._blocked_url_patterns = self._parse_csv(settings.blocked_url_patterns)
        self._allowed_http_domains = self._parse_csv(settings.allowed_http_domains)
        self._allowed_http_methods = {item.strip().upper() for item in settings.allowed_http_methods.split(',') if item.strip()}
        self._hard_block_shell_regex = [
            re.compile(r'(^|\s)rm\s+-rf\s+(/|~|\*)'),
            re.compile(r'(^|\s)(del|erase)\s+/[fFsS].*'),
            re.compile(r'(^|\s)rd\s+/s\s+/q'),
            re.compile(r'(^|\s)(mkfs|dd\s+if=)'),
        ]

    @staticmethod
    def _resolve_profile(profile_name: str) -> PolicyProfile:
        normalized = profile_name.strip().lower()
        if normalized == 'safe':
            return PolicyProfile(
                name='safe',
                block_pipe_operator=True,
                treat_unknown_shell_as_blocked=True,
                allow_unknown_http_domain=False,
            )
        if normalized == 'aggressive':
            return PolicyProfile(
                name='aggressive',
                block_pipe_operator=False,
                treat_unknown_shell_as_blocked=False,
                allow_unknown_http_domain=True,
            )
        return PolicyProfile(
            name='balanced',
            block_pipe_operator=False,
            treat_unknown_shell_as_blocked=False,
            allow_unknown_http_domain=False,
        )

    def profile_name(self) -> str:
        return self._profile.name

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
            return ShellPolicyResult(level='blocked', reason='Empty command', policy_id=f'shell.{self._profile.name}.empty')
        if len(cmd) > settings.max_shell_command_length:
            return ShellPolicyResult(
                level='blocked',
                reason='Command exceeds max_shell_command_length',
                policy_id=f'shell.{self._profile.name}.length',
            )

        if re.search(r'(`|\$\(|-enc\b|base64|invoke-expression|iex\b)', cmd):
            return ShellPolicyResult(
                level='blocked',
                reason='Encoded or obfuscated command pattern detected',
                policy_id=f'shell.{self._profile.name}.obfuscated',
            )

        for regex in self._hard_block_shell_regex:
            if regex.search(cmd):
                return ShellPolicyResult(
                    level='blocked',
                    reason='Hard blocked destructive shell pattern detected',
                    policy_id=f'shell.{self._profile.name}.hard_block',
                )

        segments, operators = self._split_shell_segments(cmd)
        if not segments:
            return ShellPolicyResult(
                level='blocked',
                reason='Command parsing produced no executable segment',
                policy_id=f'shell.{self._profile.name}.parse',
            )

        for segment in segments:
            for pattern in self._blocked_shell_patterns:
                if pattern and pattern in segment:
                    return ShellPolicyResult(
                        level='blocked',
                        reason=f'Blocked pattern detected: {pattern}',
                        policy_id=f'shell.{self._profile.name}.blocked_pattern',
                    )

        risky_segments: list[str] = []
        for segment in segments:
            if any(self._matches_prefix(segment, prefix) for prefix in self._safe_shell_prefixes):
                continue
            risky_segments.append(segment)

        if risky_segments:
            if self._profile.treat_unknown_shell_as_blocked:
                return ShellPolicyResult(
                    level='blocked',
                    reason=f'Unknown command blocked under safe profile: {risky_segments[0][:80]}',
                    policy_id=f'shell.{self._profile.name}.unknown_blocked',
                )
            return ShellPolicyResult(
                level='risky',
                reason=f'Command segment outside safe allowlist: {risky_segments[0][:80]}',
                policy_id=f'shell.{self._profile.name}.allowlist_miss',
            )

        if '|' in operators:
            if self._profile.block_pipe_operator:
                return ShellPolicyResult(
                    level='blocked',
                    reason='Piped commands are blocked in safe profile',
                    policy_id=f'shell.{self._profile.name}.pipe_blocked',
                )
            return ShellPolicyResult(
                level='risky',
                reason='Piped commands require explicit approval',
                policy_id=f'shell.{self._profile.name}.pipe_risky',
            )

        return ShellPolicyResult(
            level='safe',
            reason='All command segments are allowlisted',
            policy_id=f'shell.{self._profile.name}.allowlisted',
        )

    def evaluate_app_command(self, app_command: str) -> ShellPolicyResult:
        cmd = app_command.strip().lower()
        if not cmd:
            return ShellPolicyResult(level='blocked', reason='Empty app command', policy_id=f'app.{self._profile.name}.empty')

        if re.search(r'[`$;|]', cmd):
            return ShellPolicyResult(
                level='blocked',
                reason='App command contains shell control characters',
                policy_id=f'app.{self._profile.name}.control_chars',
            )

        for pattern in self._blocked_shell_patterns:
            if pattern and pattern in cmd:
                return ShellPolicyResult(
                    level='blocked',
                    reason=f'Blocked app pattern detected: {pattern}',
                    policy_id=f'app.{self._profile.name}.blocked_pattern',
                )

        for prefix in self._safe_app_prefixes:
            if self._matches_prefix(cmd, prefix):
                return ShellPolicyResult(
                    level='safe',
                    reason=f'Allowed by app prefix: {prefix}',
                    policy_id=f'app.{self._profile.name}.allowlisted',
                )

        if self._profile.treat_unknown_shell_as_blocked:
            return ShellPolicyResult(
                level='blocked',
                reason='App command is outside allowlist in safe profile',
                policy_id=f'app.{self._profile.name}.unknown_blocked',
            )
        return ShellPolicyResult(
            level='risky',
            reason='App command is outside safe app allowlist',
            policy_id=f'app.{self._profile.name}.allowlist_miss',
        )

    def _host_allowed(self, host: str) -> bool:
        if not self._allowed_http_domains:
            return self._profile.allow_unknown_http_domain

        host = host.lower().strip()
        for rule in self._allowed_http_domains:
            rule = rule.strip().lower()
            if not rule:
                continue
            if host == rule:
                return True
            if host.endswith('.' + rule):
                return True
        return self._profile.allow_unknown_http_domain

    def evaluate_http_request(self, method: str, url: str) -> ShellPolicyResult:
        normalized_method = method.strip().upper()
        if normalized_method not in self._allowed_http_methods:
            return ShellPolicyResult(
                level='blocked',
                reason=f'HTTP method not allowed: {normalized_method}',
                policy_id=f'http.{self._profile.name}.method_blocked',
            )

        target = url.strip().lower()
        if not target:
            return ShellPolicyResult(level='blocked', reason='URL is empty', policy_id=f'http.{self._profile.name}.empty')

        parsed = urlparse(target)
        if parsed.scheme not in {'http', 'https'}:
            return ShellPolicyResult(
                level='blocked',
                reason='Only http/https URLs are allowed',
                policy_id=f'http.{self._profile.name}.scheme_blocked',
            )

        for pattern in self._blocked_url_patterns:
            if pattern and pattern in target:
                return ShellPolicyResult(
                    level='blocked',
                    reason=f'Blocked URL pattern: {pattern}',
                    policy_id=f'http.{self._profile.name}.blocked_pattern',
                )

        host = (parsed.hostname or '').strip().lower()
        if not host:
            return ShellPolicyResult(level='blocked', reason='URL host is empty', policy_id=f'http.{self._profile.name}.host_empty')
        if not self._host_allowed(host):
            return ShellPolicyResult(
                level='blocked',
                reason=f'Host is not in allowlist: {host}',
                policy_id=f'http.{self._profile.name}.host_allowlist_miss',
            )
        return ShellPolicyResult(
            level='safe',
            reason='HTTP request policy check passed',
            policy_id=f'http.{self._profile.name}.allowlisted',
        )


policy_service = PolicyService()
