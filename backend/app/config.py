from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Database
    db_path: str = "data/fintech.db"
    faiss_index_path: str = "data/faiss.index"
    faiss_meta_path: str = "data/faiss_meta.json"

    # Embedding
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # RAG
    rag_top_k: int = 10

    # Classifier
    classifier_batch_size: int = 20

    @field_validator("deepseek_api_key")
    @classmethod
    def reject_placeholder_key(cls, v: str) -> str:
        if "your-key" in v or "your_key" in v:
            return ""
        return v

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
