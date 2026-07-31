"""Voice recall — who is speaking, so a memory has an author.

`they_said` / `their_word` have matched on `meta["said_by"]` since they were
written, and nothing ever set it: `ear.py` said outright that *"nothing in this
product ever populates `speaker`"*, because knowing who spoke means voiceprinting
whoever is in earshot. So the memory-based Truth Lens worked only for utterances
the wearer typed in themselves. This is the consented producer.

It mirrors `face_live.py` almost line for line, deliberately — a voiceprint is the
same KIND of thing as a face template, so it gets the same switches, the same
versioned consent, the same erase button, and the same honesty about enrolling
people who never agreed.

THE TEST THAT MATTERS MOST IS `TestTheHashFallbackNeverIdentifies`.
`ECAPASpeaker.embed` returns a hash of the audio's string form when speechbrain is
absent — the same speaker yields a different vector every utterance and two
strangers can collide. Identifying with that would attach real names to the wrong
people's words and store them as fact. Being wrong here is defamatory, not merely
empty, so the whole layer declines without a model that actually loaded.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server import voice_live as VL
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.voice_live import CONSENT_VERSION, VoiceRecall


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


class _FakeModel:
    """Stands in for a loaded ECAPA model: a deterministic vector PER SPEAKER.

    Keyed on an explicit speaker tag rather than on the audio, because the real
    model's job is exactly that — the same voice saying different words must
    embed close together, which the hash fallback conspicuously does not do.
    """

    _model = object()                                # "a model actually loaded"

    def embed(self, audio, key=None):
        tag = audio if isinstance(audio, str) else str(audio)
        base = {"marcus": [1.0, 0.0, 0.0], "priya": [0.0, 1.0, 0.0],
                "tomas": [0.0, 0.0, 1.0]}
        # a near-neighbour of marcus, for the margin test
        if tag == "marcus-ish":
            return [0.96, 0.28, 0.0]
        return base.get(tag, [0.5, 0.5, 0.5])


def _wired(brain, *, auto=True, on=True):
    """A consented, model-backed VoiceRecall."""
    vr = VoiceRecall(brain)
    vr._embedder = _FakeModel()
    vr._embedder_built = True
    brain.config.voice_recognition = on
    brain.config.voice_auto_enrol = auto
    brain.config.voice_consent_version = CONSENT_VERSION
    return vr


class TestTheHashFallbackNeverIdentifies:

    def test_the_gate_itself_rejects_a_wheel_with_no_model(self, brain,
                                                           monkeypatch):
        """THE line this whole file turns on, exercised through `_get_embedder`.

        Every other test here injects `_embedder` directly and therefore skips
        the construction that does the checking — so deleting the check survived
        all of them. `ECAPASpeaker.available` is True whenever speechbrain
        imports; `_model` is None when the checkpoint failed to load, and in that
        state `embed()` silently returns a hash of the audio's string form. A
        wheel is not a model, and only a model may identify a person.
        """
        from dreamlayer.ai_brain.server import voice_live as V

        class _WheelNoModel:
            available = True
            _model = None                            # imported, never loaded

            def embed(self, audio, key=None):
                raise AssertionError("the hash fallback must never be reached")

        monkeypatch.setattr("dreamlayer.orchestrator.speaker_ecapa.ECAPASpeaker",
                            _WheelNoModel)
        vr = V.VoiceRecall(brain)
        brain.config.voice_recognition = True
        brain.config.voice_auto_enrol = True
        brain.config.voice_consent_version = CONSENT_VERSION
        assert vr.model_available is False
        assert vr.identify("marcus")["reason"] == "no-voice-model"
        assert vr.status()["stored"] == 0

    def test_the_gate_accepts_a_model_that_did_load(self, brain, monkeypatch):
        """The other direction, so the gate cannot just be "always refuse"."""
        from dreamlayer.ai_brain.server import voice_live as V

        class _Loaded(_FakeModel):
            available = True

        monkeypatch.setattr("dreamlayer.orchestrator.speaker_ecapa.ECAPASpeaker",
                            _Loaded)
        vr = V.VoiceRecall(brain)
        brain.config.voice_recognition = True
        brain.config.voice_auto_enrol = True
        brain.config.voice_consent_version = CONSENT_VERSION
        assert vr.model_available is True
        assert vr.identify("marcus")["known"] is True

    def test_no_loaded_model_means_no_identification(self, brain):
        """The wheel being absent is not the test — a model having LOADED is.
        `available` is True whenever speechbrain imports, while `embed` still
        falls back to a hash if the checkpoint failed to load."""
        vr = VoiceRecall(brain)
        vr._embedder = None
        vr._embedder_built = True
        brain.config.voice_recognition = True
        brain.config.voice_consent_version = CONSENT_VERSION
        assert vr.model_available is False
        assert vr.identify("marcus")["reason"] == "no-voice-model"

    def test_no_model_means_no_enrolment_either(self, brain):
        """Auto-enrol on a hash vector would fill the store with phantom
        speakers that never match again — and each one is a biometric record of
        a real person, taken and useless."""
        vr = VoiceRecall(brain)
        vr._embedder = None
        vr._embedder_built = True
        brain.config.voice_recognition = True
        brain.config.voice_auto_enrol = True
        brain.config.voice_consent_version = CONSENT_VERSION
        vr.identify("marcus")
        assert vr.status()["stored"] == 0

    def test_the_ear_gets_no_seam_without_a_model(self, brain):
        """The pipeline must not be handed an embedder it should not use."""
        from dreamlayer.ai_brain.server.ear import EarHost
        vr = VoiceRecall(brain)
        vr._embedder = None
        vr._embedder_built = True
        brain._voice_recall = vr
        brain.config.voice_recognition = True
        brain.config.voice_consent_version = CONSENT_VERSION
        assert EarHost(brain)._voice_seam() == (None, None, None)


class TestConsentGatesEverything:

    def test_off_by_default(self, brain):
        vr = VoiceRecall(brain)
        assert vr.consented is False
        assert vr.enabled is False
        assert vr.auto_enrol is False

    def test_without_consent_nothing_is_identified(self, brain):
        vr = _wired(brain)
        brain.config.voice_consent_version = ""
        out = vr.identify("marcus")
        assert out["reason"] == "no-consent"
        assert out["consent_required"] == CONSENT_VERSION

    def test_a_stale_consent_version_does_not_carry_over(self, brain):
        """Agreeing to different words is not this agreement."""
        vr = _wired(brain)
        brain.config.voice_consent_version = "2020-01-01.old.v1"
        assert vr.consented is False
        assert vr.identify("marcus")["reason"] == "no-consent"

    def test_accepting_the_wrong_version_is_refused(self, brain):
        vr = VoiceRecall(brain)
        assert vr.accept_consent("something-else")["ok"] is False
        assert vr.consented is False

    def test_auto_enrol_alone_is_not_enough(self, brain):
        """The switch is gated behind consent, not merely alongside it."""
        vr = VoiceRecall(brain)
        brain.config.voice_auto_enrol = True
        assert vr.auto_enrol is False

    def test_the_recognition_switch_alone_is_not_enough_either(self, brain):
        """`enabled` is asserted DIRECTLY, because `identify` checks consent
        before it checks `enabled` — so removing consent from `enabled` changed
        nothing there and survived. It matters elsewhere: the ear's seam and the
        capability flag both read `enabled` and neither re-checks consent."""
        vr = VoiceRecall(brain)
        brain.config.voice_recognition = True
        assert vr.enabled is False, "the switch bypassed consent"
        brain.config.voice_consent_version = CONSENT_VERSION
        assert vr.enabled is True

    def test_an_unconsented_switch_hands_the_ear_no_seam(self, brain):
        """The consequence of the line above, at the place that would matter."""
        from dreamlayer.ai_brain.server.ear import EarHost
        vr = _wired(brain)
        brain.config.voice_consent_version = ""
        brain._voice_recall = vr
        assert EarHost(brain)._voice_seam() == (None, None, None)

    def test_revoking_consent_ERASES_the_voiceprints(self, brain):
        """Withdrawing consent has to remove what was taken under it. Stopping
        collection while keeping the templates is not withdrawal."""
        vr = _wired(brain)
        vr.identify("marcus")
        assert vr.status()["stored"] == 1
        out = vr.revoke_consent()
        assert out["erased"] == 1
        assert vr.status()["stored"] == 0
        assert brain.config.voice_recognition is False
        assert brain.config.voice_auto_enrol is False


class TestTheVeil:

    def test_a_veiled_moment_computes_no_voiceprint(self, brain):
        vr = _wired(brain)
        brain.incognito_now = lambda: True
        assert vr.identify("marcus")["reason"] == "veiled"
        assert vr.status()["stored"] == 0

    def test_an_unreadable_posture_fails_closed(self, brain):
        vr = _wired(brain)

        def _boom():
            raise RuntimeError("posture unreadable")
        brain.incognito_now = _boom
        assert vr.identify("marcus")["reason"] == "veiled"

    def test_the_resolver_is_veiled_too(self, brain):
        """The capture-loop path has its own entry point and needs its own
        gate — it does not go through `identify`."""
        vr = _wired(brain)
        vr.identify("marcus")
        vr.name_identity(vr.people()[0]["contact_id"], "Marcus")
        brain.incognito_now = lambda: True
        assert vr.resolver()([1.0, 0.0, 0.0]) == ""


class TestIdentifying:

    def test_an_unknown_voice_is_auto_enrolled_unnamed(self, brain):
        """No generated placeholder name: "speaker-8842" reads as knowledge and
        is noise. Unnamed is honest."""
        vr = _wired(brain)
        out = vr.identify("marcus")
        assert out["known"] is True and out["auto_enrolled"] is True
        assert out["name"] == "" and out["unnamed"] is True

    def test_the_same_voice_is_recognised_next_time(self, brain):
        vr = _wired(brain)
        first = vr.identify("marcus")
        again = vr.identify("marcus")
        assert again["contact_id"] == first["contact_id"]
        assert again.get("auto_enrolled") is not True
        assert again["seen_count"] == 2

    def test_a_different_voice_is_a_different_person(self, brain):
        vr = _wired(brain)
        a = vr.identify("marcus")
        b = vr.identify("priya")
        assert a["contact_id"] != b["contact_id"]
        assert vr.status()["stored"] == 2

    def test_two_similar_voices_produce_no_confident_answer(self, brain):
        """A room of similar voices should yield "I am not sure" rather than a
        coin flip — the cost of a false match is a sentence attributed to the
        wrong person and stored as what they said."""
        vr = _wired(brain, auto=False)
        vr.identify("marcus")                        # nothing stored: auto off
        vr._people["m"] = {"name": "Marcus", "vec": [1.0, 0.0, 0.0], "auto": False,
                           "seen": 1, "first_ts": 0, "last_ts": 0}
        vr._people["n"] = {"name": "Nadia", "vec": [0.97, 0.24, 0.0], "auto": False,
                           "seen": 1, "first_ts": 0, "last_ts": 0}
        assert vr.identify("marcus-ish")["known"] is False

    def test_without_auto_enrol_a_stranger_is_not_stored(self, brain):
        """Somebody IS enrolled here, so the short-circuit below does not apply
        and the comparison genuinely runs — otherwise this would pass for the
        wrong reason."""
        vr = _wired(brain, auto=False)
        vr._people["m"] = {"name": "Marcus", "vec": [1.0, 0.0, 0.0], "auto": False,
                           "seen": 1, "first_ts": 0, "last_ts": 0}
        assert vr.identify("priya")["reason"] == "no-match"
        assert vr.status()["stored"] == 1             # the stranger was not added

    def test_with_nobody_enrolled_and_no_enrolling_it_returns_before_the_model(
            self, brain):
        """With no possible match there is no reason to compute a biometric of
        whoever is talking."""
        vr = _wired(brain, auto=False)
        assert vr.identify("marcus")["reason"] == "nobody-enrolled"

    def test_a_too_short_segment_is_refused(self, brain):
        """Short utterances embed unstably, and an unstable embedding
        auto-enrolled becomes a phantom that never matches again."""
        vr = _wired(brain)
        out = vr.identify("marcus", duration_s=VL.MIN_SEGMENT_S / 2)
        assert out["reason"] == "too-short"
        assert vr.status()["stored"] == 0

    def test_the_switch_being_off_stops_it(self, brain):
        vr = _wired(brain, on=False)
        assert vr.identify("marcus")["reason"] == "off"


class TestTheComparisonIsActuallyCosine:
    """`ECAPASpeaker.similarity` is a bare dot product and `embed` returns
    UN-NORMALISED model output, so using it would make the threshold scale with
    how loud someone spoke. The normalisation happens where the comparison does,
    and these use non-unit vectors — with unit vectors, cosine and dot product
    are identical and dropping the normalisation survives everything.
    """

    def test_loudness_does_not_change_the_verdict(self, brain):
        """The same direction at ten times the magnitude is the same speaker.
        As a raw dot product this scores 10.0 and as cosine it scores 1.0 —
        both above threshold, so the MISS case below is the one that bites."""
        vr = _wired(brain, auto=False)
        vr._people["m"] = {"name": "Marcus", "vec": [10.0, 0.0, 0.0],
                           "auto": False, "seen": 1, "first_ts": 0, "last_ts": 0}
        out = vr.identify("marcus")                  # embeds to [1, 0, 0]
        assert out["known"] is True
        assert out["confidence"] <= 1.0, "not a cosine — it exceeded 1"

    def test_a_quietly_spoken_match_is_still_a_match(self, brain):
        """The failure a dot product causes, in the direction that loses people.

        These two vectors point 60° apart — cosine 0.5, comfortably over the 0.40
        threshold — but both are small, so the raw dot product is 0.1, UNDER it.
        A dot product would therefore call this pair strangers purely because
        they spoke quietly, and with auto-enrol on it would store the same person
        again as a new speaker every time the room got quiet.
        """
        vr = _wired(brain, auto=False)
        vr._people["m"] = {"name": "Marcus", "vec": [0.2, 0.0, 0.0],
                           "auto": False, "seen": 1, "first_ts": 0, "last_ts": 0}

        class _Quiet(_FakeModel):
            def embed(self, audio, key=None):
                return [0.1, 0.1732, 0.0]            # 60° from [1,0,0], and tiny
        vr._embedder = _Quiet()
        out = vr.identify("whoever")
        assert out["known"] is True, out
        assert out["name"] == "Marcus"
        assert out["confidence"] == pytest.approx(0.5, abs=0.01)

    def test_cosine_is_scale_invariant(self):
        from dreamlayer.ai_brain.server.voice_live import _cosine
        assert _cosine([1.0, 0.0], [5.0, 0.0]) == pytest.approx(1.0)
        assert _cosine([3.0, 0.0], [0.0, 7.0]) == pytest.approx(0.0)


class TestNamingIsWhatMakesItUseful:

    def test_naming_promotes_an_auto_enrolled_voice(self, brain):
        vr = _wired(brain)
        cid = vr.identify("marcus")["contact_id"]
        assert vr.name_identity(cid, "Marcus")["ok"] is True
        assert vr._people[cid]["auto"] is False

    def test_a_named_voice_is_returned_by_the_resolver(self, brain):
        """The resolver's answer becomes `said_by`."""
        vr = _wired(brain)
        cid = vr.identify("marcus")["contact_id"]
        vr.name_identity(cid, "Marcus")
        assert vr.resolver()([1.0, 0.0, 0.0]) == "Marcus"

    def test_an_UNNAMED_voice_resolves_to_empty_not_to_its_id(self, brain):
        """The ledger depends on this. `said_by` must only ever hold a name a
        lens can match on — an id like "auto-1738…" in that field would make
        `owed()` treat the wearer's own promises as somebody else's."""
        vr = _wired(brain)
        vr.identify("marcus")
        assert vr.resolver()([1.0, 0.0, 0.0]) == ""

    def test_naming_requires_a_name(self, brain):
        vr = _wired(brain)
        cid = vr.identify("marcus")["contact_id"]
        assert vr.name_identity(cid, "   ")["ok"] is False

    def test_naming_an_unknown_voice_is_refused(self, brain):
        vr = _wired(brain)
        assert vr.name_identity("no-such-id", "Marcus")["ok"] is False


class TestTheStoreIsManageable:

    def test_the_listing_never_hands_back_a_vector(self, brain):
        """A voiceprint IS the biometric. The wearer needs to see what is held,
        not receive the templates on every poll."""
        vr = _wired(brain)
        vr.identify("marcus")
        rows = vr.people()
        assert rows and all("vec" not in r for r in rows), rows

    def test_two_voices_enrolled_back_to_back_are_two_records(self, brain):
        """The id collision, pinned. `auto-{int(time.time()*1000)}-{len(vec)%97}`
        looks unique and is not: every embedding from one model has the same
        length, so the second term is constant and two speakers enrolled inside
        one millisecond shared an id — the second silently REPLACING the first.
        A biometric record overwritten by a different person's. `face_live.py`
        had the identical bug; this store was copied from it."""
        vr = _wired(brain)
        a = vr.identify("marcus")["contact_id"]
        b = vr.identify("priya")["contact_id"]
        c = vr.identify("tomas")["contact_id"]
        assert len({a, b, c}) == 3, (a, b, c)
        assert vr.status()["stored"] == 3

    def test_the_face_store_does_not_collide_either(self, brain):
        """Same bug, same file family — this store was copied from that one.

        Asserted behaviourally rather than by reading the source: the existing
        face test-suite passes either way, which is exactly how the bug survived,
        and a scrape only proves a string is present. Two enrolments back to back
        land in the same millisecond, which is the failing case."""
        from dreamlayer.ai_brain.server.face_live import FaceRecall
        fr = FaceRecall(brain)
        a = fr._auto_enrol([0.1] * 512)["contact_id"]
        b = fr._auto_enrol([0.9] * 512)["contact_id"]
        assert a != b, (a, b)
        assert fr._get_index().size == 2, "one face template replaced another"

    def test_forgetting_one_voice(self, brain):
        vr = _wired(brain)
        cid = vr.identify("marcus")["contact_id"]
        assert vr.forget(cid)["ok"] is True
        assert vr.status()["stored"] == 0

    def test_forgetting_all(self, brain):
        vr = _wired(brain)
        vr.identify("marcus")
        vr.identify("priya")
        assert vr.forget_all() == 2

    def test_unnamed_voices_age_out_and_named_ones_do_not(self, brain):
        vr = _wired(brain)
        kept = vr.identify("marcus")["contact_id"]
        vr.name_identity(kept, "Marcus")
        stranger = vr.identify("priya")["contact_id"]
        vr._people[stranger]["last_ts"] = 0.0        # long ago
        vr._people[kept]["last_ts"] = 0.0            # equally long ago
        assert vr.sweep_unnamed(1.0) == 1
        assert kept in vr._people and stranger not in vr._people

    def test_the_store_survives_a_restart(self, brain):
        vr = _wired(brain)
        cid = vr.identify("marcus")["contact_id"]
        vr.name_identity(cid, "Marcus")
        fresh = VoiceRecall(brain)
        assert [p["name"] for p in fresh.people()] == ["Marcus"]

    def test_a_corrupt_index_degrades_rather_than_raising(self, brain):
        vr = _wired(brain)
        vr.identify("marcus")
        (brain.cfg_dir / VL.VOICE_INDEX_FILE).write_text("{not json")
        assert VoiceRecall(brain).people() == []


class TestTheEarSeam:

    def test_all_three_pieces_arrive_together(self, brain):
        """A pipeline given an embedder but no resolver computes a biometric of
        everyone in earshot and does nothing with it — the worst of both."""
        from dreamlayer.ai_brain.server.ear import EarHost
        vr = _wired(brain)
        cid = vr.identify("marcus")["contact_id"]
        vr.name_identity(cid, "Marcus")
        brain._voice_recall = vr
        embedder, resolver, enrolled = EarHost(brain)._voice_seam()
        assert embedder is not None and resolver is not None
        assert enrolled == ["Marcus"]

    def test_the_seam_is_empty_when_the_switch_is_off(self, brain):
        from dreamlayer.ai_brain.server.ear import EarHost
        vr = _wired(brain, on=False)
        brain._voice_recall = vr
        assert EarHost(brain)._voice_seam() == (None, None, None)

    def test_only_NAMED_voices_are_handed_to_voice_guard(self, brain):
        """`enrolled_speakers` decides which embeddings are RETAINED. An unnamed
        auto-enrolled id is not a name, and passing it would tell voice_guard a
        stranger is enrolled."""
        from dreamlayer.ai_brain.server.ear import EarHost
        vr = _wired(brain)
        vr.identify("marcus")                        # unnamed
        brain._voice_recall = vr
        assert EarHost(brain)._voice_seam()[2] == []


class TestEndToEndTheLensesFinallyAnswer:

    def test_an_attributed_utterance_becomes_recallable_by_name(self, brain):
        """The whole point, through the real path: a named voice resolves, the
        ear writes `said_by`, and `their_word` finds it."""
        from dreamlayer.ai_brain.server.ear import EarHost
        brain.config.listen_enabled = True
        vr = _wired(brain)
        cid = vr.identify("marcus")["contact_id"]
        vr.name_identity(cid, "Marcus")
        brain._voice_recall = vr
        speaker = vr.resolver()([1.0, 0.0, 0.0])
        EarHost(brain).ingest_caption("the roof was replaced last year",
                                      speaker=speaker)
        said = brain.lenses().their_word("Marcus").get("said") or []
        assert any("roof" in str(r.get("summary", "")).lower() for r in said), said

    def test_an_unattributed_utterance_still_reaches_your_own_ledger(self, brain):
        """The other side: with no confident speaker the line is the wearer's,
        and `owed()` must still hold it."""
        from dreamlayer.ai_brain.server.ear import EarHost
        brain.config.listen_enabled = True
        vr = _wired(brain)
        EarHost(brain).ingest_caption("I'll send the lease tomorrow",
                                      speaker=vr.resolver()([1.0, 0.0, 0.0]))
        assert brain.lenses().owed()["items"]


class TestTheCapabilityIsHonest:

    def test_speaker_id_stays_declared_dormant(self):
        from dreamlayer import capabilities as C
        assert "speaker_id" in C._NOT_WIRED

    def test_the_flag_needs_a_model_AND_consent_AND_the_switch(self, brain):
        import os
        from dreamlayer.ai_brain.server.server import _capability_payload
        vr = _wired(brain)
        brain._voice_recall = vr
        before = os.environ.get("DL_WIRED_SPEAKER_ID")
        assert _capability_payload(brain)["items"]
        assert os.environ.get("DL_WIRED_SPEAKER_ID") == before, \
            "the report mutated the real environment"

    def test_an_unconsented_brain_is_never_promoted(self, caps_env=None):
        from dreamlayer import capabilities as C
        cap = C._BY_KEY["speaker_id"]
        assert C.state(cap, env={}) in ("dormant", "missing", "off", "unsupported")


class TestItIsReachableFromTheSurface:

    def test_the_routes_are_registered(self):
        import pathlib
        from dreamlayer.ai_brain.server import server as S
        src = pathlib.Path(S.__file__).read_text(encoding="utf-8")
        for route in ('"/dreamlayer/voice": _get_voice',
                      '"/dreamlayer/voice/consent": _post_voice_consent',
                      '"/dreamlayer/voice/name": _post_voice_name',
                      '"/dreamlayer/voice/forget": _post_voice_forget'):
            assert route in src, route

    def test_the_state_route_never_returns_a_vector(self, brain):
        """A voiceprint IS the biometric. The listing exists so the wearer can
        manage what is held, not to ship the templates back on every poll."""
        vr = _wired(brain)
        vr.identify("marcus")
        brain._voice_recall = vr
        blob = repr(vr.status()) + repr(vr.people())
        assert "vec" not in blob, blob

    def test_the_panel_shows_the_consent_text_before_accepting(self):
        """The wearer should read the words they are agreeing to, where they
        agree to them — not find a switch that silently does nothing."""
        import pathlib
        from dreamlayer.ai_brain.server import panel as P
        src = pathlib.Path(P.__file__).read_text(encoding="utf-8")
        i = src.index("async function refreshVoiceRecall")
        body = src[i:i + 2600]
        assert "s.consented" in body and "consent_text" in body

    def test_the_panel_distinguishes_the_wheel_from_a_loaded_model(self):
        import pathlib
        from dreamlayer.ai_brain.server import panel as P
        src = pathlib.Path(P.__file__).read_text(encoding="utf-8")
        i = src.index("async function refreshVoiceRecall")
        assert "s.model_available" in src[i:i + 2600]

    def test_the_panel_offers_erase_and_withdraw(self):
        import pathlib
        from dreamlayer.ai_brain.server import panel as P
        src = pathlib.Path(P.__file__).read_text(encoding="utf-8")
        assert "async function voiceForgetAll" in src
        assert "async function voiceConsent" in src
        assert "voiceConsent(false)" in src

    def test_unnamed_voices_are_swept_by_retention(self, brain):
        """The same window faces use — it would be strange for two biometrics
        taken by the same product to expire on different rules."""
        import pathlib
        from dreamlayer.ai_brain.server import retention_live as R
        src = pathlib.Path(R.__file__).read_text(encoding="utf-8")
        assert "unnamed_voices_dropped" in src
        assert "vr.sweep_unnamed(policy.warm_days)" in src

    def test_the_panel_does_not_redefine_an_existing_function(self):
        """`refreshVoice` already existed for Juno's TTS readiness. A second
        declaration of the same name does not error in JS — the later one
        silently REPLACES the earlier, so adding voice recall would have broken
        the speak button with no sign of it. Caught only because a source-scrape
        test found the wrong function."""
        import pathlib
        import re
        from dreamlayer.ai_brain.server import panel as P
        src = pathlib.Path(P.__file__).read_text(encoding="utf-8")
        names = re.findall(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", src)
        dupes = sorted({n for n in names if names.count(n) > 1})
        assert not dupes, f"panel JS declares these more than once: {dupes}"
