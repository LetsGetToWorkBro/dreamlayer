"""Full-stack audit, lens slice — the shipped build must not fabricate identity.

Every test here runs against the PRODUCTION `FaceEmbedder` (via the
`no_face_double` marker, which opts out of conftest's suite-wide test double), so
it asserts what a real device does rather than what the suite's double does.

The defect these pin was not a crash and not a leak. It was a confident lie: a
512-d embedding seeded from the frame's *pixel sum*, which made two visually
unrelated frames byte-identical in embedding space about once every 43,800 pairs
— and 100% of the time for any two frames that were permutations, reflections,
or uniform fields of each other. The wearer saw a stranger's face captioned with
a real contact's name, relationship, notes, and "100% match". Meanwhile two
photographs of the same person scored ~0.00, so the feature never worked; its
only successful output was the wrong answer.
"""
from __future__ import annotations

import numpy as np
import pytest

from dreamlayer.social_lens.analyzer import SocialLens
from dreamlayer.social_lens.embedder import embed_frame
from dreamlayer.truth_lens.face_embed import (DETECTION_THRESHOLD, FaceEmbedder,
                                              deterministic_embed_fn)

pytestmark = pytest.mark.no_face_double


class _Open:
    def allow_capture(self):
        return True


def _equal_sum_pair():
    """Two visually unrelated 96x96x3 frames with an identical pixel sum."""
    a = np.zeros((96, 96, 3), dtype=np.uint8)
    a[:48] = 200                                    # top half bright
    b = np.zeros((96, 96, 3), dtype=np.uint8)
    b[48:] = 200                                    # bottom half bright
    assert int(a.sum()) == int(b.sum())
    assert not np.array_equal(a, b)
    return a, b


def test_the_production_embedder_declines_rather_than_guess():
    emb = FaceEmbedder()
    assert emb.available is False
    for frame in (np.full((96, 96, 3), 200, np.uint8), *_equal_sum_pair()):
        assert emb.process_frame(frame) is None


def test_a_single_white_pixel_no_longer_asserts_a_face_at_100_percent():
    # `mean(abs(frame))` is 0-255 for uint8 and was compared against a 0.50
    # threshold, then clamped to 1.0 -- so any non-black image claimed a face,
    # always at full confidence, and the renderer's MIN_FRAME_CONFIDENCE guard
    # could never fire.
    assert FaceEmbedder().process_frame(np.array([[[255, 255, 255]]],
                                                 np.uint8)) is None


def test_a_normalised_float_frame_is_not_mistaken_for_an_empty_one():
    # The mirror-image bug: a float32 frame in [0,1] with mean < 0.5 reported
    # "no face detected" WITH a face present, because the units were wrong.
    # The seam now judges nothing at all rather than judging on brightness.
    frame = np.full((96, 96, 3), 0.35, dtype=np.float32)
    assert FaceEmbedder().process_frame(frame) is None


def test_a_miscalibrated_backend_is_declined_not_clamped_to_certainty():
    """A confidence outside [0,1] is a broken backend, not a very sure one.
    Clamping 255 down to 1.0 is precisely how the pixel-mean stub came to
    assert a face in every non-black image."""
    emb = FaceEmbedder(embed_fn=lambda f: ([0.0] * 512, 255.0))
    assert emb.process_frame(np.full((8, 8, 3), 128, np.uint8)) is None


def test_a_nan_frame_returns_none_instead_of_raising():
    # `int(np.sum(frame))` raised ValueError on NaN and OverflowError on Inf,
    # out of a method whose contract is "never raises".
    emb = FaceEmbedder(embed_fn=deterministic_embed_fn())
    for bad in (np.full((8, 8, 3), np.nan, np.float32),
                np.full((8, 8, 3), np.inf, np.float32)):
        assert emb.process_frame(bad) is None


def test_a_stranger_is_never_announced_as_a_contact():
    """The end-to-end statement: enrol from one frame, present a different frame
    with the same pixel sum, and the wearer must not be told a name."""
    a, b = _equal_sum_pair()
    lens = SocialLens(privacy=_Open())
    lens.meet("Maya Chen", frame=a)
    res = lens.identify(b)
    assert res.match is None
    card = res.to_hud_card()
    assert "Maya Chen" not in card["lines"]
    assert "100% match" not in card["lines"]


def test_equal_sum_frames_do_not_share_an_embedding_even_in_the_double():
    """The double exists so the suite can exercise downstream logic. It must not
    reintroduce the defect: it keys on the frame's BYTES, not their sum."""
    a, b = _equal_sum_pair()
    fn = deterministic_embed_fn()
    ea, _ = fn(a)
    eb, _ = fn(b)
    from dreamlayer.truth_lens.face_embed import cosine_similarity
    assert abs(cosine_similarity(ea, eb)) < 0.65
    # …and it still recalls the same image, or it would be useless as a double.
    assert cosine_similarity(ea, fn(a)[0]) == pytest.approx(1.0, abs=1e-6)


def test_no_model_reads_as_unavailable_not_as_an_absent_face():
    """"No face detected" is a claim about the world. With no embedder the system
    has not looked, so it says the true thing instead."""
    res = SocialLens(privacy=_Open()).identify(np.full((96, 96, 3), 200, np.uint8))
    assert res.unavailable is True
    assert res.no_face is False
    assert res.to_hud_card()["primary"] == "Face recall isn't set up"


def test_embed_frame_reports_no_embedding_and_zero_confidence():
    emb, conf = embed_frame(np.full((96, 96, 3), 200, np.uint8))
    assert emb is None and conf == 0.0


def test_the_detection_threshold_is_still_honoured_when_a_model_exists():
    """The gate must not have been loosened while making the seam fail closed."""
    low = FaceEmbedder(embed_fn=lambda f: ([0.0] * 512, DETECTION_THRESHOLD - 0.01))
    high = FaceEmbedder(embed_fn=lambda f: ([1.0] + [0.0] * 511,
                                            DETECTION_THRESHOLD + 0.01))
    frame = np.full((8, 8, 3), 128, np.uint8)
    assert low.process_frame(frame) is None
    assert high.process_frame(frame) is not None
