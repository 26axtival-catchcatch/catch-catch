from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

AgentMode = Literal["auto", "fixture", "gemini", "bedrock"]
ResolvedAgentMode = Literal["fixture", "gemini", "bedrock"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    agent_mode: AgentMode = "bedrock"
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "google_api_key"),
    )
    aws_bearer_token_bedrock: SecretStr | None = None
    aws_region: str = Field(
        default="us-east-1",
        min_length=1,
        validation_alias=AliasChoices("AWS_REGION", "AWS_DEFAULT_REGION"),
    )
    bedrock_model: str = Field(default="us.anthropic.claude-opus-4-6-v1", min_length=1)
    bedrock_investigator_model: str = Field(
        default="us.anthropic.claude-sonnet-4-6", pattern=r"\S"
    )
    bedrock_verifier_model: str | None = Field(default=None, pattern=r"\S")
    gemini_model: str = "gemini-3.7-flash"
    gemini_fallback_model: str = "gemini-3.6-flash"
    database_path: Path = Path("data/generated/customer_signal.duckdb")
    artifact_directory: Path = Path("data/run-artifacts")
    journal_path: Path | None = None
    onboarded_sources_dir: Path = Path("data/onboarded-sources")
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_origin: str = "http://127.0.0.1:3000"

    @computed_field
    @property
    def resolved_journal_path(self) -> Path:
        if self.journal_path is not None:
            return self.journal_path
        return self.artifact_directory / "event-journal.sqlite3"

    @computed_field
    @property
    def resolved_agent_mode(self) -> ResolvedAgentMode:
        if self.agent_mode == "auto":
            if (
                self.aws_bearer_token_bedrock
                and self.aws_bearer_token_bedrock.get_secret_value().strip()
            ):
                return "bedrock"
            has_api_key = bool(
                self.gemini_api_key and self.gemini_api_key.get_secret_value().strip()
            )
            return "gemini" if has_api_key else "fixture"

        return self.agent_mode
