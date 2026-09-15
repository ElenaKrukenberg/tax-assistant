"""Interactive browser for the Chroma store: semantic search, samples, stats.

Path and collection name come from ``core/config.py`` rather than being written
here a second time - CHROMA_PATH and CHROMA_COLLECTION move the store, and a tool
that ignores them looks at the wrong one.
"""

import json

import chromadb

from core.config import get_settings
from core.vectorstore import get_embeddings_client

settings = get_settings()
client = chromadb.PersistentClient(path=settings.chroma_path)
collection = client.get_collection(name=settings.chroma_collection)

while True:
    print("\n=== CHROMA BROWSER ===")
    print("1. Semantic search")
    print("2. Show N random documents")
    print("3. Search by source_id")
    print("4. Statistics")
    print("5. Exit")

    choice = input("\nChoice (1-5): ").strip()

    if choice == "1":
        query = input("Search query: ")
        # Embed the query ourselves, exactly as services/retrieval.py does, and search
        # by vector. Passing query_texts instead would hand the query to Chroma, which
        # has no embedding_function configured here and falls back to its bundled
        # 384-dimension MiniLM - against a collection of 1536-dimension vectors from
        # openai/text-embedding-3-small. That mismatch is what used to make this
        # option fail (#41). Costs one embeddings call per search.
        query_vector = get_embeddings_client().embed_one(query)
        results = collection.query(query_embeddings=[query_vector], n_results=5)
        for i, (doc_id, doc, meta, dist) in enumerate(zip(
            results['ids'][0], results['documents'][0],
            results['metadatas'][0], results['distances'][0]
        ), 1):
            print(f"\n{i}. ID: {doc_id}")
            print(f"   Distance: {dist:.3f}")
            print(f"   Metadata: {json.dumps(meta, ensure_ascii=False, indent=2)}")
            print(f"   Text: {doc[:150]}...")

    elif choice == "2":
        n = int(input("How many documents? "))
        results = collection.get(limit=n)
        for i, (doc_id, doc, meta) in enumerate(zip(
            results['ids'], results['documents'], results['metadatas']
        ), 1):
            print(f"\n{i}. ID: {doc_id}")
            print(f"   Metadata: {json.dumps(meta, ensure_ascii=False, indent=2)}")
            print(f"   Text: {doc[:150]}...")

    elif choice == "3":
        source = input("source_id: ")
        results = collection.get(where={"source_id": source})
        print(f"\nFound: {len(results['ids'])} documents")
        for doc_id in results['ids'][:5]:
            print(f"  - {doc_id}")

    elif choice == "4":
        all_docs = collection.get()
        print(f"\nTotal documents: {len(all_docs['ids'])}")
        from collections import Counter
        sources = Counter(m.get('source_id') for m in all_docs['metadatas'])
        print("Top sources:")
        for src, cnt in sources.most_common(5):
            print(f"  {src}: {cnt}")

    elif choice == "5":
        break
