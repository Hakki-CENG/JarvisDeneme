from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Jarvis-X'
    env: Literal['dev', 'prod', 'test'] = 'dev'
    host: str = '0.0.0.0'
    port: int = 8000

    data_dir: Path = Field(default=Path('.jarvisx_data'))
    sqlite_path: Path = Field(default=Path('.jarvisx_data/jarvisx.db'))
    logs_dir: Path = Field(default=Path('.jarvisx_data/logs'))

    primary_model_provider: str = 'gemini'
    provider_priority: str = 'gemini,openrouter'
    provider_retry_order: str = 'openrouter'

    gemini_api_key: str = ''
    openrouter_api_key: str = ''
    gemini_model: str = 'gemini-2.5-flash'
    openrouter_model: str = 'google/gemini-2.0-flash-exp:free'
    openrouter_site_url: str = 'http://localhost'
    openrouter_app_name: str = 'Jarvis-X'

    max_reasoning_rounds: int = 3
    max_subtasks: int = 12
    max_replan_attempts: int = 3
    approval_timeout_seconds: int = 3600
    max_reasoning_prompt_chars: int = 9000
    prompt_compression_chunk_chars: int = 1800
    max_parallel_workers: int = 3
    max_memory_items_for_planner: int = 8

    voice_enabled: bool = True
    vision_enabled: bool = True

    # API Security
    cors_allowed_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    user_api_token: str = ''
    admin_api_token: str = ''
    rate_limit_per_minute: int = 120
    idempotency_ttl_hours: int = 24
    event_retention_days: int = 14

    # Execution policy
    policy_profile: Literal['safe', 'balanced', 'aggressive'] = 'balanced'
    allowed_file_roots: str = '.jarvisx_data,.'
    allow_outside_paths_with_approval: bool = True
    safe_shell_prefixes: str = (
        'echo,dir,ls,pwd,whoami,where,which,python --version,python3 --version,git status'
    )
    safe_app_prefixes: str = (
        'start chrome,start msedge,start notepad,start explorer,notepad,explorer,open -a,xdg-open,google-chrome,firefox'
    )
    blocked_shell_patterns: str = 'shutdown,reboot,format,cipher /w,diskpart,net user'
    blocked_url_patterns: str = '169.254.169.254,localhost,127.0.0.1,::1,file://'
    allowed_http_methods: str = 'GET,POST'
    allowed_http_domains: str = (
        'en.wikipedia.org,www.wikidata.org,export.arxiv.org,api.crossref.org,api.github.com,api.stackexchange.com,'
        'api.open-meteo.com,earthquake.usgs.gov,nominatim.openstreetmap.org,overpass-api.de,api.gdeltproject.org,'
        'noembed.com,api.openalex.org,eutils.ncbi.nlm.nih.gov,api.semanticscholar.org,'
        'generativelanguage.googleapis.com,openrouter.ai'
    )
    max_shell_command_length: int = 600
    max_action_payload_chars: int = 12000
    require_approval_for_unknown_shell_commands: bool = True
    require_approval_for_sensitive_reads: bool = True

    # Security policy defaults.
    require_approval_for_delete: bool = True
    require_approval_for_install: bool = True
    require_approval_for_system_changes: bool = True
    require_approval_for_external_writes: bool = True


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
settings.logs_dir.mkdir(parents=True, exist_ok=True)
