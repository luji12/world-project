import os
import chromadb
import config

_client = None
_current_chroma_path = None


def get_client():
    global _client, _current_chroma_path
    
    chroma_path = os.path.join(config.MEMORY_DIR, "chroma_db")
    if _client is None or _current_chroma_path != chroma_path:
        os.makedirs(chroma_path, exist_ok=True)
        try:
            # PersistentClient automatically handles SQLite connections for the given path
            _client = chromadb.PersistentClient(path=chroma_path)
            _current_chroma_path = chroma_path
        except Exception as e:
            import sys
            print(f"[chroma] Failed to initialize at {chroma_path}: {e}", file=sys.stderr)
            raise
    return _client


def reset_client():
    global _client, _current_chroma_path
    _client = None
    _current_chroma_path = None


def get_or_create_collection(char_id: str):
    client = get_client()
    safe_name = f"mem_{char_id.replace('-', '_').replace('.', '_')}"
    try:
        return client.get_collection(safe_name)
    except Exception:
        return client.create_collection(safe_name, metadata={"char_id": char_id})


def add_memory_embedding(char_id: str, memory_id: str, content: str, metadata: dict):
    collection = get_or_create_collection(char_id)
    try:
        collection.add(
            documents=[content],
            metadatas=[metadata],
            ids=[memory_id],
        )
    except Exception:
        try:
            collection.update(
                ids=[memory_id],
                documents=[content],
                metadatas=[metadata],
            )
        except Exception:
            pass


def search_memories(char_id: str, query: str, top_k: int = 15) -> list:
    collection = get_or_create_collection(char_id)
    try:
        count = collection.count()
        if count == 0:
            return []
        results = collection.query(
            query_texts=[query],
            n_results=min(top_k, count),
        )
        memories = []
        if results["ids"] and results["ids"][0]:
            for i, mem_id in enumerate(results["ids"][0]):
                memories.append({
                    "id": mem_id,
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 0,
                })
        return memories
    except Exception:
        return []
