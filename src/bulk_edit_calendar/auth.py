from __future__ import annotations

import json
import threading
from collections.abc import Callable

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import AppPaths, save_client_config

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
KEYRING_SERVICE = "bulk-edit-calendar"
KEYRING_ACCOUNT = "google-oauth-token"


class AuthManager:
    def __init__(
        self,
        paths: AppPaths,
        get_secret: Callable[[str, str], str | None] = keyring.get_password,
        set_secret: Callable[[str, str, str], None] = keyring.set_password,
        delete_secret: Callable[[str, str], None] = keyring.delete_password,
    ):
        self.paths = paths
        self._get_secret = get_secret
        self._set_secret = set_secret
        self._delete_secret = delete_secret
        self._lock = threading.RLock()
        self._connecting = False
        self._error: str | None = None

    def import_client_config(self, payload: str) -> None:
        save_client_config(self.paths, payload)
        self._error = None

    def status(self) -> dict[str, object]:
        credentials = self._load_credentials(refresh=False)
        return {
            "client_configured": self.paths.credentials_file.exists(),
            "connected": bool(credentials and (credentials.valid or credentials.refresh_token)),
            "connecting": self._connecting,
            "error": self._error,
        }

    def connect(self) -> None:
        with self._lock:
            if self._connecting:
                return
            if not self.paths.credentials_file.exists():
                raise ValueError("Import Desktop OAuth credentials first")
            self._connecting = True
            self._error = None
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self) -> None:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.paths.credentials_file), SCOPES)
            credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
            self._save_credentials(credentials)
        except Exception as exc:  # surfaced to the local UI, without token details
            self._error = f"Google authorization failed: {exc}"
        finally:
            self._connecting = False

    def credentials(self) -> Credentials:
        credentials = self._load_credentials(refresh=True)
        if credentials is None or not credentials.valid:
            raise PermissionError("Connect a Google account first")
        return credentials

    def logout(self) -> None:
        with self._lock:
            try:
                self._delete_secret(KEYRING_SERVICE, KEYRING_ACCOUNT)
            except keyring.errors.PasswordDeleteError:
                pass
            self._error = None

    def _load_credentials(self, refresh: bool) -> Credentials | None:
        raw = self._get_secret(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if not raw:
            return None
        try:
            credentials = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
            if refresh and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self._save_credentials(credentials)
            return credentials
        except Exception as exc:
            self._error = f"Stored authorization is unavailable: {exc}"
            return None

    def _save_credentials(self, credentials: Credentials) -> None:
        self._set_secret(KEYRING_SERVICE, KEYRING_ACCOUNT, credentials.to_json())
