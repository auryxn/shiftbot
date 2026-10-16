from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str
    database_url: str
    admin_ids: str = "5326093004"
    timezone: str = "Europe/Vilnius"
    reminder_24h_minutes: int = 24 * 60
    reminder_2h_minutes: int = 2 * 60
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}

@lru_cache
def get_settings() -> Settings:
    return Settings()
