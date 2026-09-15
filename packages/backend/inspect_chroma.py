"""Quick look at the Chroma store: count, metadata, first few chunks."""

import chromadb

from core.config import get_settings

settings = get_settings()
client = chromadb.PersistentClient(path=settings.chroma_path)
collection = client.get_collection(name=settings.chroma_collection)

print(f"documents: {collection.count()}")
print(f"metadata: {collection.metadata}\n")

results = collection.get(limit=5)
for i, (doc_id, document, metadata) in enumerate(
    zip(results["ids"], results["documents"], results["metadatas"])
):
    print(f"--- chunk {i + 1} ---")
    print(f"id: {doc_id}")
    if metadata:
        print(f"metadata: {metadata}")
    print(f"text: {document[:200]}...\n" if document else "")
