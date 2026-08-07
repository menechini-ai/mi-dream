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
    reflection_cron: str = "0 */6 * * *"
    llm_provider: str = "anthropic"
    llm_base_url: str = "http://localhost:20128/v1"
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    skills_dir: str = ".midream/skills"
    agents_dir: str = ".midream/agents"


settings = Settings()
