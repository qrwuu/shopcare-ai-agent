from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, RedisDsn, computed_field, model_validator


class Settings(BaseSettings):
    PROJECT_NAME: str
    API_V1_STR: str

    # Host/server compatibility. BAA_WSGI is kept for copied env files only;
    # this FastAPI app is served by ASGI/uvicorn.
    BAA_HOST: str = "0.0.0.0"
    AGENT_PORT: int = 18001
    BAA_WSGI: str = "waitress"

    # Development CORS allow-list. Do not use wildcard with credentials.
    CORS_ORIGINS: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://10.26.65.226:3000"
    )

    # Database
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return str(PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        ))

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int

    @computed_field
    @property
    def REDIS_URL(self) -> str:
        return str(RedisDsn.build(
            scheme="redis",
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
        ))

    # LLM. The runtime client is OpenAI-compatible Chat Completions via
    # langchain-openai. ANTHROPIC_* names are accepted only as local gateway
    # aliases when OPENAI_* names are not provided.
    OPENAI_BASE_URL: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "qwen-plus"
    EMBEDDING_MODEL: str = "text-embedding-v3"
    EMBEDDING_DIM: int = 1024
    ANTHROPIC_BASE_URL: str = ""
    ANTHROPIC_AUTH_TOKEN: str = ""
    ANTHROPIC_MODEL: str = ""

    # Security
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    # Celery configuration
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    @computed_field
    @property
    def CELERY_BROKER(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @computed_field
    @property
    def CELERY_BACKEND(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    # Risk thresholds
    HIGH_RISK_REFUND_AMOUNT: float = 2000.0
    MEDIUM_RISK_REFUND_AMOUNT: float = 500.0

    # WebSocket and polling
    WEBSOCKET_HEARTBEAT_INTERVAL: int = 30
    WEBSOCKET_RECONNECT_TIMEOUT: int = 60
    STATUS_POLLING_INTERVAL: int = 3

    # Evaluation-only diagnostics. They are disabled in normal runtimes.
    AGENT_EVAL_MODE: bool = False
    EVAL_ISOLATED: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def apply_model_gateway_aliases(self) -> "Settings":
        if not self.OPENAI_BASE_URL and self.ANTHROPIC_BASE_URL:
            base_url = self.ANTHROPIC_BASE_URL.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"
            self.OPENAI_BASE_URL = base_url
        if not self.OPENAI_API_KEY and self.ANTHROPIC_AUTH_TOKEN:
            self.OPENAI_API_KEY = self.ANTHROPIC_AUTH_TOKEN
        if self.LLM_MODEL == "qwen-plus" and self.ANTHROPIC_MODEL:
            self.LLM_MODEL = self.ANTHROPIC_MODEL
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
