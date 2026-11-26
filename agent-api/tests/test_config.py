import json
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from app.config import (
    CLOUDFLARE_D1_API_URL,
    LOCAL_API_TOKEN,
    LOCAL_D1_API_URL,
    LOCAL_D1_DATABASE_ID,
    PROJECT_DIR,
    Settings,
)

LOCAL_D1_CONFIG = PROJECT_DIR.parent / "dev" / "d1-local" / "wrangler.json"


def test_local_settings_match_the_local_d1_server():
    config = json.loads(LOCAL_D1_CONFIG.read_text(encoding="utf-8"))
    assert f"http://{config['dev']['ip']}:{config['dev']['port']}/client/v4" == LOCAL_D1_API_URL
    binding = next(d for d in config["d1_databases"] if d["database_id"] == LOCAL_D1_DATABASE_ID)
    assert binding["migrations_dir"] == "../../agent-api/migrations"


def test_local_mode_never_uses_remote_d1_even_if_configured():
    settings = Settings(
        _env_file=None,
        halcyon_env="local",
        cloudflare_account_id="real-account",
        d1_api_token="real-token",
        agent_d1_database_id="real-db",
    )
    assert settings.d1.api_url == LOCAL_D1_API_URL
    assert settings.d1.database_id == LOCAL_D1_DATABASE_ID


def test_deployed_mode_uses_only_explicit_values():
    settings = Settings(
        _env_file=None,
        halcyon_env="staging",
        cloudflare_account_id="acct",
        d1_api_token="tok",
        agent_d1_database_id="db",
    )
    assert settings.d1.api_url == CLOUDFLARE_D1_API_URL
    assert (settings.d1.account_id, settings.d1.database_id, settings.d1.api_token) == ("acct", "db", "tok")


def test_shared_files_have_not_drifted():
    """Each service is its own container build, so these are copies rather than a shared package."""
    root = PROJECT_DIR.parent
    for path in ("app/db.py", "tests/d1_fake.py"):
        agent = (root / "agent-api" / path).read_text(encoding="utf-8")
        mock = (root / "mock-services" / path).read_text(encoding="utf-8")
        assert agent == mock, f"agent-api/{path} and mock-services/{path} differ"


def test_local_token_only_applies_locally():
    assert Settings(_env_file=None, halcyon_env="local").api_tokens == [LOCAL_API_TOKEN]
    assert Settings(_env_file=None, halcyon_env="production").api_tokens == []
    assert Settings(_env_file=None, halcyon_env="local", agent_api_tokens="a, b").api_tokens == ["a", "b"]


def test_lock_files_satisfy_pyproject():
    """requirements.txt must pin every dependency in pyproject.toml; re-run `npm run lock` if this fails."""
    root = PROJECT_DIR.parent
    for project in ("agent-api", "mock-services"):
        declared = tomllib.loads((root / project / "pyproject.toml").read_text(encoding="utf-8"))
        pins = {}
        for line in (root / project / "requirements.txt").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                name, _, version = line.partition("==")
                pins[canonicalize_name(name)] = version
        for spec in declared["project"]["dependencies"]:
            requirement = Requirement(spec)
            pinned = pins.get(canonicalize_name(requirement.name))
            assert pinned is not None, f"{project}: {requirement.name} is not in requirements.txt"
            assert requirement.specifier.contains(pinned), f"{project}: {requirement.name}=={pinned} breaks {spec!r}"
