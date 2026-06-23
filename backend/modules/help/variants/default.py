"""help `default` variant — serves the catalog'd markdown (audience-gated).

User pages = all signed-in users; dev pages = super_admin (HELP.DEV). The route
guards the audience; this layer filters the catalog by `include_dev`.
"""

from __future__ import annotations

from core.framework.contract import CoreServices
from modules.help import catalog
from modules.help.api import build_router


class DefaultHelp:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.router = build_router(self)

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultHelp":
        return cls(core, config)

    async def init(self) -> None: pass
    async def start(self) -> None: pass
    async def stop(self) -> None: pass

    def _visible(self, include_dev: bool):
        return [p for p in catalog.PAGES if p.audience == "user" or include_dev]

    def index(self, *, include_dev: bool) -> list[dict]:
        """Sidebar tree: [{section, audience, pages:[{id,title,route,audience}]}]."""
        sections: dict[str, dict] = {}
        for p in self._visible(include_dev):
            s = sections.setdefault(p.section, {"section": p.section, "audience": p.audience, "pages": []})
            s["pages"].append({"id": p.id, "title": p.title, "route": p.route, "audience": p.audience})
        return list(sections.values())

    def page(self, page_id: str, *, include_dev: bool) -> dict | None:
        p = catalog.get(page_id)
        if p is None or (p.audience == "dev" and not include_dev):
            return None
        md = catalog.read(p)
        if md is None:
            return {"id": p.id, "title": p.title, "audience": p.audience,
                    "markdown": f"# {p.title}\n\n_Documentation page not found: `{p.file}`._", "missing": True}
        return {"id": p.id, "title": p.title, "audience": p.audience, "section": p.section,
                "route": p.route, "markdown": md}

    def for_route(self, route: str, *, include_dev: bool) -> dict | None:
        """Context-aware: the best page documenting an app route (longest match)."""
        best = None
        for p in self._visible(include_dev):
            if p.route and (route == p.route or route.startswith(p.route + "/")):
                if best is None or len(p.route) > len(best.route):
                    best = p
        return {"id": best.id, "title": best.title} if best else None

    def search(self, query: str, *, include_dev: bool) -> list[dict]:
        q = query.lower().strip()
        if not q:
            return []
        hits = []
        for p in self._visible(include_dev):
            md = catalog.read(p) or ""
            hay = (p.title + "\n" + md).lower()
            if q in hay:
                idx = md.lower().find(q)
                snippet = (md[max(0, idx - 40):idx + 80].replace("\n", " ").strip()) if idx >= 0 else ""
                hits.append({"id": p.id, "title": p.title, "section": p.section,
                             "audience": p.audience, "snippet": snippet})
        return hits[:50]
