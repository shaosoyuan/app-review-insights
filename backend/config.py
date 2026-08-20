"""Configuration module - loads settings from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # LLM
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Data collection
    MAX_REVIEWS: int = int(os.getenv("MAX_REVIEWS", "500"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))

    # Server
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    FRONTEND_PORT: int = int(os.getenv("FRONTEND_PORT", "5173"))

    @property
    def llm_available(self) -> bool:
        return bool(self.OPENAI_API_KEY)


config = Config()
