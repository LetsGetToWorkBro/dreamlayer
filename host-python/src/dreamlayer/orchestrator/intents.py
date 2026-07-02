import re
def classify(query):
    q = query.lower()
    if "promis" in q or ("tell" in q and "i" in q):
        m = re.search(r"promis[ed]*\s+(\w+)", q)
        return {"intent":"commitment_recall","person": m.group(1).title() if m else None}
    if any(w in q for w in ("where","left","find","keys","phone","wallet","glasses","bag")):
        obj = next((c for c in ("keys","phone","wallet","glasses","bag") if c in q), None)
        return {"intent":"object_recall","object":obj}
    return {"intent":"unknown"}
