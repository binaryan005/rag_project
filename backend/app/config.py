import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Legal Document RAG Backend"
    VERSION: str = "1.0.0"
    API_PREFIX: str = ""
    
    # Database Settings
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://postgres:postgres@localhost:5432/rag_db"
    )
    
    # LLM Settings
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Upload Settings
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: set = {".pdf", ".docx"}
    
    # Chunking & Embedding Settings
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    CHUNK_SIZE: int = 600       # Target characters per chunk
    CHUNK_OVERLAP: int = 100    # Overlap characters between chunks

    # ── Web Search Settings (self-hosted SearXNG, no API keys) ──────────────
    WEB_SEARCH_ENABLED: bool = True
    SEARXNG_URL: str = os.getenv("SEARXNG_URL", "http://localhost:8080")
    SEARXNG_TIMEOUT: float = 25.0
    SEARXNG_CATEGORIES: str = "general"
    SEARXNG_LANGUAGE: str = "en-IN"
    SEARXNG_TIME_RANGE: str = ""            # "", "day", "month", "year"
    WEB_SEARCH_MAX_RESULTS: int = 8         # Citations returned to the user
    WEB_SEARCH_FETCH_LIMIT: int = 14        # Candidate pages fetched & verified
    WEB_SEARCH_FETCH_TIMEOUT: float = 18.0
    WEB_SEARCH_MAX_BYTES: int = 3_000_000   # Hard cap on a fetched page
    WEB_SEARCH_MIN_CONTENT_CHARS: int = 220 # Below this, extraction is a failure
    WEB_SEARCH_MAX_SNIPPET_CHARS: int = 420
    WEB_SEARCH_INCLUDE_SECONDARY: bool = True
    WEB_SEARCH_TARGETED_QUERIES: bool = True  # Also query site: for official sources
    WEB_SEARCH_ALLOW_PRIVATE_NETWORKS: bool = False  # SSRF guard (leave False)
    WEB_SEARCH_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Cross-encoder reranker (local, free, no API keys)
    RERANKER_ENABLED: bool = True
    RERANKER_MODEL_NAME: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
