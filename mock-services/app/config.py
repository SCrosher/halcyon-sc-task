from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parent.parent

CLOUDFLARE_D1_API_URL = "https://api.cloudflare.com/client/v4"
# Must match dev/d1-local/wrangler.json (checked by tests/test_config.py).
LOCAL_D1_API_URL = "http://127.0.0.1:8711/client/v4"
LOCAL_D1_DATABASE_ID = "halcyon-mock-services-local"


@dataclass(frozen=True)
class D1Settings:
    api_url: str
    account_id: str
    database_id: str
    api_token: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_DIR.parent / ".env", extra="ignore")

    # "local" (the default) always uses the local D1 server, whatever else is configured.
    # Deployed containers get "staging" or "production" plus their D1 values from the deploy.
    halcyon_env: Literal["local", "staging", "production"] = "local"

    # Bearer token callers must send. Empty disables auth, which is only allowed locally.
    mock_services_token: str = ""

    # "Today" for calendars is the date in this timezone, which bounds the dates a calendar can be generated for.
    # Bookings use each restaurant's own local date instead.
    member_timezone: str = "Europe/London"

    # D1 - deployed environments only.
    cloudflare_account_id: str = ""
    d1_api_token: str = ""
    mock_d1_database_id: str = ""

    @model_validator(mode="after")
    def _require_token_when_deployed(self) -> "Settings":
        if self.halcyon_env != "local" and not self.mock_services_token:
            raise ValueError(f"MOCK_SERVICES_TOKEN must be set when HALCYON_ENV is {self.halcyon_env!r}")
        return self

    def today(self) -> date:
        return datetime.now(ZoneInfo(self.member_timezone)).date()

    @property
    def d1(self) -> D1Settings:
        if self.halcyon_env == "local":
            return D1Settings(LOCAL_D1_API_URL, "local", LOCAL_D1_DATABASE_ID, "local")
        return D1Settings(
            CLOUDFLARE_D1_API_URL, self.cloudflare_account_id, self.mock_d1_database_id, self.d1_api_token
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
