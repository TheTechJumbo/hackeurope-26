from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # AI
    openai_api_key: str = ""
    paid_api_key: str = ""
    default_provider: str = "openai"
    default_model: str = "gpt-4o"
    llm_temperature: float = 0.0

    # Web Search
    serper_api_key: str = ""

    # External integrations (optional)
    google_gemini_api_key: str = ""
    elevenlabs_api_key: str = ""
    stripe_secret_key: str = ""
    sendgrid_api_key: str = ""
    miro_api_token: str = ""
    miro_board_id: str = ""

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Storage backend
    storage_backend: str = "supabase"

    # App
    app_name: str = "AgentFlow"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()
