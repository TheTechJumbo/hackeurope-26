"""Singleton Supabase client — one connection reused everywhere."""

from functools import lru_cache

from pydantic_settings import BaseSettings
from supabase import Client, create_client


class SupabaseSettings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a cached Supabase client (created once, reused forever)."""
    settings = SupabaseSettings()
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(settings.supabase_url, settings.supabase_key)
