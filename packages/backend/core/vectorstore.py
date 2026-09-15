import chromadb

from core.config import get_settings
from core.embeddings import OpenRouterEmbeddings


def get_chroma_collection(reset: bool = False):
    """Return the persistent Chroma collection for the tax KB."""
    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_path)
    if reset:
        try:
            client.delete_collection(settings.chroma_collection)
        except Exception:
            pass  # collection may not exist yet
    # embeddings are computed externally (OpenRouter), so no embedding_function
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


def get_embeddings_client() -> OpenRouterEmbeddings:
    settings = get_settings()
    return OpenRouterEmbeddings(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )
