"""Central configuration. Every credential stays on the server (.env), never in the frontend."""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Rime (Voice Models Partner) ---
RIME_API_KEY = os.getenv("RIME_API_KEY", "")
RIME_MODEL = os.getenv("RIME_MODEL", "mistv2")          # use "mist" / "mistv3" / coda per docs.rime.ai/docs/models
RIME_SPEAKER_HI = os.getenv("RIME_SPEAKER_HI", "rainforest")  # pick a Hindi-capable voice from docs.rime.ai/docs/voices
RIME_SPEAKER_EN = os.getenv("RIME_SPEAKER_EN", "cove")
RIME_TTS_URL = os.getenv("RIME_TTS_URL", "https://users.rime.ai/v1/rime-tts")

# --- Qdrant (Vector Search Partner) ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
COLLECTION_KNOWLEDGE = "ss_knowledge"   # medicine facts, policies
COLLECTION_MEMORY = "ss_memory"         # per-user memories: schedule, prefs, corrections, unresolved tasks

# --- LLM (any provider; Hugging Face router by default — OpenAI-compatible) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "huggingface")   # "huggingface" | "anthropic" | "openai"
HF_TOKEN = os.getenv("HF_TOKEN", "")            # fine-grained token with "Make calls to Inference Providers"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")  # cheap + good Hindi; stretch free credits. Upgrade to 72B if credits allow
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://router.huggingface.co/v1")

# --- Embeddings ---
# fastembed runs locally (no API needed) — great for hackathon reliability.
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

# --- App behaviour ---
# MOCK_MODE=1 lets you demo the full flow with browser TTS + in-memory store (no keys needed).
# The judged demo must run with MOCK_MODE=0 (real Rime + real Qdrant).
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"
CAREGIVER_WEBHOOK_URL = os.getenv("CAREGIVER_WEBHOOK_URL", "")  # optional: real webhook for escalation
