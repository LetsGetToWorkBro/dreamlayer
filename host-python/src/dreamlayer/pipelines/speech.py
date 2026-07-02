def extract_conversation(conv):
    return {"participants": conv.get("participants",[]), "summary": conv.get("summary",""), "turns": conv.get("turns",[])}
