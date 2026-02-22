from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI
    openai_api_key: str = ""
    google_gemini_api_key: str = ""
    paid_api_key: str = ""
    default_provider: str = ""
    default_model: str = ""
    llm_temperature: float = 0.0

    # Voice
    elevenlabs_api_key: str = ""

    # Payments
    stripe_secret_key: str = ""

    # Communication
    sendgrid_api_key: str = ""

    # Web Search
    serper_api_key: str = ""

    # Visual Memory
    miro_api_token: str = ""
    miro_board_id: str = ""

    # Database — sync sqlite3 used for MVP simplicity
    database_url: str = "sqlite:///./agentflow.db"

    # App
    app_name: str = "AgentFlow"
    debug: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
