"""Structural ports for external effects; implementations are injected by callers."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from bookgen.schemas import AtomicTextBlock, BookContext, ImageAssetMeta, PageGenerationResult, PageLayoutAST


@runtime_checkable
class LLMProvider(Protocol):
    async def generate_candidate(
        self,
        *,
        context: BookContext,
        blocks: Sequence[AtomicTextBlock],
        assets: Sequence[ImageAssetMeta],
        strategy_tag: str,
    ) -> PageLayoutAST:
        """Generate one pointer-based candidate using bounded inputs and thumbnails."""
        ...


@runtime_checkable
class StorageAdapter(Protocol):
    def put(self, key: str, data: bytes) -> str:
        """Store bytes under a key and return its storage key."""
        ...

    def get(self, key: str) -> bytes:
        """Read the bytes identified by a storage key."""
        ...


@runtime_checkable
class SessionRepository(Protocol):
    def save_snapshot(self, session_id: str, page: PageGenerationResult) -> None:
        """Persist a page snapshot within its book session."""
        ...

    def load_snapshots(self, session_id: str) -> list[PageGenerationResult]:
        """Read canonical page snapshots for a session in page order."""
        ...
