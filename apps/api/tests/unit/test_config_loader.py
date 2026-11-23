"""Configuration boot must validate every layer before application work begins."""

import importlib.util
import os
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def loader():
    assert importlib.util.find_spec("bookgen") is not None, "config loader package must be available"
    from bookgen.config import load_settings

    return load_settings


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("BOOKGEN__") or name == "APP_ENV":
            monkeypatch.delenv(name)
    for source in (ROOT / "config").glob("*.yaml"):
        shutil.copy(source, tmp_path / source.name)
    return tmp_path


def test_config_loader_is_available():
    assert callable(loader())


def test_default_values(config_dir):
    settings = loader()(config_dir=config_dir)
    assert settings.llm.max_repair_retries == 2
    assert settings.grammar.full_bleed_hero.max_words == 45
    assert settings.llm.model
    assert settings.app.storage_root
    assert settings.app.sqlite_uri.startswith("sqlite")
    assert settings.app.cors_origins
    assert "internal" in settings.compliance.tags


def test_environment_yaml_overrides_defaults(config_dir, monkeypatch):
    (config_dir / "models.prod.yaml").write_text("model: environment-model\n", encoding="utf-8")
    (config_dir / "app.prod.yaml").write_text("storage_root: production-uploads\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "prod")
    settings = loader()(config_dir=config_dir)
    assert settings.llm.model == "environment-model"
    assert settings.llm.max_repair_retries == 2
    assert str(settings.app.storage_root) == "production-uploads"


def test_nested_os_overrides_win(config_dir, monkeypatch):
    (config_dir / "models.prod.yaml").write_text("model: environment-model\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("BOOKGEN__LLM__MODEL", "os-model")
    monkeypatch.setenv("BOOKGEN__LLM__MAX_REPAIR_RETRIES", "4")
    settings = loader()(config_dir=config_dir)
    assert settings.llm.model == "os-model"
    assert settings.llm.max_repair_retries == 4


@pytest.mark.parametrize("change", ["absent", "misspelled", "invalid", "unknown"])
def test_invalid_grammar_fails_at_boot(config_dir, change):
    load_settings = loader()
    import yaml
    from pydantic import ValidationError

    path = config_dir / "design_grammar.yaml"
    grammar = yaml.safe_load(path.read_text(encoding="utf-8"))
    if change == "absent":
        del grammar["full_bleed_hero"]
    elif change == "misspelled":
        grammar["full_bleed_hero"]["max_wordz"] = grammar["full_bleed_hero"].pop("max_words")
    elif change == "invalid":
        grammar["full_bleed_hero"]["max_words"] = -1
    else:
        grammar["invented_archetype"] = {"max_words": 1}
    path.write_text(yaml.safe_dump(grammar), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(config_dir=config_dir)


def test_invalid_environment_override_fails_at_boot(config_dir, monkeypatch):
    load_settings = loader()
    from pydantic import ValidationError

    monkeypatch.setenv("BOOKGEN__LLM__MAX_REPAIR_RETRIES", "-1")
    with pytest.raises(ValidationError):
        load_settings(config_dir=config_dir)


@pytest.mark.parametrize("name", ["profiling", "theme", "export"])
def test_optional_modules_are_validated_when_their_yaml_lands(config_dir, name):
    load_settings = loader()
    from pydantic import ValidationError

    (config_dir / f"{name}.yaml").write_text("unexpected_setting: true\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(config_dir=config_dir)


def test_unknown_app_setting_fails_at_boot(config_dir):
    load_settings = loader()
    from pydantic import ValidationError

    (config_dir / "app.default.yaml").write_text("unknown_setting: true\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(config_dir=config_dir)


@pytest.mark.parametrize("name", ["profiling", "theme", "export"])
def test_optional_modules_load_defaults_and_environment(config_dir, monkeypatch, name):
    load_settings = loader()
    (config_dir / f"{name}.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / f"{name}.prod.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "prod")
    assert getattr(load_settings(config_dir=config_dir), name) is not None


def test_nested_environment_yaml_preserves_unmodified_rules(config_dir, monkeypatch):
    (config_dir / "design_grammar.prod.yaml").write_text("full_bleed_hero:\n  max_words: 20\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "prod")
    settings = loader()(config_dir=config_dir)
    assert settings.grammar.full_bleed_hero.max_words == 20
    assert settings.grammar.full_bleed_hero.max_images == 1
    assert settings.grammar.safe_flow_fallback.max_words > 0


@pytest.mark.parametrize("document", ["[]", "null", "a string"])
def test_invalid_yaml_shapes_fail_validation(config_dir, document):
    load_settings = loader()
    from pydantic import ValidationError

    (config_dir / "models.yaml").write_text(document, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(config_dir=config_dir)


def coverage_checker():
    spec = importlib.util.spec_from_file_location("coverage_checker", ROOT / "scripts/check_branch_coverage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_branch_gate_uses_weighted_branch_totals(tmp_path):
    module = coverage_checker()
    root = tmp_path / "domain"
    root.mkdir()
    first, second = root / "first.py", root / "second.py"
    first.touch()
    second.touch()
    report = {"files": {
        str(first): {"summary": {"covered_branches": 1, "num_branches": 2, "covered_lines": 100}},
        str(second): {"summary": {"covered_branches": 9, "num_branches": 10, "covered_lines": 100}},
    }}
    assert module.branch_result(report, root) == (10, 12)


def test_branch_gate_rejects_omitted_source(tmp_path):
    module = coverage_checker()
    (tmp_path / "unmeasured.py").touch()
    with pytest.raises(ValueError, match="omits source"):
        module.branch_result({"files": {}}, tmp_path)


def test_branch_gate_rejects_line_only_data(tmp_path):
    module = coverage_checker()
    report = tmp_path / "coverage.json"
    report.write_text('{"meta": {"branch_coverage": false}, "files": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="branch data"):
        module.check_coverage(report, 90, 80)


def test_branch_gate_applies_configurable_domain_threshold(tmp_path, monkeypatch):
    import json

    module = coverage_checker()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    source = tmp_path / "apps/api/src/bookgen/domain/profiler.py"
    source.parent.mkdir(parents=True)
    source.touch()
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({
        "meta": {"branch_coverage": True},
        "files": {str(source): {"summary": {"covered_branches": 94, "num_branches": 100}}},
    }), encoding="utf-8")
    assert module.check_coverage(report, 90, 80) == 0
    assert module.check_coverage(report, 95, 80) == 1
