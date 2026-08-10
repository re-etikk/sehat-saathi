# Architecture — Sehat Saathi

```mermaid
flowchart TD
    U["👤 Elderly user speaks<br/>hi-IN / en-IN"] -->|Web Speech API STT| FE["Frontend<br/>barge-in · heard_context · latency HUD"]
    FE -->|"POST /api/converse<br/>{transcript, heard_context}"| GATE{"Red-flag gate<br/>(deterministic regex)"}
    GATE -->|"chest pain / overdose / fall"| ESC["🚨 Caregiver webhook<br/>+ escalations.log"]
    ESC --> RIME
    GATE -->|safe| QM[("Qdrant · ss_memory<br/>filter: user_id + active")]
    GATE -->|safe| QK[("Qdrant · ss_knowledge<br/>verified facts hi+en")]
    QM --> LLM["LLM (JSON contract)<br/>short spoken turn +<br/>proposed memory writes"]
    QK --> LLM
    LLM --> VAL["Server validation<br/>allowed types only ·<br/>LLM can never delete"]
    VAL -->|write / correct| QM
    VAL --> RIME["🔊 Rime TTS<br/>voice routed by language"]
    RIME -->|audio_b64 + timings| FE
    FE -->|user interrupts| BARGE["Barge-in: stop audio,<br/>compute heard fraction"]
    BARGE -->|heard_context| FE
```

## The four kinds of context (as the brief recommends)
1. **Knowledge** the agent may need → `ss_knowledge`
2. **Memories about this user** → `ss_memory` (schedule/preference)
3. **Similar past cases** → `ss_memory` (adherence history)
4. **Current task state** → `heard_context` + unresolved memories

## Why memory is trustworthy here
- Strict `user_id` payload filter on every recall (leak-proof by construction, tested).
- Corrections deactivate rather than overwrite (`active=false, superseded_by=…`) → audit trail.
- The Memory panel makes every stored item visible and deletable by the user.
