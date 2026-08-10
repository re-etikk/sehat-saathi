# Sehat Saathi 🎙

> **One-sentence claim:** A Hindi/English voice companion that helps elderly users manage daily medicines with correctable Qdrant memory, deterministic caregiver escalation, and Rime speech that recovers correctly from interruptions — reasoning from what the user actually *heard*, not what the system intended to say.

**StarForge 2026 · Track 01 — VoxForge** · Routes covered: *High-trust workflows* + *Multilingual voice* + *Memory & continuity*

---

## 1. Problem

Over 100M elderly Indians manage chronic conditions (diabetes, hypertension) with multi-medicine schedules. Many struggle with small text, apps, and typing — but everyone can **talk**. Missed doses and accidental double doses are a real, consequential problem. A screen-based reminder app fails exactly the users who need it most.

**Why voice is essential (not decoration):** the target user often cannot comfortably read a screen or type. Speaking in their own language — including natural Hindi-English code-switching — is the *only* interface that works. This is not a chatbot with a microphone; the same product does **not** work equally well as text.

## 2. Solution

A voice-first companion the user simply talks to:

- **"Meri dawai kab leni hai?"** → agent recalls *their* schedule from Qdrant and speaks it.
- **"Maine dawai le li."** → adherence logged as a memory.
- **"Nahi, Metformin raat ko nahi, subah leni hai."** → agent confirms once, then performs a **memory correction**: old memory is deactivated (audit trail kept), corrected one becomes active. Wrong memory never silently carries forward.
- **"Seene mein dard ho raha hai."** → deterministic **red-flag gate** (no LLM in the loop) → caregiver webhook fired + auditable escalation log + spoken guidance.
- **Interrupt anytime** → barge-in stops Rime audio and the agent reasons from the portion of the reply the user actually heard (`heard_context`).

### v2 app features
- **Accounts & login** (phone + password, salted PBKDF2, session tokens) — Qdrant memory isolation is now tied to real authenticated users, never a client-supplied ID.
- **Dashboard ("Aaj")** — next-dose countdown, today's medicine checklist with one-tap "Le li ✓", adherence streak, 7-day chart.
- **Voice-set alarms** — "subah aath baje Metformin yaad dilana" → agent proposes `set_reminder`, server validates HH:MM, alarm saved. Manageable in the Alarm tab too.
- **Spoken reminders** — when due, the app chimes, **speaks via Rime** ("Ramesh ji, Metformin lene ka samay ho gaya hai"), and shows a full-screen card with "Le li ✓ / Baad mein". Fires once per day per alarm.
- **SQLite + Qdrant split**: SQLite = structured app data (accounts, alarms, tick-marks); Qdrant = semantic memory the agent retrieves by meaning.

## 3. Architecture

```
 User speaks (hi-IN / en-IN)
        │  browser STT (Web Speech API)
        ▼
 ┌─────────────────────────  FastAPI server (all keys live here)  ─────────────────────────┐
 │ 1. RED-FLAG GATE  (deterministic regex — chest pain, overdose, fall → escalate)          │
 │        │ safe                                                                            │
 │ 2. QDRANT recall   ss_memory   filter: user_id + active=true  (strict isolation)         │
 │    QDRANT search   ss_knowledge (verified medicine facts, hi+en)                         │
 │        ▼                                                                                 │
 │ 3. LLM (Claude/GPT) → JSON contract: short spoken turn + proposed memory writes          │
 │        ▼                                                                                 │
 │ 4. SERVER-VALIDATED memory writes / corrections → Qdrant  (LLM can never delete)         │
 │        ▼                                                                                 │
 │ 5. RIME TTS  (voice routed by language: hi → RIME_SPEAKER_HI, en → RIME_SPEAKER_EN)      │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
        ▼
 Audio plays → user may BARGE-IN → frontend computes heard_context → next turn
                                     (state updates from what was HEARD, not intended)
```

A Mermaid version is in [`docs/architecture.md`](docs/architecture.md).

## 4. How to run

```bash
# 0. Prerequisites: Python 3.10+, a Qdrant instance (free: docker run -p 6333:6333 qdrant/qdrant)
git clone <this-repo> && cd sehat-saathi
pip install -r requirements.txt

# 1. Configure (keys stay server-side, never in the frontend)
cp .env.example .env       # fill RIME_API_KEY, QDRANT_URL, HF_TOKEN (free Hugging Face token)

# 2. Seed knowledge + a synthetic demo user
cd backend && python seed_knowledge.py

# 3. Run
uvicorn main:app --reload --port 8000
# open http://localhost:8000  (use Chrome — Web Speech API)

# No keys yet? Full UI flow works in mock mode:
MOCK_MODE=1 uvicorn main:app --reload --port 8000
```

**Reproduce the central proof (tests):**
```bash
cd backend && MOCK_MODE=1 python -m pytest tests/ -v
```

## 5. Proof

- ✅ **Tests that catch a wrong implementation** (`backend/tests/test_agent.py`): red-flag gate fires deterministically; user-memory isolation (user A can never see user B); correction keeps an audit trail; deletion respects ownership.
- ✅ **Visible Qdrant moment**: the side panel shows exactly which memories/knowledge were retrieved each turn, with scores.
- ✅ **User-perceived latency HUD**: STT → Qdrant → LLM → Rime TTS → network → playback, measured from *end of user speech to first audio* — not just model generation time.
- 🎬 **Showcase clip (add before submission)**: 25-second clip of the correction flow — user interrupts mid-sentence, corrects the schedule, memory panel shows old memory struck through + new one active.

## 6. Technology anchor

| Component | Exact role |
|---|---|
| **Rime** (`mistv2`/Coda — validate exact model+voice on your account before demo) | All spoken output. Language-aware voice routing (hi/en). Short punctuated turns because Coda takes delivery cues from wording/punctuation (no SSML). |
| **Qdrant** | Two collections: `ss_knowledge` (verified facts, hybrid-ready) and `ss_memory` (schedule/preference/adherence/unresolved) with payload filters `user_id, mem_type, lang, active` → strict per-user isolation, correctable + deletable memory. Qdrant *changes the outcome*: without it the agent literally does not know the user's schedule. |
| LLM | **Hugging Face Inference Providers** (default: `Qwen/Qwen2.5-7B-Instruct` via the OpenAI-compatible router, `HF_TOKEN`) — also supports Anthropic/OpenAI; JSON contract; proposes memory writes that the **server validates**. |
| STT | Browser Web Speech API (hi-IN/en-IN). Swap-in point documented for Whisper/Deepgram. |
| Embeddings | **Hugging Face model** `paraphrase-multilingual-MiniLM-L12-v2` running locally via fastembed (multilingual — Hindi + English in one vector space). |
| Escalation | Deterministic regex gate → caregiver webhook (`CAREGIVER_WEBHOOK_URL`) + `escalations.log` audit file. |

## 7. Limitations (what this does NOT prove)

- Not a medical device; it never advises doses or medicines — it only recalls the user's own stored schedule and verified general facts, and defers to doctors.
- Browser STT quality varies for heavy code-switching; production would use a dedicated multilingual STT.
- `heard_context` is estimated proportionally from audio playback time — good enough to be honest, not word-exact (word-level timestamps are the upgrade path).
- All demo data is synthetic; no real health information anywhere in code, logs, or demos.
- Red-flag list is a starter set, not a clinically validated triage system.

## 8. Team contributions

| Member | Contribution |
|---|---|
| **Ritik Kumar** (Team Leader) | Backend architecture — FastAPI server, login/auth system (PBKDF2 + sessions), Qdrant memory design (isolation, correction audit-trail), Hugging Face LLM integration, deployment & repo |
| **Tushar Raj Gupta** | Frontend UI/UX — dashboard ("Aaj"), alarm/reminder interface, barge-in implementation, latency HUD, elderly-friendly design system |
| **Shashi Bhushan** | Voice pipeline — Rime TTS integration & voice routing (hi/en), agent prompting & JSON contract, red-flag safety gate, pytest test suite |
| **Saffihuzzama** | Evaluation & delivery — latency/retrieval eval harness, knowledge seeding, demo script & video, PPT, documentation, end-to-end QA |

AI-assisted coding was used (Claude); the team can explain every file, and `tests/` catches wrong implementations.

## 9. Demo

- Full demo video: https://drive.google.com/file/d/1urrLY3E8DI9PZ3L4JUbyZGm2D5eUOnbc/view
- PPT link: https://docs.google.com/presentation/d/1Knaws9ix8BggXj-_sAhnBu2k8tmaZ6w3/edit?slide=id.p1#slide=id.p1


---
*Build the present. Explore the frontier. Leave a signal worth following.*
