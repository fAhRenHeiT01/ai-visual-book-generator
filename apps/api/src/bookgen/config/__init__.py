"""Validated YAML settings: defaults < environment YAML < nested OS variables."""

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
import yaml

from .app import AppConfig
from .compliance import ComplianceConfig
from .export import ExportConfig
from .grammar import GrammarConfig
from .models import LLMConfig
from .profiling import ProfilingConfig
from .theme import ThemeConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="forbid", env_prefix="BOOKGEN__", env_nested_delimiter="__"
    )

    app: AppConfig
    llm: LLMConfig
    grammar: GrammarConfig
    compliance: ComplianceConfig
    profiling: ProfilingConfig | None = None
    theme: ThemeConfig | None = None
    export: ExportConfig | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return env_settings, init_settings


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return yaml.safe_load(source)


def load_settings(config_dir: str | Path | None = None) -> Settings:
    """Load and validate each known configuration file without caching OS state.

    A module's ordinary YAML is its default, with ``<name>.default.yaml`` also
    accepted. Optional modules activate when their files arrive in a later ticket.
    """
    directory = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parents[5] / "config"
    environment = os.environ.get("APP_ENV")
    modules: dict[str, tuple[str, type[BaseModel], bool]] = {
        "app": ("app", AppConfig, True),
        "models": ("llm", LLMConfig, True),
        "design_grammar": ("grammar", GrammarConfig, True),
        "compliance": ("compliance", ComplianceConfig, True),
        "profiling": ("profiling", ProfilingConfig, False),
        "theme": ("theme", ThemeConfig, False),
        "export": ("export", ExportConfig, False),
    }
    payload: dict[str, Any] = {}
    for name, (field, model, required) in modules.items():
        candidates = [directory / f"{name}.yaml", directory / f"{name}.default.yaml"]
        if environment:
            candidates.append(directory / f"{name}.{environment}.yaml")
        existing = [path for path in candidates if path.is_file()]
        if not existing and not required:
            continue
        merged: Any = {}
        for path in existing:
            layer = _read_yaml(path)
            if not isinstance(layer, Mapping):
                # Use the typed model to produce the same boot-time ValidationError
                # for invalid YAML shapes as for invalid individual settings.
                model.model_validate(layer)
            merged = _merge(merged, layer)
        payload[field] = merged
    return Settings(**payload)


__all__ = ["Settings", "load_settings"]
