from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Required
    ANTHROPIC_API_KEY: str
    APP_SECRET_TOKEN: str

    # Optional with defaults
    ALLOWED_ORIGIN: str = "*"
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/carbcount.db"
    MODEL: str = "claude-sonnet-4-5-20250929"
    MAX_TOKENS: int = 16000
    TEMPERATURE: float = 0.0
    API_TIMEOUT: float = 120.0
    CACHE_HOURS: int = 24
    RATE_LIMIT_PER_HOUR: int = 30
    RATE_LIMIT_PER_DAY: int = 200

    class Config:
        env_file = ".env"


settings = Settings()
