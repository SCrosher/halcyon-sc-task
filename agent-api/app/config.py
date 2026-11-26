from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parent.parent

CLOUDFLARE_D1_API_URL = "https://api.cloudflare.com/client/v4"
# Must match dev/d1-local/wrangler.json (checked by tests/test_config.py).
LOCAL_D1_API_URL = "http://127.0.0.1:8711/client/v4"
LOCAL_D1_DATABASE_ID = "halcyon-agent-local"
# Accepted bearer token when running locally without AGENT_API_TOKENS set.
LOCAL_API_TOKEN = "local-dev-token"


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

    # Comma-separated bearer tokens accepted by this API.
    agent_api_tokens: str = ""
    cors_origins: str = "*"

    # Claude
    anthropic_api_key: str = ""
    # Writes every member-facing reply.
    anthropic_model: str = "claude-sonnet-5-5"
    agent_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    # Runs the tool-calling steps of a turn (searches, diary, memory, bookings), then hands over to
    # anthropic_model for the reply. Empty = anthropic_model does everything.
    tool_model: str = "claude-haiku-5-5"
    tool_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    # "default" = Anthropic server-side refusal fallbacks; "off" to disable.
    anthropic_fallbacks: Literal["default", "off"] = "default"
    max_output_tokens: int = 16000

    # Mock services (calendar REST API + restaurant MCP server)
    mock_services_url: str = "http://127.0.0.1:8100"
    mock_services_token: str = ""

    # D1 - deployed environments only.
    cloudflare_account_id: str = ""
    d1_api_token: str = ""
    agent_d1_database_id: str = ""

    # Turn behaviour
    # Post a holding message if no assistant message has gone out for this long (must stay under 12s).
    holding_message_after_seconds: float = 9.0
    turn_timeout_seconds: float = 120.0
    max_model_calls_per_turn: int = 12
    # Earlier turns are dropped from the model's context (they stay in the transcript table).
    max_history_turns: int = Field(default=20, ge=1)
    # The member's most recent earlier conversations given to the model as background, oldest first.
    earlier_conversations: int = Field(default=5, ge=0)
    # request_logs rows older than this are deleted when the service starts.
    request_log_retention_days: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if not 1 <= self.holding_message_after_seconds < 12:
            raise ValueError("HOLDING_MESSAGE_AFTER_SECONDS must be at least 1 and less than 12")
        return self

    @property
    def d1(self) -> D1Settings:
        if self.halcyon_env == "local":
            return D1Settings(LOCAL_D1_API_URL, "local", LOCAL_D1_DATABASE_ID, "local")
        return D1Settings(
            CLOUDFLARE_D1_API_URL, self.cloudflare_account_id, self.agent_d1_database_id, self.d1_api_token
        )

    @property
    def mock_services_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.mock_services_token}"} if self.mock_services_token else {}

    @property
    def api_tokens(self) -> list[str]:
        tokens = [t.strip() for t in self.agent_api_tokens.split(",") if t.strip()]
        if not tokens and self.halcyon_env == "local":
            return [LOCAL_API_TOKEN]
        return tokens


@lru_cache
def get_settings() -> Settings:
    return Settings()
