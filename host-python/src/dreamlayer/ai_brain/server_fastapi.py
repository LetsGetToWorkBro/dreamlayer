"""ai_brain/server_fastapi.py — an OPTIONAL FastAPI mirror of the Brain server.

ADD-alongside: the production server is the stdlib `http.server` in
`ai_brain/server/server.py` and it is NOT replaced or edited. This module gives
builders who prefer ASGI (async handlers, websockets, uvicorn autoreload) a
FastAPI app that wraps the SAME request handler callable, so both servers share
one implementation of the routes.

fastapi/uvicorn are optional (extras group `platform`). When absent, `available`
is False and `make_app`/`serve` return None / raise a clear message — importing
this module never fails and never affects the stdlib server.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

log = logging.getLogger("dreamlayer.server_fastapi")

try:
    from fastapi import FastAPI, Request  # type: ignore
    from fastapi.responses import JSONResponse  # type: ignore
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

available = _HAS_FASTAPI


def make_app(handler: Callable[[str, dict], Any], *, token: Optional[str] = None):
    """Build a FastAPI app. `handler(route, body)->dict` is the same dispatch the
    stdlib server uses. Returns None when FastAPI is not installed.

    Routes:
      GET  /health            -> {"ok": true}
      POST /api/{route}       -> handler(route, json_body)
    An optional bearer `token` gates the POST route (mirrors the stdlib server).
    """
    if not _HAS_FASTAPI:
        log.info("[server_fastapi] fastapi not installed; use the stdlib server")
        return None

    app = FastAPI(title="DreamLayer Brain (FastAPI mirror)")

    @app.get("/health")
    async def health():  # pragma: no cover - exercised only with fastapi present
        return {"ok": True}

    @app.post("/api/{route}")
    async def dispatch(route: str, request: Request):  # pragma: no cover
        if token is not None:
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json() if await request.body() else {}
        try:
            result = handler(route, body)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(result if isinstance(result, dict) else {"result": result})

    return app


def serve(handler: Callable[[str, dict], Any], *, host: str = "127.0.0.1",
          port: int = 8752, token: Optional[str] = None) -> None:
    """Run the FastAPI mirror under uvicorn. Raises RuntimeError if the optional
    deps are missing so a caller who asked for ASGI hears why."""
    if not _HAS_FASTAPI:
        raise RuntimeError("fastapi is not installed (pip install 'dreamlayer[platform]')")
    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        raise RuntimeError("uvicorn is not installed (pip install 'dreamlayer[platform]')") from exc
    uvicorn.run(make_app(handler, token=token), host=host, port=port)
