from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from googleapiclient.discovery import build
from pydantic import BaseModel

from .auth import AuthManager
from .calendar import CalendarEngine
from .config import AppPaths
from .models import ApplyRequest, NotificationMode, Preset, PreviewRequest
from .presets import PresetStore

PACKAGE_DIR = Path(__file__).parent


class CredentialImport(BaseModel):
    credentials_json: str


class UndoRequest(BaseModel):
    notifications: NotificationMode = NotificationMode.NONE


class AppState:
    def __init__(self, paths: AppPaths, auth: AuthManager, engine: CalendarEngine, presets: PresetStore):
        self.paths = paths
        self.auth = auth
        self.engine = engine
        self.presets = presets
        self.csrf_token = secrets.token_urlsafe(32)


def create_app(
    paths: AppPaths | None = None,
    auth: AuthManager | None = None,
    engine: CalendarEngine | None = None,
    presets: PresetStore | None = None,
) -> FastAPI:
    paths = paths or AppPaths.discover()
    auth = auth or AuthManager(paths)

    def service_provider():
        return build("calendar", "v3", credentials=auth.credentials(), cache_discovery=False)

    engine = engine or CalendarEngine(service_provider)
    presets = presets or PresetStore(paths.presets_db)
    state = AppState(paths, auth, engine, presets)

    app = FastAPI(title="Bulk Edit Calendar", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bulk_edit = state
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0].strip("[]")
        if host not in {"127.0.0.1", "localhost"}:
            return Response("Untrusted host", status_code=400)
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1"}:
            return Response("Loopback access only", status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(supplied, state.csrf_token):
                return Response("Invalid CSRF token", status_code=403)
            origin = request.headers.get("origin")
            if origin and origin not in {
                f"http://127.0.0.1:{request.url.port}",
                f"http://localhost:{request.url.port}",
            }:
                return Response("Untrusted origin", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    async def csrf_guard(x_csrf_token: Annotated[str | None, Header()] = None) -> None:
        if not x_csrf_token or not hmac.compare_digest(x_csrf_token, state.csrf_token):
            raise HTTPException(403, "Invalid CSRF token")

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return Response(str(exc), status_code=400, media_type="text/plain")

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_request: Request, exc: PermissionError):
        return Response(str(exc), status_code=401, media_type="text/plain")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"csrf_token": state.csrf_token})

    @app.get("/api/auth/status")
    async def auth_status():
        return state.auth.status()

    @app.post("/api/auth/import", dependencies=[Depends(csrf_guard)])
    async def auth_import(payload: CredentialImport):
        state.auth.import_client_config(payload.credentials_json)
        return state.auth.status()

    @app.post("/api/auth/connect", dependencies=[Depends(csrf_guard)])
    async def auth_connect():
        state.auth.connect()
        return state.auth.status()

    @app.post("/api/auth/logout", dependencies=[Depends(csrf_guard)])
    async def auth_logout():
        state.engine.clear_session()
        state.auth.logout()
        return state.auth.status()

    @app.get("/api/calendars")
    async def calendars():
        return state.engine.list_calendars()

    @app.post("/api/preview", dependencies=[Depends(csrf_guard)])
    async def preview(payload: PreviewRequest):
        return state.engine.preview(payload)

    @app.post("/api/apply", dependencies=[Depends(csrf_guard)])
    async def apply(payload: ApplyRequest):
        return state.engine.apply(payload)

    @app.post("/api/undo", dependencies=[Depends(csrf_guard)])
    async def undo(payload: UndoRequest):
        return state.engine.undo(payload.notifications)

    @app.get("/api/presets")
    async def list_presets():
        return state.presets.list()

    @app.post("/api/presets", dependencies=[Depends(csrf_guard)])
    async def save_preset(payload: Preset):
        return state.presets.save(payload)

    @app.delete("/api/presets/{preset_id}", dependencies=[Depends(csrf_guard)])
    async def delete_preset(preset_id: int):
        if not state.presets.delete(preset_id):
            raise HTTPException(404, "Preset not found")
        return {"deleted": True}

    return app
