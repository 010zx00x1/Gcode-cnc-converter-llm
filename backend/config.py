"""
Configuración del backend. Lee de .env y llm_config.json.
UN SOLO LUGAR para toda la config.
"""
import json
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List


LLM_CONFIG_PATH = Path(__file__).parent / "data" / "llm_config.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # API Keys (solo desde .env, nunca hardcoded)
    openai_api_key:    str = Field(default="", validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    # Pipeline
    max_correction_attempts: int   = Field(default=3,    validation_alias="MAX_CORRECTION_ATTEMPTS")
    deviation_threshold_mm:  float = Field(default=0.01, validation_alias="DEVIATION_THRESHOLD_MM")
    max_file_size_kb:        int   = Field(default=500,  validation_alias="MAX_FILE_SIZE_KB")
    translation_timeout_sec: int   = Field(default=120,  validation_alias="TRANSLATION_TIMEOUT_SEC")

    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        validation_alias="CORS_ORIGINS",
    )


def load_llm_config() -> dict:
    """Carga la configuración del LLM desde llm_config.json."""
    if not LLM_CONFIG_PATH.exists():
        return _default_llm_config()
    with open(LLM_CONFIG_PATH, "r") as f:
        return json.load(f)


def save_llm_config(config: dict) -> None:
    """Guarda la configuración del LLM en llm_config.json."""
    LLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LLM_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def _default_llm_config() -> dict:
    return {
        "provider":      "openai",
        "model":         "gpt-4o",
        "api_key_env":   "OPENAI_API_KEY",
        "temperature":   0.1,
        "max_tokens":    2048,
        "timeout_seconds": 30,
        "available_providers": [
            {"id": "openai",    "models": ["gpt-4o", "gpt-4o-mini"]},
            {"id": "anthropic", "models": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]},
            {"id": "ollama",    "models": ["codellama:13b", "llama3:8b"],
             "base_url": "http://localhost:11434"}
        ]
    }


settings = Settings()
