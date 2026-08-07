from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    tenant_id: str = "default"
    refl_interval_minutes: int = 10
    compact_threshold_chars: int = 8000
    compact_keep_recent: int = 8
    learn_trace_threshold: int = 10
    daily_review_hour: int = 8
    llm_provider: str = "anthropic"
    llm_base_url: str = "http://localhost:20128/v1"
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.7
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    vector_top_k: int = 5
    skills_dir: str = ".midream/skills"
    agents_dir: str = ".midream/agents"
    agent_max_iterations: int = 5
    enable_shell_tool: bool = False
    tool_workdir: str = "."


settings = Settings()
