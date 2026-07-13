"""Dedicated coverage for the optional relationship graph adapter."""

import pytest


def test_relationship_graph_networkx_real_path():
    pytest.importorskip("networkx")
    from dreamlayer.social_lens.graph import RelationshipGraph

    graph = RelationshipGraph()
    assert graph.available

    graph.met_at("marcus", "overpass-show")
    graph.met_at("marcus", "overpass-show")
    graph.met_at("priya", "overpass-show")
    graph.relate("marcus", "priya")

    assert set(graph.people_at("overpass-show")) == {"marcus", "priya"}
    assert graph.connections("marcus") == ["priya"]
    assert graph.connections("unknown") == []
    assert graph._g is not None
    assert graph._g.edges[("p", "marcus"), ("p", "priya")]["kind"] == "knows"


def test_relationship_graph_without_networkx(monkeypatch):
    from dreamlayer.social_lens import graph as graph_module

    monkeypatch.setattr(graph_module, "_HAS_NX", False)
    monkeypatch.setattr(graph_module.RelationshipGraph, "available", False)
    graph = graph_module.RelationshipGraph()

    assert not graph.available
    graph.met_at("marcus", "overpass-show")
    graph.met_at("marcus", "overpass-show")
    graph.met_at("priya", "overpass-show")
    graph.relate("marcus", "priya")

    assert graph.people_at("overpass-show") == ["marcus", "priya"]
    assert graph.connections("marcus") == ["priya"]
    assert graph.connections("unknown") == []
