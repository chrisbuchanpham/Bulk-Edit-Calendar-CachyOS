from pathlib import Path

import httpx2
import pytest

from bulk_edit_calendar.app import create_app
from bulk_edit_calendar.config import AppPaths
from bulk_edit_calendar.presets import PresetStore


class FakeAuth:
    def status(self):
        return {"client_configured": False, "connected": False, "connecting": False, "error": None}

    def import_client_config(self, _payload):
        pass

    def connect(self):
        pass

    def logout(self):
        pass


class FakeEngine:
    def clear_session(self):
        pass

    def list_calendars(self):
        return []


def build_app(tmp_path: Path):
    paths = AppPaths(tmp_path, tmp_path, tmp_path / "credentials.json", tmp_path / "presets.db")
    app = create_app(paths, FakeAuth(), FakeEngine(), PresetStore(paths.presets_db))
    return app


@pytest.mark.anyio
async def test_root_has_security_headers_and_no_openapi(tmp_path):
    app = build_app(tmp_path)
    transport = httpx2.ASGITransport(app, client=("127.0.0.1", 50000))
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "Bulk Edit Calendar" in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert (await client.get("/openapi.json")).status_code == 404


@pytest.mark.anyio
async def test_untrusted_host_and_csrf_are_rejected(tmp_path):
    app = build_app(tmp_path)
    transport = httpx2.ASGITransport(app, client=("127.0.0.1", 50000))
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        assert (await client.get("/", headers={"host": "evil.example"})).status_code == 400
        assert (await client.post("/api/auth/logout")).status_code == 403
        token = app.state.bulk_edit.csrf_token
        assert (await client.post("/api/auth/logout", headers={"X-CSRF-Token": token})).status_code == 200
