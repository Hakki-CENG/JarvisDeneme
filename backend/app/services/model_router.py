from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
import textwrap

import httpx

from app.core.settings import settings
from app.models.schemas import ModelQuotaResponse, ProviderQuota
from app.services.audit_service import audit_service
from app.services.metrics_service import metrics_service
from app.services.policy_service import policy_service
from app.services.secret_vault import secret_vault


class ProviderExhaustedError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


class ModelRouter:
    def __init__(self) -> None:
        priority = [p.strip() for p in settings.provider_priority.split(',') if p.strip()]
        retry = [p.strip() for p in settings.provider_retry_order.split(',') if p.strip()]
        merged: list[str] = []
        for provider in priority + retry:
            if provider not in merged:
                merged.append(provider)

        self._providers = {
            name: ProviderQuota(
                provider=name,
                remaining_requests=300,
                reset_at=datetime.now(timezone.utc) + timedelta(hours=24),
                enabled=True,
            )
            for name in merged
        }
        if settings.primary_model_provider not in self._providers:
            self._providers[settings.primary_model_provider] = ProviderQuota(
                provider=settings.primary_model_provider,
                remaining_requests=300,
                reset_at=datetime.now(timezone.utc) + timedelta(hours=24),
                enabled=True,
            )

        self._priority_order = merged or [settings.primary_model_provider]
        self._selected: str | None = settings.primary_model_provider
        self._lock = Lock()

    def _refresh_if_needed(self, quota: ProviderQuota) -> None:
        if quota.reset_at and datetime.now(timezone.utc) >= quota.reset_at:
            quota.remaining_requests = 300
            quota.reset_at = datetime.now(timezone.utc) + timedelta(hours=24)

    def get_selected_provider(self) -> str:
        with self._lock:
            if self._selected and self._selected in self._providers:
                selected = self._providers[self._selected]
                self._refresh_if_needed(selected)
                if selected.enabled and selected.remaining_requests > 0:
                    return self._selected

            for name in self._priority_order:
                quota = self._providers.get(name)
                if not quota:
                    continue
                self._refresh_if_needed(quota)
                if quota.enabled and quota.remaining_requests > 0:
                    self._selected = name
                    return name

        raise ProviderExhaustedError('No model providers have remaining request quota.')

    def _provider_order_for_attempt(self) -> list[str]:
        names: list[str] = []
        current = self._selected
        if current:
            names.append(current)
        for provider in self._priority_order:
            if provider not in names:
                names.append(provider)
        return names

    def consume(self, provider: str, amount: int = 1) -> None:
        with self._lock:
            quota = self._providers[provider]
            self._refresh_if_needed(quota)
            quota.remaining_requests = max(quota.remaining_requests - amount, 0)

    def _mark_exhausted(self, provider: str, hours: int = 1) -> None:
        with self._lock:
            quota = self._providers.get(provider)
            if not quota:
                return
            quota.remaining_requests = 0
            quota.reset_at = datetime.now(timezone.utc) + timedelta(hours=hours)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int) -> list[str]:
        if chunk_size <= 0:
            return [text]
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    def _compress_prompt(self, prompt: str) -> str:
        limit = max(settings.max_reasoning_prompt_chars, 512)
        if len(prompt) <= limit:
            return prompt

        chunk_size = max(settings.prompt_compression_chunk_chars, 400)
        chunks = self._chunk_text(prompt, chunk_size)

        summaries: list[str] = []
        for idx, chunk in enumerate(chunks[:12]):
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            head = lines[0] if lines else chunk[:220]
            tail = lines[-1] if len(lines) > 1 else ''
            snippet = f'{head} ... {tail}'.strip()
            summaries.append(f'{idx + 1}. {textwrap.shorten(snippet, width=220, placeholder=" ...")}')
        if len(chunks) > 12:
            summaries.append(f'... {len(chunks) - 12} additional chunks omitted but preserved in local task context.')

        compressed = (
            'Prompt exceeded context budget. Continue with hierarchical strategy and preserve intent.\n'
            f'Original length: {len(prompt)} chars. Chunk size: {chunk_size} chars.\n'
            'Chunked high-level summary:\n'
            + '\n'.join(summaries)
        )

        if len(compressed) <= limit:
            return compressed

        tail_keep = max(limit // 3, 256)
        head_keep = max(limit - tail_keep - 80, 256)
        return (
            prompt[:head_keep]
            + '\n...[prompt truncated for context safety]...\n'
            + prompt[-tail_keep:]
        )[:limit]

    def request_reasoning(self, prompt: str, round_name: str) -> dict[str, str]:
        prepared_prompt = self._compress_prompt(prompt)
        try:
            self.get_selected_provider()
        except ProviderExhaustedError as exc:
            raise ProviderExhaustedError(str(exc)) from exc

        errors: list[str] = []
        for provider in self._provider_order_for_attempt():
            quota = self._providers.get(provider)
            if not quota:
                continue
            self._refresh_if_needed(quota)
            if not quota.enabled or quota.remaining_requests <= 0:
                continue

            try:
                analysis = self._call_provider(provider=provider, prompt=prepared_prompt, round_name=round_name)
                self.consume(provider, 1)
                self._selected = provider
                metrics_service.inc('model_calls')
                return {'provider': provider, 'round': round_name, 'analysis': analysis}
            except ProviderRequestError as exc:
                err_text = str(exc).lower()
                if any(marker in err_text for marker in ['context', 'token limit', 'max tokens', 'too long']):
                    shorter = self._compress_prompt(prepared_prompt[: max(len(prepared_prompt) // 2, 512)])
                    try:
                        analysis = self._call_provider(provider=provider, prompt=shorter, round_name=round_name)
                        self.consume(provider, 1)
                        self._selected = provider
                        metrics_service.inc('model_calls')
                        return {'provider': provider, 'round': round_name, 'analysis': analysis}
                    except Exception as nested_exc:
                        errors.append(f'{provider}: {nested_exc}')
                        continue
                errors.append(f'{provider}: {exc}')
                continue
            except ProviderExhaustedError as exc:
                errors.append(f'{provider}: {exc}')
                self._mark_exhausted(provider, hours=1)
                continue

        # Final fallback for local development when API keys are not configured.
        if settings.env == 'dev' and (all('missing API key' in err for err in errors) or not errors):
            fallback_provider = 'local_stub'
            return {
                'provider': fallback_provider,
                'round': round_name,
                'analysis': f'{round_name} local fallback response. Prompt summary: {prepared_prompt[:240]}',
            }

        raise ProviderExhaustedError('All providers failed: ' + ' | '.join(errors))

    def _call_provider(self, provider: str, prompt: str, round_name: str) -> str:
        provider = provider.lower()
        if provider == 'gemini':
            return self._call_gemini(prompt, round_name)
        if provider == 'openrouter':
            return self._call_openrouter(prompt, round_name)
        raise ProviderRequestError(f'Unsupported provider: {provider}')

    def _call_gemini(self, prompt: str, round_name: str) -> str:
        api_key = settings.gemini_api_key or secret_vault.get_secret('GEMINI_API_KEY', consumer='model_router.gemini')
        if not api_key:
            raise ProviderRequestError('missing API key')

        url = (
            f'https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent'
            f'?key={api_key}'
        )
        policy = policy_service.evaluate_http_request(method='POST', url=url)
        audit_service.log(
            actor='policy',
            action='external_http_policy',
            details=f'provider=gemini method=POST policy={policy.policy_id} level={policy.level}',
        )
        if policy.level != 'safe':
            raise ProviderRequestError(f'HTTP policy rejected Gemini call: {policy.reason} ({policy.policy_id})')
        payload = {
            'contents': [
                {
                    'parts': [
                        {
                            'text': (
                                'You are an expert autonomous AI subsystem. '
                                f'Round={round_name}. Return concise actionable reasoning.\n\n{prompt}'
                            )
                        }
                    ]
                }
            ]
        }

        try:
            response = httpx.post(url, json=payload, timeout=45)
        except Exception as exc:
            raise ProviderRequestError(str(exc)) from exc

        if response.status_code == 429:
            raise ProviderExhaustedError('quota exhausted (429)')
        if response.status_code >= 400:
            raise ProviderRequestError(f'HTTP {response.status_code}: {response.text[:260]}')
        self._apply_quota_hint('gemini', response.headers)

        data = response.json()
        candidates = data.get('candidates') or []
        if not candidates:
            raise ProviderRequestError('No candidates in Gemini response')

        parts = candidates[0].get('content', {}).get('parts', [])
        text_chunks = [part.get('text', '') for part in parts if isinstance(part, dict)]
        text = '\n'.join(chunk for chunk in text_chunks if chunk).strip()
        if not text:
            raise ProviderRequestError('Gemini returned empty content')
        return text

    def _call_openrouter(self, prompt: str, round_name: str) -> str:
        api_key = settings.openrouter_api_key or secret_vault.get_secret('OPENROUTER_API_KEY', consumer='model_router.openrouter')
        if not api_key:
            raise ProviderRequestError('missing API key')

        url = 'https://openrouter.ai/api/v1/chat/completions'
        policy = policy_service.evaluate_http_request(method='POST', url=url)
        audit_service.log(
            actor='policy',
            action='external_http_policy',
            details=f'provider=openrouter method=POST policy={policy.policy_id} level={policy.level}',
        )
        if policy.level != 'safe':
            raise ProviderRequestError(f'HTTP policy rejected OpenRouter call: {policy.reason} ({policy.policy_id})')

        payload = {
            'model': settings.openrouter_model,
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'You are an autonomous AI co-processor. '
                        'Return concise, high-signal reasoning and next actions.'
                    ),
                },
                {'role': 'user', 'content': f'Round={round_name}\n\n{prompt}'},
            ],
        }
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': settings.openrouter_site_url,
            'X-Title': settings.openrouter_app_name,
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=45)
        except Exception as exc:
            raise ProviderRequestError(str(exc)) from exc

        if response.status_code == 429:
            raise ProviderExhaustedError('quota exhausted (429)')
        if response.status_code >= 400:
            raise ProviderRequestError(f'HTTP {response.status_code}: {response.text[:260]}')
        self._apply_quota_hint('openrouter', response.headers)

        data = response.json()
        choices = data.get('choices') or []
        if not choices:
            raise ProviderRequestError('No choices in OpenRouter response')

        message = choices[0].get('message', {})
        content = message.get('content', '')
        if not content:
            raise ProviderRequestError('OpenRouter returned empty content')
        return str(content)

    def _apply_quota_hint(self, provider: str, headers: httpx.Headers) -> None:
        candidates = [
            headers.get('x-ratelimit-remaining'),
            headers.get('ratelimit-remaining'),
            headers.get('x-ratelimit-requests-remaining'),
        ]
        remaining = None
        for value in candidates:
            if value is None:
                continue
            try:
                remaining = int(float(value))
                break
            except Exception:
                continue
        if remaining is None:
            return
        with self._lock:
            if provider in self._providers:
                self._providers[provider].remaining_requests = max(remaining, 0)

    def quotas(self) -> ModelQuotaResponse:
        selected = None
        try:
            selected = self.get_selected_provider()
        except ProviderExhaustedError:
            selected = None

        return ModelQuotaResponse(
            primary=settings.primary_model_provider,
            selected_provider=selected,
            providers=list(self._providers.values()),
        )


model_router = ModelRouter()
