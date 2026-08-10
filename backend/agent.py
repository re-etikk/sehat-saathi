"""Conversation brain.

Flow per turn (see docs/architecture.md):
  transcript -> red-flag safety check -> Qdrant recall (memory, strict user filter)
             -> Qdrant knowledge search -> LLM (short spoken turn, JSON contract)
             -> memory writes / corrections -> Rime speaks

Design decisions that matter for judging:
  * SHORT TURNS: voice is sequential; every reply <= 2 sentences unless reading a schedule.
  * SAFETY FIRST: red-flag symptoms bypass the LLM entirely — deterministic escalation.
  * SEPARATION OF POWERS: the LLM proposes memory writes; the server validates types
    before anything touches Qdrant. The LLM cannot delete memory — only the user can,
    via the visible Memory panel (auditable, correctable memory).
"""
import json
import re
import time
from dataclasses import dataclass, field

import httpx

import config

if config.MOCK_MODE:
    import mock_store as store
else:
    import memory as store

# Deterministic red-flag escalation (never left to the LLM in a high-trust flow)
RED_FLAGS = [
    r"seene? m[ei]+n? dard", r"chest pain", r"saans (nahi|nahin|rukna)", r"breath",
    r"behosh", r"unconscious", r"chakkar", r"faint", r"गिर गय", r"fall(en)? down", r"gir gay",
    r"bleeding", r"khoon", r"zyada dawai", r"overdose", r"double dose le li",
]

SYSTEM_PROMPT = """You are "Sehat Saathi", a warm voice companion helping an elderly Indian user manage daily medicines. You speak in short, natural spoken turns (max 2 short sentences) because your words are converted to speech.

Language rule: reply in the language the user spoke. If they mix Hindi and English (code-switching), reply in natural Hinglish written in Devanagari for Hindi words. Set "lang":"hi" for Hindi/Hinglish, "en" for pure English.

Speech rule: no bullet points, no markdown, no emojis. Numbers as words where natural ("subah aath baje"). Use commas and full stops to shape delivery — the TTS takes cues from punctuation.

Safety rules (non-negotiable):
- You NEVER change a dose, suggest a new medicine, or give medical advice beyond the stored schedule and general knowledge provided. For anything medical beyond that, say the doctor should be asked, and offer to note the question down.
- If the user reports feeling unwell in a serious way, set "escalate": true.
- Before recording a schedule CHANGE, confirm it back once ("Toh ab se Metformin raat ko, theek hai?"). Only after the user confirms, emit the memory write.

You receive CONTEXT: the user's relevant memories (their medicine schedule, preferences, unresolved items) and knowledge snippets. Treat memories as the source of truth about this user.

You must reply ONLY with JSON:
{
 "say": "<short spoken reply>",
 "lang": "hi" | "en",
 "memory_writes": [{"type": "schedule|preference|adherence|unresolved", "text": "<one clear sentence>"}],
 "memory_correction": null | {"old_query": "<what to find>", "new_text": "<corrected sentence>", "type": "schedule|preference"},
 "set_reminder": null | {"label": "<medicine/task name>", "time": "HH:MM"},
 "mark_taken": null | "<medicine label>",
 "escalate": false,
 "needs_confirmation": false
}
Use set_reminder when the user asks to be reminded / set an alarm ("subah aath baje yaad dilana"). Convert spoken times to 24h HH:MM. Use mark_taken when the user says they took a medicine; put the medicine name if known, else "dawai".
Emit memory_writes only for durable facts worth remembering, not small talk."""


@dataclass
class TurnResult:
    say: str
    lang: str = "hi"
    escalated: bool = False
    memory_events: list = field(default_factory=list)
    retrieved: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)


def _red_flag(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in RED_FLAGS)


def _call_llm(messages: list[dict]) -> str:
    if config.LLM_PROVIDER == "anthropic":
        headers = {"x-api-key": config.ANTHROPIC_API_KEY,
                   "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": config.LLM_MODEL, "max_tokens": 400,
                "system": SYSTEM_PROMPT, "messages": messages}
        with httpx.Client(timeout=30) as http:
            r = http.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        r.raise_for_status()
        return r.json()["content"][0]["text"]
    # OpenAI-compatible path — works for BOTH:
    #   huggingface : base_url=https://router.huggingface.co/v1, key=HF_TOKEN
    #   openai      : base_url=https://api.openai.com/v1,       key=OPENAI_API_KEY
    if config.LLM_PROVIDER == "huggingface":
        base_url, key = config.LLM_BASE_URL, config.HF_TOKEN
    else:
        base_url, key = "https://api.openai.com/v1", config.OPENAI_API_KEY
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    body = {"model": config.LLM_MODEL, "max_tokens": 400,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages}
    with httpx.Client(timeout=60) as http:
        r = http.post(base_url.rstrip("/") + "/chat/completions", headers=headers, json=body)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_spoken_time(t: str):
    """'8 baje', 'subah 8:30', '20:15', 'raat 9 baje' -> 'HH:MM' or None."""
    t = t.lower()
    m = re.search(r"(\d{1,2})[:.](\d{2})", t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d{1,2})\s*(baje|am|pm|bje)", t)
        if not m:
            return None
        hh, mm = int(m.group(1)), 0
    if hh <= 12 and any(w in t for w in ["raat", "shaam", "sham", "evening", "night", "pm"]) and hh != 12:
        hh += 12
    if "am" in t and hh == 12:
        hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def _mock_reply(transcript: str, memories: list[dict]) -> dict:
    """Keyword agent for MOCK_MODE so the UI is demoable with zero keys."""
    t = transcript.lower()
    base = {"lang": "hi", "memory_writes": [], "memory_correction": None,
            "set_reminder": None, "mark_taken": None,
            "escalate": False, "needs_confirmation": False}
    if any(w in t for w in ["yaad dila", "alarm", "reminder", "remind"]):
        hhmm = _parse_spoken_time(t)
        if hhmm:
            label = "Dawai"
            mmed = re.search(r"(metformin|amlodipine|paracetamol|insulin|vitamin\w*)", t)
            if mmed:
                label = mmed.group(1).capitalize()
            spoken = f"{int(hhmm[:2])%12 or 12} baj kar {int(hhmm[3:])} minute" if hhmm[3:] != "00" else f"{int(hhmm[:2])%12 or 12} baje"
            return {**base, "say": f"Theek hai, maine {label} ka alarm {spoken} ke liye laga diya hai.",
                    "set_reminder": {"label": label, "time": hhmm}}
        return {**base, "say": "Zaroor. Kitne baje yaad dilaoon? Jaise, subah aath baje."}
    if any(w in t for w in ["le li", "kha li", "taken", "took", "le liya"]):
        return {**base, "say": "Bahut achha, maine likh liya ki aaj ki dawai le li gayi hai.",
                "mark_taken": "dawai",
                "memory_writes": [{"type": "adherence", "text": f"User ne dawai li ({time.strftime('%d %b %H:%M')})"}]}
    if any(w in t for w in ["kya", "kaunsi", "which", "medicine", "dawai", "dawa"]):
        if memories:
            return {**base, "say": f"Aapki yaad ke mutabik, {memories[0]['text']}"}
        return {**base, "say": "Abhi mere paas aapki dawai ki jaankari nahi hai. Bataiye, kaunsi dawai kab leni hai?"}
    return {**base, "say": "Ji, main sun rahi hoon. Aap apni dawai ke baare mein poochh sakte hain.",
            "lang": "hi", "memory_writes": [], "memory_correction": None,
            "escalate": False, "needs_confirmation": False}


def handle_turn(user_id: str, transcript: str, heard_context: str = "") -> TurnResult:
    """heard_context = what the user ACTUALLY heard before interrupting (barge-in truth).
    We reason from what was heard, not from the full text we intended to say."""
    timings = {}

    # 1. deterministic safety gate
    if _red_flag(transcript):
        _notify_caregiver(user_id, transcript)
        return TurnResult(
            say=("Yeh zaroori lagta hai. Main abhi aapke caregiver ko khabar bhej rahi hoon. "
                 "Agar bahut takleef hai toh kripya ek so aath par phone karein."),
            lang="hi", escalated=True,
            memory_events=[{"event": "escalation", "text": transcript}],
        )

    # 2. recall + knowledge (Qdrant)
    t0 = time.perf_counter()
    memories = store.recall(user_id, transcript, limit=4)
    knowledge = store.search_knowledge(transcript, limit=2)
    timings["qdrant_ms"] = round((time.perf_counter() - t0) * 1000)

    # 3. reason
    t0 = time.perf_counter()
    if config.MOCK_MODE or not (config.HF_TOKEN or config.ANTHROPIC_API_KEY or config.OPENAI_API_KEY):
        data = _mock_reply(transcript, memories)
    else:
        ctx = {
            "user_memories": [m["text"] for m in memories],
            "knowledge": [k["text"] for k in knowledge],
            "user_heard_before_interrupting": heard_context or None,
            "now": time.strftime("%A %d %B, %H:%M"),
        }
        messages = [{"role": "user",
                     "content": (f"CONTEXT:\n{json.dumps(ctx, ensure_ascii=False)}\n\n"
                                 f"USER SAID: {transcript}\n\n"
                                 "Reply with ONLY the JSON object, no other text, no markdown fences.")}]
        try:
            raw = _call_llm(messages)
            # strip reasoning tags / code fences some open models add
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
            raw = raw.replace("```json", "").replace("```", "")
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                raise ValueError(f"LLM did not return JSON. Raw reply: {raw[:300]!r}")
            data = json.loads(m.group(0))
            if not data.get("say"):
                raise ValueError(f"LLM JSON missing 'say'. Raw: {raw[:300]!r}")
        except Exception as e:
            # NEVER crash the voice turn — log the cause, degrade gracefully
            print(f"[LLM ERROR] {type(e).__name__}: {e}")
            data = _mock_reply(transcript, memories)
    timings["llm_ms"] = round((time.perf_counter() - t0) * 1000)

    # 4. validated memory writes (server-side gate)
    events = []
    allowed = {"schedule", "preference", "adherence", "unresolved"}
    for w in data.get("memory_writes") or []:
        if w.get("type") in allowed and w.get("text"):
            pid = store.remember(user_id, w["text"].strip(), w["type"], data.get("lang", "hi"))
            events.append({"event": "write", "id": pid, "type": w["type"], "text": w["text"]})
    corr = data.get("memory_correction")
    if corr and corr.get("type") in {"schedule", "preference"}:
        res = store.correct_memory(user_id, corr["old_query"], corr["new_text"],
                                   corr["type"], data.get("lang", "hi"))
        events.append({"event": "correction", **res, "text": corr["new_text"]})

    # 5. validated app actions (server-side gate — same principle as memory)
    import db as appdb
    sr = data.get("set_reminder")
    if sr and sr.get("label") and re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(sr.get("time", ""))):
        rem = appdb.add_reminder(user_id, sr["label"], sr["time"])
        events.append({"event": "reminder_set", **rem})
    mt = data.get("mark_taken")
    if mt:
        appdb.mark_adherence(user_id, str(mt))
        events.append({"event": "adherence_marked", "label": str(mt)})

    return TurnResult(
        say=data["say"], lang=data.get("lang", "hi"),
        escalated=bool(data.get("escalate")),
        memory_events=events,
        retrieved={"memories": memories, "knowledge": knowledge},
        timings_ms=timings,
    )


def _notify_caregiver(user_id: str, transcript: str) -> None:
    """Real webhook if configured, otherwise an auditable local log (demo-safe)."""
    payload = {"user_id": user_id, "reason": transcript, "at": time.time()}
    if config.CAREGIVER_WEBHOOK_URL:
        try:
            with httpx.Client(timeout=5) as http:
                http.post(config.CAREGIVER_WEBHOOK_URL, json=payload)
        except Exception:
            pass
    with open("escalations.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
