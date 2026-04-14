"""
Sprint 2 — Retrieval Worker (IMPLEMENTED)
==========================================
Tìm kiếm chunks bằng chứng từ Knowledge Base bằng ChromaDB + SentenceTransformers.

Stateless: không đọc/ghi state ngoài những gì khai báo trong contract.
Test độc lập: python workers/retrieval.py
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

WORKER_NAME = "retrieval_worker"
_BASE_DIR = Path(__file__).parent.parent
CHROMA_DB_PATH = str(_BASE_DIR / "chroma_db")
COLLECTION_NAME = "day09_docs_openai"  # Đổi tên để build lại index mới tránh xung đột size embedding
DOCS_DIR = str(_BASE_DIR / "data" / "docs")
EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_TOP_K = 3

_collection_cache = None


def _get_collection():
    """Lấy hoặc tạo ChromaDB collection. Build index nếu chưa có."""
    global _collection_cache
    if _collection_cache is not None:
        return _collection_cache

    ef = embedding_functions.OpenAIEmbeddingFunction(
        api_key=os.environ.get("OPENAI_API_KEY"),
        model_name=EMBEDDING_MODEL
    )
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    col = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    if col.count() == 0:
        print("[RETRIEVAL] Building ChromaDB index from docs...")
        _build_index(col)
    _collection_cache = col
    return col


def _build_index(collection):
    """Build ChromaDB index từ tất cả tài liệu .txt trong data/docs/."""
    docs_path = Path(DOCS_DIR)
    ids, documents, metadatas = [], [], []
    for fname in sorted(os.listdir(docs_path)):
        if not fname.endswith(".txt"):
            continue
        content = (docs_path / fname).read_text(encoding="utf-8")
        paragraphs = [p.strip() for p in content.split("\n\n") if len(p.strip()) >= 30]
        for i, para in enumerate(paragraphs):
            ids.append(f"chunk_{fname}_{i:03d}")
            documents.append(para)
            metadatas.append({"source": fname, "chunk_index": i})
    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        print(f"[RETRIEVAL] Indexed {len(ids)} chunks from {DOCS_DIR}")
    return collection


def build_index():
    """Public function để build index từ ngoài."""
    col = _get_collection()
    return col


def search(query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
    """
    Search ChromaDB với query text.
    Score = cosine similarity [0, 1].
    """
    col = _get_collection()
    n = min(top_k, col.count())
    if n == 0:
        return []

    results = col.query(
        query_texts=[query],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )
    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        # ChromaDB cosine distance [0,2] → similarity [0,1]
        sim = max(0.0, min(1.0, 1.0 - dist / 2.0))
        chunks.append({
            "text": doc,
            "source": meta.get("source", "unknown"),
            "score": round(sim, 4),
            "metadata": meta,
        })
    chunks.sort(key=lambda x: x["score"], reverse=True)
    return chunks


# Also expose as retrieve_dense for mcp_server compatibility
def retrieve_dense(query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
    return search(query, top_k)


# ─────────────────────────────────────────────────────────────────────────────
# Worker Entry Point — run(state)
# ─────────────────────────────────────────────────────────────────────────────

def run(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieval Worker — theo contract worker_contracts.yaml.
    Input:  task (str), top_k (int optional)
    Output: retrieved_chunks, retrieved_sources, worker_io_logs (append)
    """
    task = state.get("task", "")
    top_k = state.get("top_k", DEFAULT_TOP_K)

    io_log = {
        "worker": WORKER_NAME,
        "input": {"task": task[:120], "top_k": top_k},
        "timestamp_start": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        chunks = search(query=task, top_k=top_k)
        sources = list(dict.fromkeys(c["source"] for c in chunks))

        io_log.update({
            "output": {"chunks_found": len(chunks), "sources": sources,
                       "top_score": chunks[0]["score"] if chunks else 0.0},
            "status": "success",
            "timestamp_end": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })

        updated = dict(state)
        updated["retrieved_chunks"] = chunks
        updated["retrieved_sources"] = sources
        updated.setdefault("worker_io_logs", [])
        updated["worker_io_logs"].append(io_log)

        print(f"[RETRIEVAL] {len(chunks)} chunks | sources={sources} | "
              f"top_score={chunks[0]['score'] if chunks else 0:.3f}")
        return updated

    except Exception as e:
        io_log.update({
            "status": "error",
            "error": {"code": "RETRIEVAL_FAILED", "reason": str(e)},
            "timestamp_end": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        updated = dict(state)
        updated["retrieved_chunks"] = []
        updated["retrieved_sources"] = []
        updated.setdefault("worker_io_logs", [])
        updated["worker_io_logs"].append(io_log)
        print(f"[RETRIEVAL] ERROR: {e}")
        return updated


# ─────────────────────────────────────────────────────────────────────────────
# Standalone Test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("RETRIEVAL WORKER — Standalone Test")
    print("=" * 60)

    test_cases = [
        "SLA ticket P1 là bao lâu?",
        "Hoàn tiền trong bao nhiêu ngày?",
        "Cấp quyền Level 3 cần ai phê duyệt?",
        "Tài khoản bị khóa sau bao nhiêu lần đăng nhập sai?",
        "Nhân viên được làm remote tối đa mấy ngày?",
    ]

    for query in test_cases:
        print(f"\nQuery: {query}")
        result = run({"task": query})
        chunks = result["retrieved_chunks"]
        print(f"  Found {len(chunks)} chunks | Sources: {result['retrieved_sources']}")
        if chunks:
            print(f"  Top: [{chunks[0]['score']:.3f}] {chunks[0]['source']}: "
                  f"{chunks[0]['text'][:100]}...")
