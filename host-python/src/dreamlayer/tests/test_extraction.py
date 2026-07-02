from dreamlayer.pipelines.extraction import extract_commitments
import json, os

FX = os.path.join(os.path.dirname(__file__), "..", "simulator", "fixtures")

def _load(name): return json.load(open(os.path.join(FX, name)))

def test_extract_invoice_commitment():
    c = extract_commitments(_load("conversation_invoice.json"))
    assert len(c) == 1
    assert c[0]["task"] == "Send the invoice"
    assert c[0]["person"] == "Jordan"

def test_extract_deal_two_commitments():
    c = extract_commitments(_load("conversation_deal.json"))
    assert len(c) == 2
    tasks = [x["task"] for x in c]
    assert "Send the contract" in tasks
    assert "Include the pricing deck" in tasks

def test_extract_multicommit_sofia():
    c = extract_commitments(_load("conversation_multicommit.json"))
    assert len(c) == 2
    persons = {x["person"] for x in c}
    assert "Sofia" in persons

def test_no_commitments():
    conv = {"participants":["A","B"],"turns":[{"speaker":"A","text":"Hi there."},{"speaker":"B","text":"Hello."}]}
    assert extract_commitments(conv) == []
