"""Runtime configuration with safe local defaults."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "payments-scam-copilot"
    log_level: str = "INFO"
    auth_enabled: bool = False
    analyst_api_key: SecretStr | None = None
    operations_api_key: SecretStr | None = None
    allowed_origins: str = "http://localhost:8501"
    rate_limit_per_minute: int = 30
    max_request_bytes: int = 16_384
    langsmith_tracing: bool = False
    langsmith_project: str = "payments-scam-copilot"
    langsmith_api_key: SecretStr | None = None
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    model_provider: str = "nebius"
    model_name: str = "Qwen/Qwen3-30B-A3B-Instruct-2507"
    model_input_cost_per_million_usd: float = 0.0
    model_output_cost_per_million_usd: float = 0.0
    live_model_enabled: bool = False
    nebius_api_key: SecretStr | None = None
    fireworks_api_key: SecretStr | None = None
    pinecone_api_key: SecretStr | None = None
    pinecone_index_name: str = "meridian-policy-rag-v1"
    pinecone_namespace: str = "approved-policy-v1"
    embedding_model_name: str = "Qwen/Qwen3-Embedding-8B"
    rag_backend: str = "local"
    hybrid_search_enabled: bool = True
    reranker_enabled: bool = True
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    mem0_api_key: SecretStr | None = None
    fixtures_dir: Path = Path("data/fixtures")
    policy_dir: Path = Path("knowledge_base/policy")

    @model_validator(mode="after")
    def validate_live_dependencies(self) -> Settings:
        if self.live_model_enabled and self.nebius_api_key is None:
            raise ValueError("NEBIUS_API_KEY is required when LIVE_MODEL_ENABLED=true.")
        if self.rag_backend.lower() == "pinecone":
            if self.nebius_api_key is None or self.pinecone_api_key is None:
                raise ValueError("Nebius and Pinecone keys are required when RAG_BACKEND=pinecone.")
        return self
