from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    access_token_minutes: int = 60
    storage_dir: Path = Path('./private_uploads')
    max_upload_bytes: int = 10 * 1024 * 1024
    cors_origins: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']
    google_api_key: str = ''
    gemini_model: str = 'gemini-2.5-flash'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @field_validator('database_url')
    @classmethod
    def require_postgres(cls, value: str) -> str:
        if not value.startswith('postgresql+psycopg://'):
            raise ValueError('DATABASE_URL must use postgresql+psycopg://')
        return value

    @field_validator('jwt_secret')
    @classmethod
    def secure_secret(cls, value: str) -> str:
        if len(value) < 32 or value.startswith('REPLACE_'):
            raise ValueError('JWT_SECRET must be a random string of at least 32 characters')
        return value

    @property
    def checkpoint_dsn(self) -> str:
        return self.database_url.replace('postgresql+psycopg://', 'postgresql://', 1)

settings = Settings()
