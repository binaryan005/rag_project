
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Legal Document RAG Backend"
    VERSION: str = "1.0.0"
    API_PREFIX: str = ""

    # Database Settings
    DATABASE_URL: str = "sqlite:///./legal_rag.db"

    # LLM Settings
    GEMINI_API_KEY: str = ""

    # Upload Settings
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: set = {".pdf", ".docx", ".txt"}

    # Chunking & Embedding Settings
    EMBEDDING_MODEL_NAME: str = (
        "sentence-transformers/all-MiniLM-L6-v2"
    )
    EMBEDDING_DIMENSION: int = 384

    # Clause-aware chunking
    CHUNK_SIZE: int = 1200
    CHUNK_OVERLAP: int = 150

    # Web Search Settings - Self-hosted SearXNG
    WEB_SEARCH_ENABLED: bool = True
    SEARXNG_URL: str = "http://localhost:8080"
    SEARXNG_TIMEOUT: float = 25.0
    SEARXNG_CATEGORIES: str = "general"
    SEARXNG_LANGUAGE: str = "en-IN"
    SEARXNG_TIME_RANGE: str = ""

    WEB_SEARCH_MAX_RESULTS: int = 8
    WEB_SEARCH_FETCH_LIMIT: int = 14
    WEB_SEARCH_FETCH_TIMEOUT: float = 18.0
    WEB_SEARCH_MAX_BYTES: int = 3_000_000
    WEB_SEARCH_MIN_CONTENT_CHARS: int = 220
    WEB_SEARCH_MAX_SNIPPET_CHARS: int = 420

    WEB_SEARCH_INCLUDE_SECONDARY: bool = True
    WEB_SEARCH_TARGETED_QUERIES: bool = True

    # SSRF Protection
    WEB_SEARCH_ALLOW_PRIVATE_NETWORKS: bool = False

    WEB_SEARCH_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # Local Cross-Encoder Reranker
    RERANKER_ENABLED: bool = True
    RERANKER_MODEL_NAME: str = (
        "cross-encoder/ms-marco-MiniLM-L-6-v2"
    )

    # Environment Configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8"
    )


settings = Settings()

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
