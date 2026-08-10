"""Latency + retrieval eval (v2: with auth). Server chalu hona chahiye.
Run:  python eval_latency.py
"""
import json, statistics, urllib.request

BASE = "http://localhost:8000"
TURNS = ["meri dawai kab leni hai", "mujhe subah 8 baje dawai yaad dilana",
         "maine dawai le li", "Metformin khaali pet le sakte hain kya"]

def post(path, body, token=""):
    req = urllib.request.Request(BASE+path, data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
    return json.loads(urllib.request.urlopen(req).read())

if __name__ == "__main__":
    try:
        auth = post("/api/register", {"name":"EvalBot","phone":"0000001111","password":"eval1234"})
    except Exception:
        auth = post("/api/login", {"phone":"0000001111","password":"eval1234"})
    tok = auth["token"]
    totals, hits = [], 0
    for t in TURNS:
        r = post("/api/converse", {"transcript":t,"heard_context":""}, tok)
        tm = r["timings_ms"]; totals.append(tm.get("server_total_ms",0))
        hit = bool(r["retrieved"].get("memories") or r["retrieved"].get("knowledge")); hits += hit
        print(f"{t[:40]:42} qdrant={tm.get('qdrant_ms',0):>4}ms llm={tm.get('llm_ms',0):>5}ms "
              f"tts={tm.get('tts_ms',0):>5}ms total={tm.get('server_total_ms',0):>5}ms hit={hit}")
    print(f"\nserver p50={statistics.median(totals)}ms  max={max(totals)}ms  retrieval hit-rate={hits}/{len(TURNS)}")
