"""test_plugin_social.py — the store's social layer (reference implementation).

Pins ratings (one vote/user, updatable, average), downloads, comments, folding
stats into the index, persistence, and the pure request router the Cloudflare
Worker mirrors.
"""
from __future__ import annotations

from dreamlayer.plugins.social import SocialStore, route


# -- ratings ------------------------------------------------------------------

def test_rating_is_one_vote_per_user_and_averages():
    s = SocialStore()
    s.rate("gadget", 5, "alice")
    s.rate("gadget", 3, "bob")
    st = s.stats("gadget")
    assert st["ratings_count"] == 2 and st["rating"] == 4.0


def test_a_user_can_update_their_vote():
    s = SocialStore()
    s.rate("gadget", 1, "alice")
    s.rate("gadget", 5, "alice")               # same user again → replaces
    st = s.stats("gadget")
    assert st["ratings_count"] == 1 and st["rating"] == 5.0


def test_stars_are_clamped_and_junk_ignored():
    s = SocialStore()
    s.rate("g", 9, "u")                        # clamps to 5
    assert s.stats("g")["rating"] == 5.0
    s.rate("g", "nope", "v")                   # junk → no vote
    assert s.stats("g")["ratings_count"] == 1


# -- downloads + comments -----------------------------------------------------

def test_downloads_count_up():
    s = SocialStore()
    assert s.record_download("g") == 1 and s.record_download("g") == 2
    assert s.stats("g")["downloads"] == 2


def test_comments_append_newest_first_and_reject_empty():
    s = SocialStore()
    assert s.add_comment("g", "  ", "u") is None       # empty rejected
    s.add_comment("g", "first", "alice", ts=1.0)
    s.add_comment("g", "second", "bob", ts=2.0)
    cs = s.comments("g")
    assert [c["text"] for c in cs] == ["second", "first"]
    assert s.stats("g")["comments_count"] == 2


# -- folding into the index ---------------------------------------------------

def test_apply_to_index_is_non_mutating():
    s = SocialStore()
    s.rate("g", 4, "u"); s.record_download("g")
    entries = [{"name": "g", "downloads": 0, "rating": 0}]
    out = s.apply_to_index(entries)
    assert out[0]["downloads"] == 1 and out[0]["rating"] == 4.0
    assert entries[0]["downloads"] == 0                # original untouched


# -- persistence --------------------------------------------------------------

def test_persists_across_sessions(tmp_path):
    p = str(tmp_path / "social.json")
    s = SocialStore(p)
    s.rate("g", 5, "u"); s.record_download("g"); s.add_comment("g", "hi", "u", ts=1.0)
    reborn = SocialStore(p)
    st = reborn.stats("g")
    assert st["rating"] == 5.0 and st["downloads"] == 1 and st["comments_count"] == 1


# -- the router (the Worker mirrors this) -------------------------------------

def test_router_get_list_folds_stats():
    s = SocialStore(); s.rate("g", 4, "u")
    code, obj = route(s, "GET", "/api/plugins", index_entries=[{"name": "g"}])
    assert code == 200 and obj["plugins"][0]["rating"] == 4.0


def test_router_rate_download_comment_and_get_one():
    s = SocialStore()
    assert route(s, "POST", "/api/plugins/g/rate", {"stars": 5, "user": "u"})[1]["rating"] == 5.0
    assert route(s, "POST", "/api/plugins/g/download")[1]["downloads"] == 1
    code, c = route(s, "POST", "/api/plugins/g/comment", {"text": "nice", "user": "u"}, ts=3.0)
    assert code == 200 and c["text"] == "nice"
    code, one = route(s, "GET", "/api/plugins/g")
    assert one["rating"] == 5.0 and one["downloads"] == 1 and len(one["comments"]) == 1


def test_router_list_without_a_catalogue_uses_known_names():
    s = SocialStore()
    s.rate("gadget", 5, "u"); s.record_download("widget")
    code, obj = route(s, "GET", "/api/plugins")     # no index_entries (private registry)
    names = {p["name"] for p in obj["plugins"]}
    assert code == 200 and names == {"gadget", "widget"}


def test_router_rejects_bad_routes():
    s = SocialStore()
    assert route(s, "GET", "/nope")[0] == 404
    assert route(s, "POST", "/api/plugins")[0] == 405
    assert route(s, "POST", "/api/plugins/g/comment", {"text": ""})[0] == 400
