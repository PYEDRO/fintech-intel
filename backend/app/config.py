from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemma-4-26b-it"

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

    @field_validator("llm_api_key")
    @classmethod
    def reject_placeholder_key(cls, v: str) -> str:
        if "your-key" in v or "your_key" in v:
            return ""
        return v

    class Config:
        env_file = (".env", "../.env")
        extra = "ignore"


settings = Settings()
