"""Small live check for the configured LLM transport and credentials."""

import argparse
import asyncio
from collections.abc import Mapping
import os
from pathlib import Path
import sys

import yaml

from bookgen.config import load_settings
from bookgen.schemas import PageLayoutAST
from bookgen.adapters.llm.gemini import _gemini_json_schema


class ProviderCheckError(RuntimeError):
    """The configured model provider could not complete its check request."""


def _check_prompt() -> str:
    path = Path(__file__).resolve().parents[4] / "config" / "prompts" / "provider_check.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    prompt = document.get("text") if isinstance(document, Mapping) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ProviderCheckError(f"Provider check prompt is missing or invalid: {path}")
    return prompt.strip()


def _client_factory(*, vertexai: bool):
    from google import genai

    return genai.Client(vertexai=vertexai)


def _safe_error(exc: Exception, env: Mapping[str, str]) -> str:
    message = str(exc) or type(exc).__name__
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        secret = env.get(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return message


async def check_provider(settings, *, env=None, client_factory=None) -> str:
    """Check local mock configuration or make one minimal request to the live provider."""
    environment = env if env is not None else os.environ
    config = settings.llm
    if config.provider == "mock":
        return "PASS: mock provider is configured; no API key or network request is required."

    vertexai = config.transport_mode == "vertex"
    if not vertexai and not any(environment.get(name, "").strip() for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY")):
        raise ProviderCheckError(
            "No developer API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY in this terminal."
        )

    factory = client_factory or _client_factory
    client = None
    try:
        client = factory(vertexai=vertexai)
        response = await client.aio.models.generate_content(
            model=config.model,
            contents=_check_prompt(),
            config={
                "response_mime_type": "application/json",
                "response_json_schema": _gemini_json_schema(PageLayoutAST),
            },
        )
        if not isinstance(getattr(response, "text", None), str) or not response.text.strip():
            raise ProviderCheckError("The provider returned an empty response to the check request.")
        PageLayoutAST.model_validate_json(response.text)
    except ProviderCheckError:
        raise
    except Exception as exc:
        raise ProviderCheckError(f"Provider request failed ({type(exc).__name__}): {_safe_error(exc, environment)}") from exc
    finally:
        if client is not None:
            await client.aio.aclose()

    transport = "Vertex AI" if vertexai else "Gemini developer API"
    return f"PASS: {transport} responded successfully using configured model '{config.model}'."


async def _run_cli() -> int:
    try:
        message = await check_provider(load_settings())
    except ProviderCheckError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAIL: unable to load provider configuration ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the configured LLM provider and credentials.")
    parser.parse_args()
    raise SystemExit(asyncio.run(_run_cli()))


if __name__ == "__main__":
    main()
