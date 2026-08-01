"""ai_brain/server_fastapi.py — an OPTIONAL ASGI adapter for a dispatch
function you supply.

WHAT THIS IS NOT, stated first because the file used to claim otherwise. It is
not a mirror of the Brain server, and it does not "share one implementation of
the routes" with it. The production server is the stdlib `http.server` in
`ai_brain/server/server.py`, which dispatches through `_GET_ROUTES` /
`_POST_ROUTES` — dicts of bound handler methods taking `(self, path, qs)`.
There is no `handler(route, body) -> dict` callable anywhere in this tree for
this module to wrap. Anyone reading the old docstring would have gone looking
for one, not found it, and had to reimplement dispatch themselves — while the
capability catalogue advertised the routes as already shared.

So this is the honest version of the same offer: if you are building something
ASGI-shaped (async handlers, websockets, uvicorn autoreload) and you have your
own dispatch function, this wires it to FastAPI with the auth and the error
envelope already handled. Bring your own routes.

AUTH IS NOT OPTIONAL HERE, and that is the second thing that changed. `token`
used to default to `None`, which meant no bearer check at all — so the "mirror"
of a token-gated server served every route it had to anyone who could reach the
port. It is now keyword-only and required; `token=None` still works but is an
explicit refusal that logs, so an unauthenticated surface is something somebody
typed rather than something they forgot.

fastapi/uvicorn are optional (extras group `platform`). When absent, `available`
is False and `make_app`/`serve` return None / raise a clear message — importing
this module never fails and never affects the stdlib server.
"""
from __future__ import annotations

import hmac
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


def make_app(handler: Callable[[str, dict], Any], *, token: Optional[str]):
    """Build a FastAPI app around YOUR `handler(route, body) -> dict`.

    Returns None when FastAPI is not installed.

    Routes:
      GET  /health            -> {"ok": true}
      POST /api/{route}       -> handler(route, json_body)

    `token` is keyword-only and has no default: a bearer token gates the POST
    route, and passing `None` is an explicit "serve this unauthenticated", which
    is logged as a warning. It used to default to None, so forgetting the
    argument and deciding not to authenticate looked identical from the call
    site — on a route that hands arbitrary strings to a dispatch function.
    """
    if not _HAS_FASTAPI:
        log.info("[server_fastapi] fastapi not installed; use the stdlib server")
        return None

    app = FastAPI(title="DreamLayer ASGI adapter")

    @app.get("/health")
    async def health():  # pragma: no cover - exercised only with fastapi present
        return {"ok": True}

    if token is None:
        log.warning("[server_fastapi] no token — /api/{route} is UNAUTHENTICATED; "
                    "anything that can reach this port can call your dispatch")

    @app.post("/api/{route}")
    async def dispatch(route: str, request: Request):  # pragma: no cover
        if token is not None:
            auth = request.headers.get("authorization", "")
            # Constant-time, like the stdlib server's own check: a plain `!=`
            # on a secret leaks its prefix to anyone who can time the response.
            if not hmac.compare_digest(auth, f"Bearer {token}"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json() if await request.body() else {}
        try:
            result = handler(route, body)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(result if isinstance(result, dict) else {"result": result})

    return app


def serve(handler: Callable[[str, dict], Any], *, token: Optional[str],
          host: str = "127.0.0.1", port: int = 8752) -> None:
    """Run the adapter under uvicorn. Raises RuntimeError if the optional deps
    are missing so a caller who asked for ASGI hears why. `token` is
    keyword-only and required, for the reason `make_app` gives."""
    if not _HAS_FASTAPI:
        raise RuntimeError("fastapi is not installed (pip install 'dreamlayer[platform]')")
    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        raise RuntimeError("uvicorn is not installed (pip install 'dreamlayer[platform]')") from exc
    uvicorn.run(make_app(handler, token=token), host=host, port=port)
