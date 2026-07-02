import json
from ..hud import cards
from ..config import CONFIG
def build_object_answer(scored):
    if not scored: return cards.low_confidence()
    score, mem = scored[0]
    if score < CONFIG.recall_min_confidence: return cards.low_confidence()
    meta = json.loads(mem.get("meta") or "{}")
    return cards.object_recall({"object":meta.get("object",mem["summary"]),"place":meta.get("place",""),
                                 "detail":meta.get("detail",""),"last_seen":meta.get("last_seen",""),"confidence":round(score,2)})
def build_commitment_answer(commits):
    if not commits: return cards.low_confidence()
    c = commits[0]
    if c.get("confidence",0) < CONFIG.recall_min_confidence: return cards.low_confidence()
    return cards.commitment_recall(c)
def build_proactive(p):
    if not p or p.get("confidence",0) < CONFIG.proactive_min_confidence: return None
    return cards.proactive_memory(p)
