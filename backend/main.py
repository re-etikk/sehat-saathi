"""Sehat Saathi — FastAPI server (v2: accounts, alarms, dashboard).

Auth: Bearer token (from /api/register or /api/login) required on all /api/*
except register/login/health. Every user gets their own isolated Qdrant memory
(user_id from the session, never from the client body).

New in v2
  /api/register /api/login /api/logout /api/me
  /api/reminders  (CRUD)  + /api/reminders/due  (frontend polls; fires alarms)
  /api/dashboard  (today's meds, next dose, streak, weekly adherence)
  /api/adherence/mark  (tick a medicine as taken)
"""
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db as appdb
import rime_client
from agent import handle_turn

if config.MOCK_MODE:
    import mock_store as store
else:
    import memory as store

app = FastAPI(title="Sehat Saathi", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------- auth plumbing ----------------

def current_user(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    user = appdb.user_from_token(token)
    if not user:
        raise HTTPException(401, "login required")
    return user


class RegisterIn(BaseModel):
    name: str
    phone: str
    password: str
    lang: str = "hi"
    caregiver_phone: str = ""


class LoginIn(BaseModel):
    phone: str
    password: str


class ConverseIn(BaseModel):
    transcript: str
    heard_context: str = ""


class TTSIn(BaseModel):
    text: str
    lang: str = "hi"


class ReminderIn(BaseModel):
    label: str
    time_hhmm: str
    days: str = "daily"


class MarkIn(BaseModel):
    label: str
    status: str = "taken"


@app.on_event("startup")
def startup():
    appdb.init_db()
    store.ensure_collections()


@app.get("/api/health")
def health():
    return {"mode": "mock" if config.MOCK_MODE else "live",
            "rime": bool(config.RIME_API_KEY), "qdrant": not config.MOCK_MODE,
            "llm": config.LLM_PROVIDER if (config.HF_TOKEN or config.ANTHROPIC_API_KEY or config.OPENAI_API_KEY) else "mock"}


# ---------------- auth endpoints ----------------

@app.post("/api/register")
def register(body: RegisterIn):
    if len(body.password) < 4:
        raise HTTPException(400, "Password kam se kam 4 characters ka rakhein")
    res = appdb.register(body.name, body.phone, body.password, body.lang, body.caregiver_phone)
    if not res:
        raise HTTPException(409, "Ye phone number pehle se registered hai — login karein")
    return res


@app.post("/api/login")
def login(body: LoginIn):
    res = appdb.login(body.phone, body.password)
    if not res:
        raise HTTPException(401, "Phone ya password galat hai")
    return res


@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    appdb.logout(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"user": user}


# ---------------- assistant ----------------

@app.post("/api/converse")
def converse(body: ConverseIn, user: dict = Depends(current_user)):
    t0 = time.perf_counter()
    if not body.transcript.strip():
        raise HTTPException(400, "empty transcript")
    result = handle_turn(user["id"], body.transcript.strip(), body.heard_context.strip())
    tts = {"audio_b64": None, "content_type": None, "latency_ms": 0, "speaker": None, "model": None}
    try:
        tts = rime_client.synthesize(result.say, result.lang)
    except rime_client.RimeError as e:
        result.memory_events.append({"event": "tts_error", "text": str(e)})
    timings = dict(result.timings_ms)
    timings["tts_ms"] = tts["latency_ms"]
    timings["server_total_ms"] = round((time.perf_counter() - t0) * 1000)
    return {"say": result.say, "lang": result.lang, "escalated": result.escalated,
            "audio_b64": tts["audio_b64"], "content_type": tts.get("content_type"),
            "voice": {"speaker": tts["speaker"], "model": tts["model"]},
            "memory_events": result.memory_events, "retrieved": result.retrieved,
            "timings_ms": timings}


@app.post("/api/tts")
def tts(body: TTSIn, user: dict = Depends(current_user)):
    try:
        return rime_client.synthesize(body.text, body.lang)
    except rime_client.RimeError as e:
        raise HTTPException(502, str(e))


# ---------------- memory ----------------

@app.get("/api/memories")
def memories(user: dict = Depends(current_user)):
    return {"memories": store.list_memories(user["id"])}


@app.delete("/api/memories/{point_id}")
def delete_memory(point_id: str, user: dict = Depends(current_user)):
    if not store.delete_memory(user["id"], point_id):
        raise HTTPException(404, "memory not found for this user")
    return {"deleted": point_id}


# ---------------- reminders / alarms ----------------

@app.get("/api/reminders")
def reminders(user: dict = Depends(current_user)):
    return {"reminders": appdb.list_reminders(user["id"])}


@app.post("/api/reminders")
def add_reminder(body: ReminderIn, user: dict = Depends(current_user)):
    import re
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", body.time_hhmm):
        raise HTTPException(400, "time must be HH:MM")
    return appdb.add_reminder(user["id"], body.label, body.time_hhmm, body.days)


@app.patch("/api/reminders/{rid}")
def toggle_reminder(rid: str, active: bool, user: dict = Depends(current_user)):
    if not appdb.toggle_reminder(user["id"], rid, active):
        raise HTTPException(404, "reminder not found")
    return {"ok": True}


@app.delete("/api/reminders/{rid}")
def delete_reminder(rid: str, user: dict = Depends(current_user)):
    if not appdb.delete_reminder(user["id"], rid):
        raise HTTPException(404, "reminder not found")
    return {"ok": True}


@app.get("/api/reminders/due")
def due(user: dict = Depends(current_user)):
    """Frontend polls this; when a reminder is due, it speaks via Rime + shows overlay."""
    items = appdb.due_reminders(user["id"])
    out = []
    for r in items:
        text = f"{user['name']} ji, {r['label']} lene ka samay ho gaya hai."
        audio = {"audio_b64": None, "content_type": None}
        try:
            audio = rime_client.synthesize(text, user.get("lang", "hi"))
        except Exception:
            pass
        out.append({**r, "speak_text": text, "audio_b64": audio["audio_b64"],
                    "content_type": audio.get("content_type")})
    return {"due": out}


# ---------------- adherence / dashboard ----------------

@app.post("/api/adherence/mark")
def mark(body: MarkIn, user: dict = Depends(current_user)):
    appdb.mark_adherence(user["id"], body.label, body.status)
    store.remember(user["id"], f"{user['name']} ne {body.label} li ({time.strftime('%d %b %H:%M')})",
                   "adherence", user.get("lang", "hi"))
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    return appdb.dashboard_stats(user["id"])


app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
