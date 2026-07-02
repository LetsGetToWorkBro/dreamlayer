def summarize(text: str, max_words: int = 8) -> str:
    return " ".join(text.replace("\n"," ").split()[:max_words])
