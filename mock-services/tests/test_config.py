import json

import pytest
from pydantic import ValidationError

from app.config import CLOUDFLARE_D1_API_URL, LOCAL_D1_API_URL, LOCAL_D1_DATABASE_ID, PROJECT_DIR, Settings

LOCAL_D1_CONFIG = PROJECT_DIR.parent / "dev" / "d1-local" / "wrangler.json"


def test_local_settings_match_the_local_d1_server():
    config = json.loads(LOCAL_D1_CONFIG.read_text(encoding="utf-8"))
    assert f"http://{config['dev']['ip']}:{config['dev']['port']}/client/v4" == LOCAL_D1_API_URL
    binding = next(d for d in config["d1_databases"] if d["database_id"] == LOCAL_D1_DATABASE_ID)
    assert binding["migrations_dir"] == "../../mock-services/migrations"


def test_local_mode_never_uses_remote_d1_even_if_configured():
    settings = Settings(
        _env_file=None,
        halcyon_env="local",
        cloudflare_account_id="real-account",
        d1_api_token="real-token",
        mock_d1_database_id="real-db",
    )
    assert settings.d1.api_url == LOCAL_D1_API_URL
    assert settings.d1.database_id == LOCAL_D1_DATABASE_ID


def test_deployed_mode_uses_only_explicit_values():
    settings = Settings(
        _env_file=None,
        halcyon_env="production",
        cloudflare_account_id="acct",
        d1_api_token="tok",
        mock_d1_database_id="db",
        mock_services_token="secret",
    )
    assert settings.d1.api_url == CLOUDFLARE_D1_API_URL
    assert (settings.d1.account_id, settings.d1.database_id, settings.d1.api_token) == ("acct", "db", "tok")


def test_deployed_mode_requires_a_token():
    with pytest.raises(ValidationError, match="MOCK_SERVICES_TOKEN"):
        Settings(_env_file=None, halcyon_env="staging")
    assert Settings(_env_file=None, halcyon_env="local").mock_services_token == ""
