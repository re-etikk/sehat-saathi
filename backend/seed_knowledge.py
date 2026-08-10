"""Seed the shared knowledge collection + one synthetic demo user.

ALL DATA IS SYNTHETIC (hackathon rule: no real personal/health information).
Run:  python seed_knowledge.py
"""
import config

if config.MOCK_MODE:
    import mock_store as store
else:
    import memory as store

KNOWLEDGE = [
    ("Metformin khaane ke saath ya khaane ke turant baad lena chahiye, isse pet kharab hone ki sambhavna kam hoti hai.", "hi", "metformin"),
    ("Metformin should be taken with food to reduce stomach upset.", "en", "metformin"),
    ("Agar dawai ki ek khuraak chhoot jaaye aur agli khuraak ka samay paas ho, toh double dose kabhi na lein; doctor se poochhein.", "hi", "missed-dose"),
    ("If a dose is missed and the next dose is near, never take a double dose; ask the doctor.", "en", "missed-dose"),
    ("Blood pressure ki dawai roz ek hi samay par lena sabse achha hota hai, jisse asar bana rehta hai.", "hi", "bp"),
    ("Amlodipine subah ke samay li ja sakti hai; halka sar dard shuru mein aam hai, bana rahe toh doctor ko batayein.", "hi", "amlodipine"),
    ("Paani achhi maatra mein peena dawai ke saath aam taur par sahi rehta hai, jab tak doctor ne mana na kiya ho.", "hi", "general"),
    ("Dawai kabhi bhi doctor se poochhe bina band nahi karni chahiye, chahe tabiyat theek lage.", "hi", "general"),
]

if __name__ == "__main__":
    store.ensure_collections()
    for text, lang, topic in KNOWLEDGE:
        store.add_knowledge(text, lang, topic)
    print(f"Seeded {len(KNOWLEDGE)} knowledge points. (Users ab register/login se bante hain; "
          f"unki memory baat-cheet se banegi.)")
