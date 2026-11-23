"""Task-local request metadata keeps the public provider port small."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    page_number: int = 1
    rhythm_history: tuple = ()
    recent_archetypes: tuple = ()


request_context = ContextVar("bookgen_provider_context", default=RequestContext())


@contextmanager
def provider_context(**kwargs):
    token = request_context.set(RequestContext(**kwargs))
    try:
        yield
    finally:
        request_context.reset(token)
