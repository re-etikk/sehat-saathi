"""Qdrant layer — this is where Qdrant 'earns its place'.

Two collections:
  ss_knowledge : verified medicine / health-routine facts (shared, read-only at runtime)
  ss_memory    : per-user memories (schedule, preferences, corrections, unresolved tasks,
                 adherence log). Every point carries payload filters:
                    user_id, mem_type, lang, active, created_at
                 so one user's context can never leak into another's conversation.

Memory is CORRECTABLE: when the user says "nahi, galat hai", we deactivate the old
point (active=False, superseded_by=<new_id>) and write the corrected one. Nothing is
silently overwritten — the audit trail survives, which matters in a high-trust workflow.
"""
import time
import uuid
from typing import Optional

from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding

import config

_embedder: Optional[TextEmbedding] = None
_client: Optional[QdrantClient] = None
VECTOR_SIZE = 384  # paraphrase-multilingual-MiniLM-L12-v2


def embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=config.EMBED_MODEL)
    return _embedder


def client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY or None)
    return _client


def embed(text: str) -> list[float]:
    return list(embedder().embed([text]))[0].tolist()


def ensure_collections() -> None:
    c = client()
    for name in (config.COLLECTION_KNOWLEDGE, config.COLLECTION_MEMORY):
        if not c.collection_exists(name):
            c.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
            )
    # payload indexes for fast, safe filtering
    for field in ("user_id", "mem_type", "lang", "active"):
        try:
            c.create_payload_index(config.COLLECTION_MEMORY, field_name=field,
                                   field_schema=models.PayloadSchemaType.KEYWORD)
        except Exception:
            pass  # already exists


# ---------------- knowledge ----------------

def add_knowledge(text: str, lang: str, topic: str) -> str:
    pid = str(uuid.uuid4())
    client().upsert(
        collection_name=config.COLLECTION_KNOWLEDGE,
        points=[models.PointStruct(id=pid, vector=embed(text),
                                   payload={"text": text, "lang": lang, "topic": topic})],
    )
    return pid


def search_knowledge(query: str, limit: int = 3) -> list[dict]:
    hits = client().query_points(
        collection_name=config.COLLECTION_KNOWLEDGE,
        query=embed(query), limit=limit, with_payload=True,
    ).points
    return [{"text": h.payload["text"], "topic": h.payload.get("topic", ""), "score": h.score}
            for h in hits if h.score > 0.35]


# ---------------- user memory ----------------

def remember(user_id: str, text: str, mem_type: str, lang: str = "hi") -> str:
    """mem_type: schedule | preference | adherence | unresolved | correction"""
    pid = str(uuid.uuid4())
    client().upsert(
        collection_name=config.COLLECTION_MEMORY,
        points=[models.PointStruct(
            id=pid, vector=embed(text),
            payload={"user_id": user_id, "text": text, "mem_type": mem_type,
                     "lang": lang, "active": "true", "created_at": time.time()},
        )],
    )
    return pid


def recall(user_id: str, query: str, limit: int = 4,
           mem_type: Optional[str] = None) -> list[dict]:
    """STRICT isolation: user_id filter is mandatory, active memories only."""
    must = [
        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
        models.FieldCondition(key="active", match=models.MatchValue(value="true")),
    ]
    if mem_type:
        must.append(models.FieldCondition(key="mem_type", match=models.MatchValue(value=mem_type)))
    hits = client().query_points(
        collection_name=config.COLLECTION_MEMORY,
        query=embed(query),
        query_filter=models.Filter(must=must),
        limit=limit, with_payload=True,
    ).points
    return [{"id": str(h.id), "text": h.payload["text"], "mem_type": h.payload["mem_type"],
             "score": h.score} for h in hits if h.score > 0.3]


def correct_memory(user_id: str, old_query: str, new_text: str, mem_type: str, lang: str) -> dict:
    """Deactivate the closest matching old memory, write the corrected one, keep the audit trail."""
    old = recall(user_id, old_query, limit=1, mem_type=mem_type)
    new_id = remember(user_id, new_text, mem_type, lang)
    superseded = None
    if old:
        superseded = old[0]["id"]
        client().set_payload(
            collection_name=config.COLLECTION_MEMORY,
            payload={"active": "false", "superseded_by": new_id},
            points=[superseded],
        )
    return {"new_id": new_id, "superseded": superseded}


def list_memories(user_id: str) -> list[dict]:
    points, _ = client().scroll(
        collection_name=config.COLLECTION_MEMORY,
        scroll_filter=models.Filter(must=[
            models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
        ]),
        limit=100, with_payload=True,
    )
    out = []
    for p in points:
        out.append({"id": str(p.id), "text": p.payload["text"],
                    "mem_type": p.payload["mem_type"], "active": p.payload["active"],
                    "created_at": p.payload.get("created_at")})
    return sorted(out, key=lambda x: x.get("created_at") or 0, reverse=True)


def delete_memory(user_id: str, point_id: str) -> bool:
    """Hard delete — the user's right to be forgotten."""
    # verify ownership before deleting
    pts = client().retrieve(config.COLLECTION_MEMORY, ids=[point_id], with_payload=True)
    if not pts or pts[0].payload.get("user_id") != user_id:
        return False
    client().delete(config.COLLECTION_MEMORY, points_selector=models.PointIdsList(points=[point_id]))
    return True
