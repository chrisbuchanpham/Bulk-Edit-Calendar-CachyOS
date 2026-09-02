import json

import pytest
from google.oauth2.credentials import Credentials

from bulk_edit_calendar.auth import KEYRING_ACCOUNT, KEYRING_SERVICE, SCOPES, AuthManager
from bulk_edit_calendar.config import AppPaths, save_client_config, validate_client_config


def paths(tmp_path):
    return AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "config" / "credentials.json",
        tmp_path / "data" / "presets.db",
    )


def client_json():
    return json.dumps(
        {
            "installed": {
                "client_id": "example.apps.googleusercontent.com",
                "client_secret": "desktop-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    )


def test_client_config_is_validated_and_saved_user_only(tmp_path):
    app_paths = paths(tmp_path)
    save_client_config(app_paths, client_json())
    assert app_paths.credentials_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(app_paths.credentials_file.read_text())["installed"]["client_id"].endswith(
        "googleusercontent.com"
    )


def test_web_credentials_are_rejected():
    with pytest.raises(ValueError, match="Desktop app"):
        validate_client_config({"web": {"client_id": "wrong-kind"}})


def test_tokens_use_injected_keyring_and_status_redacts_them(tmp_path):
    secrets = {}
    manager = AuthManager(
        paths(tmp_path),
        get_secret=lambda service, account: secrets.get((service, account)),
        set_secret=lambda service, account, value: secrets.__setitem__((service, account), value),
        delete_secret=lambda service, account: secrets.pop((service, account)),
    )
    credentials = Credentials(
        token="access-secret",
        refresh_token="refresh-secret",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client",
        client_secret="secret",
        scopes=SCOPES,
    )
    manager._save_credentials(credentials)
    status = manager.status()
    assert status["connected"] is True
    assert "secret" not in json.dumps(status)
    assert "access-secret" in secrets[(KEYRING_SERVICE, KEYRING_ACCOUNT)]
    manager.logout()
    assert secrets == {}
