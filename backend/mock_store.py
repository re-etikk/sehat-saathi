"""Dev-only fallback used when MOCK_MODE=1 (no Qdrant running).
Same function signatures as memory.py, naive substring/keyword scoring.
The judged demo must use the real Qdrant path (memory.py).
"""
import time
import uuid

_KNOWLEDGE: list[dict] = []
_MEMORY: list[dict] = []


def ensure_collections():
    pass


def add_knowledge(text, lang, topic):
    _KNOWLEDGE.append({"text": text, "lang": lang, "topic": topic})
    return str(uuid.uuid4())


def _score(query, text):
    q = set(query.lower().split())
    t = set(text.lower().split())
    return len(q & t) / (len(q) or 1)


def search_knowledge(query, limit=3):
    scored = [{"text": k["text"], "topic": k["topic"], "score": _score(query, k["text"])}
              for k in _KNOWLEDGE]
    scored.sort(key=lambda x: -x["score"])
    return [s for s in scored[:limit] if s["score"] > 0]


def remember(user_id, text, mem_type, lang="hi"):
    pid = str(uuid.uuid4())
    _MEMORY.append({"id": pid, "user_id": user_id, "text": text, "mem_type": mem_type,
                    "lang": lang, "active": "true", "created_at": time.time()})
    return pid


def recall(user_id, query, limit=4, mem_type=None):
    rows = [m for m in _MEMORY if m["user_id"] == user_id and m["active"] == "true"
            and (mem_type is None or m["mem_type"] == mem_type)]
    scored = [{"id": m["id"], "text": m["text"], "mem_type": m["mem_type"],
               "score": _score(query, m["text"])} for m in rows]
    scored.sort(key=lambda x: -x["score"])
    return scored[:limit]


def correct_memory(user_id, old_query, new_text, mem_type, lang):
    old = recall(user_id, old_query, limit=1, mem_type=mem_type)
    new_id = remember(user_id, new_text, mem_type, lang)
    superseded = None
    if old:
        superseded = old[0]["id"]
        for m in _MEMORY:
            if m["id"] == superseded:
                m["active"] = "false"
                m["superseded_by"] = new_id
    return {"new_id": new_id, "superseded": superseded}


def list_memories(user_id):
    rows = [dict(m) for m in _MEMORY if m["user_id"] == user_id]
    return sorted(rows, key=lambda x: -x["created_at"])


def delete_memory(user_id, point_id):
    before = len(_MEMORY)
    _MEMORY[:] = [m for m in _MEMORY if not (m["id"] == point_id and m["user_id"] == user_id)]
    return len(_MEMORY) < before
