from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    env: str = "development"
    mongo_uri: str
    mongo_db: str = "tickethub"
    redis_url: str
    cors_origins: str = "http://localhost:3000"
    hold_minutes: int = 15
    jwt_secret: str
    access_token_minutes: int = 15
    refresh_token_days: int = 7

settings = Settings()