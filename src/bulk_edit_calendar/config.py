from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_data_path

APP_NAME = "bulk-edit-calendar"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    credentials_file: Path
    presets_db: Path

    @classmethod
    def discover(cls) -> AppPaths:
        config_dir = user_config_path(APP_NAME, ensure_exists=True)
        data_dir = user_data_path(APP_NAME, ensure_exists=True)
        os.chmod(config_dir, 0o700)
        os.chmod(data_dir, 0o700)
        return cls(
            config_dir=config_dir,
            data_dir=data_dir,
            credentials_file=config_dir / "credentials.json",
            presets_db=data_dir / "presets.sqlite3",
        )


def validate_client_config(payload: str | bytes | dict) -> dict:
    if isinstance(payload, (str, bytes)):
        data = json.loads(payload)
    else:
        data = payload
    installed = data.get("installed")
    required = {"client_id", "client_secret", "auth_uri", "token_uri"}
    if not isinstance(installed, dict) or not required.issubset(installed):
        raise ValueError("Expected Google OAuth credentials for a Desktop app")
    if not str(installed["auth_uri"]).startswith("https://accounts.google.com/"):
        raise ValueError("Unexpected OAuth authorization endpoint")
    if not str(installed["token_uri"]).startswith("https://oauth2.googleapis.com/"):
        raise ValueError("Unexpected OAuth token endpoint")
    return {"installed": installed}


def save_client_config(paths: AppPaths, payload: str | bytes | dict) -> None:
    data = validate_client_config(payload)
    paths.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=paths.config_dir, prefix="credentials-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, paths.credentials_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
