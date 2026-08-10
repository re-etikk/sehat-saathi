"""Quick diagnostic: is the Hugging Face LLM reachable and replying properly?

Run from the backend folder:   python test_llm.py
It prints the HTTP status and the model's raw reply, so you can see exactly
what's wrong (401 = bad token, 402 = credits over, 404 = model not available,
plain-text reply = model ignoring JSON instruction).
"""
import json

import httpx

import config

def main():
    if not config.HF_TOKEN:
        print("❌ HF_TOKEN is empty in .env — add it and restart.")
        return
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = {
        "model": config.LLM_MODEL,
        "max_tokens": 120,
        "messages": [
            {"role": "system", "content": "Reply with ONLY this JSON, nothing else: {\"say\": \"Namaste, main theek hoon\", \"lang\": \"hi\"}"},
            {"role": "user", "content": "hello"},
        ],
    }
    print(f"→ POST {url}\n→ model: {config.LLM_MODEL}\n")
    try:
        r = httpx.post(url, json=body, timeout=60,
                       headers={"Authorization": f"Bearer {config.HF_TOKEN}"})
    except Exception as e:
        print(f"❌ Network error: {e}")
        return
    print(f"HTTP status: {r.status_code}")
    if r.status_code == 401:
        print("❌ Token galat/expired hai. Naya fine-grained token banao with 'Make calls to Inference Providers' permission.")
    elif r.status_code == 402:
        print("❌ Free credits khatam. Doosre member ka token use karo, ya chhota model try karo.")
    elif r.status_code == 404:
        print("❌ Ye model router pe available nahi. Try: LLM_MODEL me ':fastest' suffix lagao,")
        print("   ya koi aur model, e.g. meta-llama/Llama-3.1-8B-Instruct ya Qwen/Qwen2.5-7B-Instruct:fastest")
    try:
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print("\nModel ka raw reply:")
        print(repr(content[:500]))
        if "{" in content and "say" in content:
            print("\n✅ SAB THEEK — model JSON de raha hai. App ab kaam karega.")
        else:
            print("\n⚠ Model reply toh de raha hai par JSON nahi — app ab bhi chalega (fallback laga diya hai),")
            print("  par better model try karo (Llama-3.1-8B-Instruct ya bada Qwen).")
    except Exception:
        print("\nRaw response body:")
        print(r.text[:500])

if __name__ == "__main__":
    main()
