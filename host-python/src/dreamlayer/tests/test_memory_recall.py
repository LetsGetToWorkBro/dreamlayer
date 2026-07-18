from dreamlayer.simulator import scenarios

def test_object_recall_returns_keys():
    _, card = scenarios.object_recall()
    assert card["type"] == "ObjectRecallCard"
    assert card["primary"]["name"] == "Keys"
    assert any(l == "Kitchen table" or (isinstance(l, dict) and l.get("name") == "Kitchen table") for l in card["lines"])

def test_object_wallet_returns_bedroom():
    _, card = scenarios.object_wallet()
    assert card["type"] == "ObjectRecallCard"
    assert card["primary"]["name"] == "Wallet"
    assert any(l == "Bedroom dresser" or (isinstance(l, dict) and l.get("name") == "Bedroom dresser") for l in card["lines"])

def test_object_glasses_returns_livingroom():
    _, card = scenarios.object_glasses()
    assert card["type"] == "ObjectRecallCard"
    assert card["primary"]["name"] == "Glasses"
    assert any(l == "Living room couch" or (isinstance(l, dict) and l.get("name") == "Living room couch") for l in card["lines"])

def test_commitment_recall_returns_jordan_invoice():
    _, card = scenarios.commitment_recall()
    assert card["type"] == "CommitmentRecallCard"
    assert card["primary"] == "Send the invoice"
    assert card["eyebrow"] == "You promised Jordan"

def test_commitment_multi_returns_marcus():
    _, card = scenarios.commitment_multi()
    assert card["type"] == "CommitmentRecallCard"
    assert card["eyebrow"] == "You promised Marcus"
    assert card["primary"] == "Send the contract"

def test_commitment_multi_person_sofia():
    _, card = scenarios.commitment_multi_person()
    assert card["type"] == "CommitmentRecallCard"
    assert card["eyebrow"] == "You promised Sofia"
    assert card["primary"] == "Book the van"

def test_low_conf_scene_returns_low_confidence_card(monkeypatch):
    # Pin default_embedder()'s ladder to the offline hashing/lexical tier
    # explicitly. With sentence-transformers installed (issue #449), the
    # ladder in dreamlayer.memory.embeddings.default_embedder() (read via
    # Orchestrator.__init__) picks the real MiniLM model instead, which finds
    # a genuinely better match for "where is my bag" and returns
    # ObjectRecallCard -- an environment effect, not a regression in the
    # LowConfidenceCard contract this scenario exercises. Mirrors
    # test_embedder_static.py::TestLadderWiring.test_hashing_when_neither_present,
    # the precedent for forcing the ladder down to HashingEmbeddingProvider.
    from dreamlayer.memory.embedder_local import LocalEmbeddingProvider
    from dreamlayer.memory.embedder_static import StaticEmbeddingProvider
    monkeypatch.setattr(LocalEmbeddingProvider, "available", False)
    monkeypatch.setattr(StaticEmbeddingProvider, "available", False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _, card = scenarios.low_confidence_recall()
    assert card["type"] in ("LowConfidenceCard",)

def test_empty_db_returns_low_confidence():
    _, card = scenarios.no_memory_recall()
    assert card["type"] == "LowConfidenceCard"

def test_unknown_query_returns_low_confidence():
    _, card = scenarios.unknown_query()
    assert card["type"] == "LowConfidenceCard"
