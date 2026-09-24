"""Top-level API router.

Aggregates the base routes plus any overlay-contributed routers, all wired at
import time. Overlays add routers through ``_fragments/<overlay-id>/api_router.py.jinja``
(assembled in ``overlay_order``), each fragment a 4-space-indented block that
imports its router and calls ``api_router.include_router(...)``. Overlays never
mount routers from a lifespan hook and never touch ``app.openapi_schema``.

An overlay that needs a dependency applied to every route on ``api_router``
(for example ``auth``'s bearer-token check) contributes to the
``api_router_deps.py`` slot: a statement (or a few) appending to
``_api_router_dependencies`` below, doing any import it needs locally inside
a helper function (same local-import convention as every ``health.py`` /
``lifespan.py`` fragment) so the base file never needs a conditional import
of its own. Skipped (renders empty) when no selected overlay ships it, in
which case ``api_router`` gets an empty dependency list - identical behavior
to the previous plain ``APIRouter()``.
"""

from fastapi import APIRouter
from fastapi.params import Depends

from .routes import root

# Overlays needing a dependency applied to every api_router route append to
# this list, in overlay_order (see _fragments/<overlay-id>/api_router_deps.py.jinja).
# `fastapi.params.Depends` is the class the `fastapi.Depends(...)` call returns
# (not the callable itself - that isn't a valid type annotation).
_api_router_dependencies: list[Depends] = []


api_router = APIRouter(dependencies=_api_router_dependencies)
api_router.include_router(root.router)


def _include_overlay_routers() -> None:
    """Attach overlay-contributed routers. Body assembled at render time."""
    from receipt_parser_backend.llm.openai.routes import router as _llm_openai_router

    api_router.include_router(_llm_openai_router)

    from receipt_parser_backend.langchain.routes import router as _langchain_router

    api_router.include_router(_langchain_router)


_include_overlay_routers()
