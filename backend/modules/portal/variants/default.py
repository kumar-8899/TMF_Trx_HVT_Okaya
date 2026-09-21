"""portal `default` variant — the user portal's server side: the PDF library today; the troubleshooting
assistant + case log attach here next (docs/contracts/PORTAL.md). The manual itself (framework user
pages + an app's own `app/<name>/portal/*.md`) is served by the help module; the portal UI composes
both — modules never depend on each other (CORE.md §6.1)."""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.portal.api import build_router
from modules.portal.library import Library


class DefaultPortal:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.library = Library(core, config)
        self.router = build_router(self)

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultPortal":
        return cls(core, config)

    async def init(self) -> None:
        await self.library.reindex()          # rebuild the in-memory search index from durable records

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        docs = await self.library.list()
        mode = "fts5" if self.library.index.fts else "substring"
        return Health(status=HealthStatus.OK, detail=f"{len(docs)} document(s) · search={mode}")
