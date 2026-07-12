"""Real-path coverage for the optional networkx relationship graph."""

import pytest


def test_relationship_graph_networkx_real_path():
    pytest.importorskip("networkx")
    from dreamlayer.social_lens.graph import RelationshipGraph

    graph = RelationshipGraph()
    assert graph.available

    graph.met_at("marcus", "overpass-show")
    graph.met_at("priya", "overpass-show")
    graph.relate("marcus", "priya", kind="colleagues")

    assert set(graph.people_at("overpass-show")) == {"marcus", "priya"}
    assert graph.connections("marcus") == ["priya"]
