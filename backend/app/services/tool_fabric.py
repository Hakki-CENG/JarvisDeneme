from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from typing import Any, Awaitable, Callable

import httpx

from app.models.schemas import (
    ToolBatchExecutionRequest,
    ToolBatchExecutionResult,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealth,
    ToolManifest,
    ToolRetryPolicy,
)
from app.services.audit_service import audit_service
from app.services.policy_service import policy_service
from app.services.repositories import repositories

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class ToolRuntimeState:
    calls_window: deque[float] = field(default_factory=deque)
    cache: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict)
    failure_count: int = 0
    circuit_open_until: float = 0.0
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_latency_ms: int = 0


class ToolFabricService:
    def __init__(self) -> None:
        self._manifests: dict[str, ToolManifest] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self._runtime: dict[str, ToolRuntimeState] = {}
        self._promoted_versions: dict[str, str] = {}
        self._default_rate_limit_per_minute = 30
        self._default_cache_ttl_seconds = 300
        self._circuit_failure_threshold = 3
        self._circuit_cooldown_seconds = 90
        self._register_builtin_connectors()

    def list_catalog(self) -> list[ToolManifest]:
        manifests: list[ToolManifest] = []
        for name in sorted(self._promoted_versions.keys()):
            manifest, _ = self._resolve_manifest(name)
            if manifest:
                manifests.append(manifest)
        return manifests

    def health(self) -> list[ToolHealth]:
        now = time.time()
        items: list[ToolHealth] = []
        for name in sorted(self._promoted_versions.keys()):
            manifest, key = self._resolve_manifest(name)
            if not manifest or not key:
                continue
            state = self._runtime[key]
            self._trim_calls_window(state, now)
            items.append(
                ToolHealth(
                    name=name,
                    enabled=manifest.enabled,
                    circuit_open=state.circuit_open_until > now,
                    cache_items=len(state.cache),
                    last_error_code=state.last_error_code,
                    last_error_message=state.last_error_message,
                    last_latency_ms=state.last_latency_ms,
                    recent_calls=len(state.calls_window),
                )
            )
        return items

    def get_manifest(self, name: str) -> ToolManifest | None:
        manifest, _ = self._resolve_manifest(name)
        return manifest

    def set_enabled(self, name: str, enabled: bool) -> bool:
        manifest, key = self._resolve_manifest(name)
        if not manifest:
            return False
        manifest.enabled = enabled
        if key:
            self._manifests[key] = manifest
            repositories['tool_manifests'].save(
                manifest_payload=manifest.model_dump(mode='json'),
                tool_name=manifest.name,
                version=manifest.version,
                promoted=(self._promoted_versions.get(manifest.name) == manifest.version),
            )
        return True

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        return repositories['tool_manifests'].list_versions(name)

    def promote(self, name: str, version: str) -> bool:
        ok = repositories['tool_manifests'].promote(name, version)
        if not ok:
            return False
        key = self._manifest_key(name, version)
        if key in self._manifests:
            self._promoted_versions[name] = version
        return True

    async def batch_execute(self, request: ToolBatchExecutionRequest) -> ToolBatchExecutionResult:
        results: list[ToolExecutionResult] = []
        failed = 0
        succeeded = 0
        for item in request.requests:
            result = await self.execute(item)
            results.append(result)
            if result.success:
                succeeded += 1
            else:
                failed += 1
                if request.stop_on_error:
                    break
        return ToolBatchExecutionResult(
            success=failed == 0,
            results=results,
            failed_count=failed,
            success_count=succeeded,
        )

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        now = time.time()
        requested_name = request.name
        manifest, resolved_key = self._resolve_manifest(request.name)
        if not manifest or not resolved_key:
            return self._error_result(request.name, 'TOOL_NOT_FOUND', 'Tool is not registered', requested_name=requested_name)

        state = self._runtime[resolved_key]
        if not manifest.enabled:
            return self._error_result(
                manifest.name,
                'TOOL_DISABLED',
                'Tool is disabled by policy',
                requested_name=requested_name,
                resolved_version=manifest.version,
            )

        if manifest.risk_level in {'MEDIUM', 'HIGH'} and not request.approved and not request.dry_run:
            return self._error_result(
                manifest.name,
                'APPROVAL_REQUIRED',
                'Tool requires approval because of risk level',
                requested_name=requested_name,
                resolved_version=manifest.version,
            )

        if state.circuit_open_until > now:
            return self._error_result(
                manifest.name,
                'CIRCUIT_OPEN',
                f'Tool circuit is open until {datetime.fromtimestamp(state.circuit_open_until, tz=timezone.utc).isoformat()}',
                requested_name=requested_name,
                resolved_version=manifest.version,
            )

        if not self._allow_rate_limit(state, now):
            return self._error_result(
                manifest.name,
                'RATE_LIMITED',
                'Tool rate limit exceeded',
                requested_name=requested_name,
                resolved_version=manifest.version,
            )

        if request.dry_run:
            return ToolExecutionResult(
                name=manifest.name,
                requested_name=requested_name,
                resolved_version=manifest.version,
                success=True,
                output={
                    'dry_run': True,
                    'contract': manifest.model_dump(mode='json'),
                    'payload_preview': request.payload,
                },
                cached=False,
                attempts=0,
                latency_ms=0,
            )

        cache_key = self._cache_key(f'{manifest.name}@{manifest.version}', request.payload)
        cached = self._read_cache(state, cache_key)
        if cached is not None and manifest.idempotent:
            return ToolExecutionResult(
                name=manifest.name,
                requested_name=requested_name,
                resolved_version=manifest.version,
                success=True,
                output=cached,
                cached=True,
                attempts=0,
                latency_ms=state.last_latency_ms,
            )

        handler = self._handlers[resolved_key]
        attempts = max(1, manifest.retry_policy.max_attempts)
        backoff = max(0.0, manifest.retry_policy.backoff_seconds)

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                output = await asyncio.wait_for(handler(request.payload), timeout=manifest.timeout_seconds)
                latency_ms = int((time.perf_counter() - started) * 1000)
                state.last_latency_ms = latency_ms
                state.failure_count = 0
                state.last_error_code = None
                state.last_error_message = None
                if manifest.idempotent:
                    self._write_cache(state, cache_key, output)
                return ToolExecutionResult(
                    name=manifest.name,
                    requested_name=requested_name,
                    resolved_version=manifest.version,
                    success=True,
                    output=output,
                    cached=False,
                    attempts=attempt,
                    latency_ms=latency_ms,
                )
            except TimeoutError:
                state.failure_count += 1
                state.last_error_code = 'TOOL_TIMEOUT'
                state.last_error_message = f'Tool timed out after {manifest.timeout_seconds}s'
                state.last_latency_ms = int((time.perf_counter() - started) * 1000)
            except httpx.HTTPError as exc:
                state.failure_count += 1
                state.last_error_code = 'UPSTREAM_HTTP_ERROR'
                state.last_error_message = str(exc)
                state.last_latency_ms = int((time.perf_counter() - started) * 1000)
            except Exception as exc:  # pragma: no cover - runtime safety
                state.failure_count += 1
                state.last_error_code = 'TOOL_EXECUTION_ERROR'
                state.last_error_message = str(exc)
                state.last_latency_ms = int((time.perf_counter() - started) * 1000)

            if state.failure_count >= self._circuit_failure_threshold:
                state.circuit_open_until = time.time() + self._circuit_cooldown_seconds

            if attempt < attempts and backoff > 0:
                await asyncio.sleep(backoff * attempt)

        return self._error_result(
            manifest.name,
            state.last_error_code or 'TOOL_FAILED',
            state.last_error_message or 'Tool execution failed',
            attempts=attempts,
            latency_ms=state.last_latency_ms,
            requested_name=requested_name,
            resolved_version=manifest.version,
        )

    @staticmethod
    def _manifest_key(name: str, version: str) -> str:
        return f'{name}@{version}'

    def _resolve_manifest(self, requested_name: str) -> tuple[ToolManifest | None, str | None]:
        name = requested_name.strip()
        version: str | None = None
        if '@' in name:
            parts = name.split('@', 1)
            name = parts[0].strip()
            version = parts[1].strip() or None
        if not name:
            return None, None

        selected_version = version or self._promoted_versions.get(name)
        if not selected_version:
            return None, None
        key = self._manifest_key(name, selected_version)
        return self._manifests.get(key), key

    def _register(self, manifest: ToolManifest, handler: ToolHandler, promoted: bool = False) -> None:
        key = self._manifest_key(manifest.name, manifest.version)
        self._manifests[key] = manifest
        self._handlers[key] = handler
        self._runtime[key] = ToolRuntimeState()
        current_promoted = self._promoted_versions.get(manifest.name)
        if promoted or not current_promoted:
            self._promoted_versions[manifest.name] = manifest.version
        repositories['tool_manifests'].save(
            manifest_payload=manifest.model_dump(mode='json'),
            tool_name=manifest.name,
            version=manifest.version,
            promoted=(self._promoted_versions.get(manifest.name) == manifest.version),
        )

    def _register_builtin_connectors(self) -> None:
        retry = ToolRetryPolicy(max_attempts=2, backoff_seconds=0.8)

        self._register(
            ToolManifest(
                name='wikipedia.search',
                description='Search Wikipedia pages by keyword.',
                category='knowledge',
                input_schema={'query': 'string', 'limit': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._wikipedia_search,
        )
        self._register(
            ToolManifest(
                name='wikidata.lookup',
                description='Lookup Wikidata entities by text query.',
                category='knowledge',
                input_schema={'query': 'string', 'limit': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._wikidata_lookup,
        )
        self._register(
            ToolManifest(
                name='arxiv.search',
                description='Retrieve arXiv paper metadata using keyword search.',
                category='knowledge',
                input_schema={'query': 'string', 'limit': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=25,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._arxiv_search,
        )
        self._register(
            ToolManifest(
                name='crossref.search',
                description='Search Crossref records for DOI/publication metadata.',
                category='knowledge',
                input_schema={'query': 'string', 'rows': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._crossref_search,
        )
        self._register(
            ToolManifest(
                name='github.search_repos',
                description='Search public GitHub repositories.',
                category='knowledge',
                input_schema={'query': 'string', 'per_page': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._github_search_repos,
        )
        self._register(
            ToolManifest(
                name='stackexchange.search',
                description='Search StackExchange questions.',
                category='knowledge',
                input_schema={'query': 'string', 'site': 'string', 'pagesize': 'int<=20'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._stackexchange_search,
        )
        self._register(
            ToolManifest(
                name='open_meteo.forecast',
                description='Fetch weather forecast for coordinates.',
                category='world',
                input_schema={'lat': 'float', 'lon': 'float'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._open_meteo_forecast,
        )
        self._register(
            ToolManifest(
                name='usgs.earthquakes',
                description='Fetch recent earthquake feed from USGS.',
                category='world',
                input_schema={'period': 'str(one of: hour/day/week/month)'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._usgs_earthquakes,
        )
        self._register(
            ToolManifest(
                name='osm.nominatim',
                description='Geocode location text via OpenStreetMap Nominatim.',
                category='world',
                input_schema={'query': 'string', 'limit': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._osm_nominatim,
        )
        self._register(
            ToolManifest(
                name='gdelt.events',
                description='Query GDELT document/events by keyword.',
                category='world',
                input_schema={'query': 'string', 'maxrecords': 'int<=25'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=25,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._gdelt_events,
        )
        self._register(
            ToolManifest(
                name='rss.fetch',
                description='Fetch and parse RSS/Atom feed headlines.',
                category='content',
                input_schema={'url': 'string', 'limit': 'int<=20'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._rss_fetch,
        )
        self._register(
            ToolManifest(
                name='youtube.summary',
                description='Fetch lightweight metadata summary for a YouTube URL.',
                category='content',
                input_schema={'url': 'string'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._youtube_summary,
        )
        self._register(
            ToolManifest(
                name='openalex.search',
                description='Search OpenAlex works metadata.',
                category='knowledge',
                input_schema={'query': 'string', 'per_page': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._openalex_search,
        )
        self._register(
            ToolManifest(
                name='pubmed.search',
                description='Search PubMed IDs and article summaries.',
                category='knowledge',
                input_schema={'query': 'string', 'retmax': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._pubmed_search,
        )
        self._register(
            ToolManifest(
                name='semanticscholar.search',
                description='Search Semantic Scholar paper metadata.',
                category='knowledge',
                input_schema={'query': 'string', 'limit': 'int<=10'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=20,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._semanticscholar_search,
        )
        self._register(
            ToolManifest(
                name='osm.overpass',
                description='Query OpenStreetMap Overpass API by text or query language.',
                category='world',
                input_schema={'query': 'string', 'timeout': 'int<=60'},
                risk_level='LOW',
                idempotent=True,
                timeout_seconds=25,
                retry_policy=retry,
                rollback_hint='Read-only external query; no rollback required.',
            ),
            self._osm_overpass,
        )

        # Optional adapters - disabled by default for explicit opt-in.
        self._register(
            ToolManifest(
                name='adapter.geosentinel',
                description='Optional GeoSentinel adapter endpoint.',
                category='osint',
                input_schema={'endpoint': 'string', 'query': 'string'},
                risk_level='MEDIUM',
                idempotent=True,
                timeout_seconds=25,
                retry_policy=retry,
                rollback_hint='Adapter call may access external systems; no automatic rollback.',
                enabled=False,
                optional=True,
                source='adapter',
            ),
            self._generic_adapter_call,
        )
        self._register(
            ToolManifest(
                name='adapter.project_nomad',
                description='Optional Project Nomad adapter endpoint.',
                category='osint',
                input_schema={'endpoint': 'string', 'query': 'string'},
                risk_level='MEDIUM',
                idempotent=True,
                timeout_seconds=25,
                retry_policy=retry,
                rollback_hint='Adapter call may access external systems; no automatic rollback.',
                enabled=False,
                optional=True,
                source='adapter',
            ),
            self._generic_adapter_call,
        )
        self._register(
            ToolManifest(
                name='adapter.spiderfoot',
                description='Optional SpiderFoot adapter endpoint.',
                category='osint',
                input_schema={'endpoint': 'string', 'query': 'string'},
                risk_level='HIGH',
                idempotent=True,
                timeout_seconds=30,
                retry_policy=ToolRetryPolicy(max_attempts=1, backoff_seconds=0.0),
                rollback_hint='Potentially sensitive intel scan; requires explicit approval.',
                enabled=False,
                optional=True,
                source='adapter',
            ),
            self._generic_adapter_call,
        )

    def _allow_rate_limit(self, state: ToolRuntimeState, now: float) -> bool:
        self._trim_calls_window(state, now)
        if len(state.calls_window) >= self._default_rate_limit_per_minute:
            return False
        state.calls_window.append(now)
        return True

    @staticmethod
    def _trim_calls_window(state: ToolRuntimeState, now: float) -> None:
        while state.calls_window and now - state.calls_window[0] > 60:
            state.calls_window.popleft()

    @staticmethod
    def _cache_key(name: str, payload: dict[str, Any]) -> str:
        raw = json.dumps({'name': name, 'payload': payload}, ensure_ascii=True, sort_keys=True)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @staticmethod
    def _read_cache(state: ToolRuntimeState, key: str) -> dict[str, Any] | None:
        now = time.time()
        item = state.cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < now:
            state.cache.pop(key, None)
            return None
        return value

    def _write_cache(self, state: ToolRuntimeState, key: str, value: dict[str, Any]) -> None:
        expires_at = time.time() + self._default_cache_ttl_seconds
        state.cache[key] = (expires_at, value)
        if len(state.cache) > 500:
            oldest = sorted(state.cache.items(), key=lambda item: item[1][0])[:50]
            for old_key, _ in oldest:
                state.cache.pop(old_key, None)

    @staticmethod
    def _error_result(
        name: str,
        code: str,
        message: str,
        attempts: int = 1,
        latency_ms: int = 0,
        requested_name: str | None = None,
        resolved_version: str | None = None,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            name=name,
            requested_name=requested_name,
            resolved_version=resolved_version,
            success=False,
            error_code=code,
            error_message=message,
            attempts=attempts,
            latency_ms=latency_ms,
            cached=False,
        )

    @staticmethod
    async def _http_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 20) -> dict[str, Any]:
        policy = policy_service.evaluate_http_request(method='GET', url=url)
        audit_service.log(
            actor='policy',
            action='external_http_policy',
            details=f'context=tool_fabric method=GET url={url} policy={policy.policy_id} level={policy.level}',
        )
        if policy.level != 'safe':
            raise PermissionError(f'HTTP policy rejected request: {policy.reason} ({policy.policy_id})')
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    @staticmethod
    async def _http_text(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 20) -> str:
        policy = policy_service.evaluate_http_request(method='GET', url=url)
        audit_service.log(
            actor='policy',
            action='external_http_policy',
            details=f'context=tool_fabric method=GET url={url} policy={policy.policy_id} level={policy.level}',
        )
        if policy.level != 'safe':
            raise PermissionError(f'HTTP policy rejected request: {policy.reason} ({policy.policy_id})')
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.text

    async def _wikipedia_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        limit = max(1, min(int(payload.get('limit', 5)), 10))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://en.wikipedia.org/w/api.php',
            params={
                'action': 'query',
                'list': 'search',
                'format': 'json',
                'utf8': 1,
                'srlimit': limit,
                'srsearch': query,
            },
        )
        results = data.get('query', {}).get('search', [])
        normalized = [
            {
                'title': item.get('title'),
                'snippet': re.sub('<[^<]+?>', '', str(item.get('snippet', ''))),
                'pageid': item.get('pageid'),
            }
            for item in results
        ]
        return {'query': query, 'results': normalized}

    async def _wikidata_lookup(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        limit = max(1, min(int(payload.get('limit', 5)), 10))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://www.wikidata.org/w/api.php',
            params={
                'action': 'wbsearchentities',
                'format': 'json',
                'language': 'en',
                'uselang': 'en',
                'limit': limit,
                'search': query,
            },
        )
        return {'query': query, 'results': data.get('search', [])}

    async def _arxiv_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        limit = max(1, min(int(payload.get('limit', 5)), 10))
        if not query:
            raise ValueError('query is required')
        text = await self._http_text(
            'https://export.arxiv.org/api/query',
            params={'search_query': f'all:{query}', 'start': 0, 'max_results': limit},
            timeout=25,
        )
        entries = re.findall(r'<entry>(.*?)</entry>', text, re.DOTALL)
        papers: list[dict[str, Any]] = []
        for entry in entries[:limit]:
            title = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
            summary = re.search(r'<summary>(.*?)</summary>', entry, re.DOTALL)
            link = re.search(r'<id>(.*?)</id>', entry, re.DOTALL)
            papers.append(
                {
                    'title': (title.group(1).strip() if title else '').replace('\n', ' '),
                    'summary': (summary.group(1).strip() if summary else '').replace('\n', ' ')[:500],
                    'id': link.group(1).strip() if link else '',
                }
            )
        return {'query': query, 'results': papers}

    async def _crossref_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        rows = max(1, min(int(payload.get('rows', 5)), 10))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json('https://api.crossref.org/works', params={'query': query, 'rows': rows})
        items = data.get('message', {}).get('items', [])
        results = [
            {
                'title': (item.get('title') or [''])[0],
                'doi': item.get('DOI'),
                'type': item.get('type'),
                'publisher': item.get('publisher'),
            }
            for item in items
        ]
        return {'query': query, 'results': results}

    async def _github_search_repos(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        per_page = max(1, min(int(payload.get('per_page', 5)), 10))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://api.github.com/search/repositories',
            params={'q': query, 'sort': 'stars', 'order': 'desc', 'per_page': per_page},
            headers={'Accept': 'application/vnd.github+json'},
        )
        return {
            'query': query,
            'results': [
                {
                    'full_name': item.get('full_name'),
                    'html_url': item.get('html_url'),
                    'description': item.get('description'),
                    'stargazers_count': item.get('stargazers_count'),
                    'language': item.get('language'),
                }
                for item in data.get('items', [])
            ],
        }

    async def _stackexchange_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        site = str(payload.get('site', 'stackoverflow')).strip() or 'stackoverflow'
        pagesize = max(1, min(int(payload.get('pagesize', 5)), 20))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://api.stackexchange.com/2.3/search/advanced',
            params={
                'order': 'desc',
                'sort': 'relevance',
                'q': query,
                'site': site,
                'pagesize': pagesize,
                'filter': 'default',
            },
        )
        return {
            'query': query,
            'site': site,
            'results': [
                {
                    'title': item.get('title'),
                    'link': item.get('link'),
                    'is_answered': item.get('is_answered'),
                    'score': item.get('score'),
                }
                for item in data.get('items', [])
            ],
        }

    async def _open_meteo_forecast(self, payload: dict[str, Any]) -> dict[str, Any]:
        lat = float(payload.get('lat'))
        lon = float(payload.get('lon'))
        data = await self._http_json(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude': lat,
                'longitude': lon,
                'current': 'temperature_2m,apparent_temperature,wind_speed_10m,weather_code',
                'hourly': 'temperature_2m,precipitation_probability',
                'forecast_days': 2,
            },
        )
        return {
            'coordinates': {'lat': lat, 'lon': lon},
            'current': data.get('current', {}),
            'hourly': data.get('hourly', {}),
        }

    async def _usgs_earthquakes(self, payload: dict[str, Any]) -> dict[str, Any]:
        period = str(payload.get('period', 'day')).strip().lower()
        if period not in {'hour', 'day', 'week', 'month'}:
            period = 'day'
        data = await self._http_json(f'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_{period}.geojson')
        features = data.get('features', [])
        results = []
        for item in features[:20]:
            prop = item.get('properties', {})
            geom = item.get('geometry', {})
            results.append(
                {
                    'place': prop.get('place'),
                    'mag': prop.get('mag'),
                    'time': prop.get('time'),
                    'url': prop.get('url'),
                    'coordinates': geom.get('coordinates'),
                }
            )
        return {'period': period, 'count': len(features), 'results': results}

    async def _osm_nominatim(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        limit = max(1, min(int(payload.get('limit', 5)), 10))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://nominatim.openstreetmap.org/search',
            params={'q': query, 'format': 'jsonv2', 'limit': limit},
            headers={'User-Agent': 'Jarvis-X/1.0'},
        )
        return {'query': query, 'results': data}

    async def _gdelt_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        maxrecords = max(1, min(int(payload.get('maxrecords', 10)), 25))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://api.gdeltproject.org/api/v2/doc/doc',
            params={'query': query, 'mode': 'ArtList', 'maxrecords': maxrecords, 'format': 'json'},
            timeout=25,
        )
        articles = data.get('articles', []) or []
        return {
            'query': query,
            'results': [
                {
                    'title': item.get('title'),
                    'url': item.get('url'),
                    'source': item.get('sourcecountry'),
                    'seendate': item.get('seendate'),
                }
                for item in articles
            ],
        }

    async def _rss_fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get('url', '')).strip()
        limit = max(1, min(int(payload.get('limit', 10)), 20))
        if not url:
            raise ValueError('url is required')
        text = await self._http_text(url, headers={'User-Agent': 'Jarvis-X/1.0'})
        items = re.findall(r'<item>(.*?)</item>', text, flags=re.DOTALL | re.IGNORECASE)
        if not items:
            items = re.findall(r'<entry>(.*?)</entry>', text, flags=re.DOTALL | re.IGNORECASE)
        parsed: list[dict[str, Any]] = []
        for raw in items[:limit]:
            title_match = re.search(r'<title[^>]*>(.*?)</title>', raw, flags=re.DOTALL | re.IGNORECASE)
            link_match = re.search(r'<link[^>]*>(.*?)</link>', raw, flags=re.DOTALL | re.IGNORECASE)
            if not link_match:
                attr_link = re.search(r'<link[^>]*href=["\']([^"\']+)["\']', raw, flags=re.IGNORECASE)
                link = attr_link.group(1).strip() if attr_link else ''
            else:
                link = link_match.group(1).strip()
            parsed.append(
                {
                    'title': re.sub('<[^<]+?>', '', (title_match.group(1).strip() if title_match else '')),
                    'link': link,
                }
            )
        return {'url': url, 'results': parsed}

    async def _youtube_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get('url', '')).strip()
        if not url:
            raise ValueError('url is required')
        data = await self._http_json('https://noembed.com/embed', params={'url': url})
        title = str(data.get('title', '')).strip()
        author = str(data.get('author_name', '')).strip()
        provider = str(data.get('provider_name', 'YouTube')).strip()
        summary = f'{title} by {author} ({provider})'.strip()
        return {
            'url': url,
            'title': title,
            'author': author,
            'provider': provider,
            'summary': summary,
        }

    async def _openalex_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        per_page = max(1, min(int(payload.get('per_page', 5)), 10))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://api.openalex.org/works',
            params={'search': query, 'per-page': per_page},
        )
        results = []
        for item in data.get('results', [])[:per_page]:
            ids = item.get('ids', {})
            results.append(
                {
                    'id': item.get('id'),
                    'doi': ids.get('doi'),
                    'title': item.get('title'),
                    'publication_year': item.get('publication_year'),
                    'cited_by_count': item.get('cited_by_count'),
                    'open_access': item.get('open_access', {}).get('is_oa'),
                }
            )
        return {'query': query, 'results': results}

    async def _pubmed_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        retmax = max(1, min(int(payload.get('retmax', 5)), 10))
        if not query:
            raise ValueError('query is required')
        search = await self._http_json(
            'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',
            params={'db': 'pubmed', 'retmode': 'json', 'term': query, 'retmax': retmax},
        )
        ids = search.get('esearchresult', {}).get('idlist', [])[:retmax]
        if not ids:
            return {'query': query, 'results': []}
        summary = await self._http_json(
            'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi',
            params={'db': 'pubmed', 'retmode': 'json', 'id': ','.join(ids)},
        )
        items = summary.get('result', {})
        results: list[dict[str, Any]] = []
        for pmid in ids:
            row = items.get(pmid) or {}
            results.append(
                {
                    'pmid': pmid,
                    'title': row.get('title'),
                    'pubdate': row.get('pubdate'),
                    'source': row.get('source'),
                    'authors': [a.get('name') for a in row.get('authors', []) if isinstance(a, dict)],
                }
            )
        return {'query': query, 'results': results}

    async def _semanticscholar_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        limit = max(1, min(int(payload.get('limit', 5)), 10))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://api.semanticscholar.org/graph/v1/paper/search',
            params={'query': query, 'limit': limit, 'fields': 'title,year,citationCount,venue,url'},
        )
        return {'query': query, 'results': data.get('data', [])[:limit]}

    async def _osm_overpass(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get('query', '')).strip()
        timeout = max(5, min(int(payload.get('timeout', 30)), 60))
        if not query:
            raise ValueError('query is required')
        data = await self._http_json(
            'https://overpass-api.de/api/interpreter',
            params={'data': f'[out:json][timeout:{timeout}];{query};out body 15;'},
            timeout=25,
        )
        elements = data.get('elements', []) if isinstance(data, dict) else []
        return {'query': query, 'count': len(elements), 'elements': elements[:50]}

    async def _generic_adapter_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(payload.get('endpoint', '')).strip()
        query = str(payload.get('query', '')).strip()
        if not endpoint:
            raise ValueError('endpoint is required')
        headers = payload.get('headers')
        if headers is not None and not isinstance(headers, dict):
            raise ValueError('headers must be an object')
        params = {'query': query} if query else None
        data = await self._http_json(endpoint, params=params, headers=headers)
        return {'endpoint': endpoint, 'result': data}


tool_fabric_service = ToolFabricService()
