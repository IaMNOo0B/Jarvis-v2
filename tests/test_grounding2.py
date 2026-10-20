"""Grounding-2 (Team 8 steals) — DVOC refinement loop + capture_id
freshness in jarvis/grounding.py, and the LoopGuard in jarvis/loop_guard.py.

The laws under test:
  * DVOC moves the point ONLY when it converges (two consecutive
    reported offsets below epsilon); damping follows the paper's
    schedule alpha = 1.0, 0.5, 0.25 (floored). Oscillation (sign flip
    with growing magnitude), exhaustion, and offsetter failure all keep
    the cascade point, honestly flagged in dvoc_outcome.
  * DVOC can never mint clickability: the verifier gate is untouched.
  * Every result carries a capture_id minted at observation time;
    assert_fresh rejects stale (size-changed) and foreign (not minted
    here) observations — mechanically, not by prompt.
  * LoopGuard verdicts are deterministic: STAGNANT (3 identical
    consecutive states) > CYCLE (trailing A->B->A) > REPEAT (same
    action >= 4 in the window) > OK, and the window really slides.
"""

import re

import pytest

from jarvis.grounding import (
    GroundResult, StaleCaptureError, assert_fresh, ground, refine,
)
from jarvis.loop_guard import CYCLE, OK, REPEAT, STAGNANT, LoopGuard

SIZE = (1400, 1050)  # cascade: coarse (700,525) -> crop (500,375,400,300)
                     # -> refined point_exact (600.0, 600.0), exact


class ScriptedGrounder:
    def __init__(self, full, crop):
        self.full, self.crop = full, crop
        self.calls = []

    def __call__(self, view, query):
        self.calls.append((view, query))
        return self.full if view is None else self.crop


def good_grounder():
    return ScriptedGrounder((0.5, 0.5, 0.9), (0.25, 0.75, 0.8))


def yes_verifier(box, query):
    return True


class ScriptedOffsetter:
    """Pops scripted (dx, dy, conf) returns; records every call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, point, crop_box):
        self.calls.append((point, crop_box))
        if self.script:
            return self.script.pop(0)
        return (0.0, 0.0, 0.9)


def dvoc_rounds(res):
    return [s for s in res.steps if s["action"] == "dvoc_round"]


# --------------------------------------------------------------------------- #
# DVOC — convergence, with the exact arithmetic of the damping schedule
# --------------------------------------------------------------------------- #

def test_dvoc_converges_and_point_is_exact():
    off = ScriptedOffsetter([(40.0, -20.0, 0.9),    # mag ~44.7, alpha 1.0
                             (1.5, 0.5, 0.9),       # mag ~1.58 < 2, a 0.5
                             (0.5, -0.25, 0.9)])    # mag ~0.56 < 2, a 0.25
    res = refine(SIZE, "save button", good_grounder(), off, yes_verifier,
                 epsilon_px=2.0)
    assert res.refined_dvoc is True and res.dvoc_outcome == "converged"
    # (600,600) + (40,-20) + 0.5*(1.5,0.5) + 0.25*(0.5,-0.25)
    assert res.point_exact == (640.875, 580.1875)
    assert res.point == (641, 580)
    # the offsetter was shown the moving point + the cascade crop box
    assert [c[0] for c in off.calls] == [(600.0, 600.0), (640.0, 580.0),
                                         (640.75, 580.25)]
    assert all(c[1] == (500, 375, 400, 300) for c in off.calls)
    rounds = dvoc_rounds(res)
    assert [r["alpha"] for r in rounds] == [1.0, 0.5, 0.25]
    assert [r["small_streak"] for r in rounds] == [0, 1, 2]
    assert rounds[-1]["outcome"] == "converged"
    assert len(res.steps) == 5 + 3  # cascade trail + 3 DVOC rounds
    # verifier gate untouched: verified stays verified
    assert res.verified is True and res.clickable is True


def test_dvoc_alpha_schedule_floors_at_quarter():
    off = ScriptedOffsetter([(8.0, 0.0, 0.9), (1.0, 0.0, 0.9),
                             (8.0, 0.0, 0.9), (1.0, 0.0, 0.9),
                             (0.5, 0.0, 0.9)])
    res = refine(SIZE, "x", good_grounder(), off, yes_verifier,
                 max_rounds=5, epsilon_px=2.0)
    assert res.dvoc_outcome == "converged"
    assert [r["alpha"] for r in dvoc_rounds(res)] == \
        [1.0, 0.5, 0.25, 0.25, 0.25]          # alpha(>=2) = 0.25, floored
    # 600 + 8 + 0.5*1 + 0.25*8 + 0.25*1 + 0.25*0.5
    assert res.point_exact == (610.875, 600.0)


def test_dvoc_offset_exactly_at_epsilon_is_not_small():
    off = ScriptedOffsetter([(2.0, 0.0, 0.9),   # mag == epsilon: NOT below
                             (1.0, 0.0, 0.9), (1.0, 0.0, 0.9)])
    res = refine(SIZE, "x", good_grounder(), off, yes_verifier,
                 epsilon_px=2.0)
    assert res.dvoc_outcome == "converged"
    rounds = dvoc_rounds(res)
    assert len(rounds) == 3 and rounds[0]["small_streak"] == 0
    assert res.point_exact == (602.75, 600.0)  # 600 + 2 + 0.5 + 0.25


def test_dvoc_never_mints_clickability():
    off = ScriptedOffsetter([(40.0, -20.0, 0.9), (1.5, 0.5, 0.9),
                             (0.5, -0.25, 0.9)])
    res = refine(SIZE, "x", good_grounder(), off, None,  # no verifier
                 epsilon_px=2.0)
    assert res.refined_dvoc is True            # the point DID refine…
    assert res.point_exact == (640.875, 580.1875)
    assert res.verified is False and res.clickable is False  # …not click
    assert res.reason == "unverified"


# --------------------------------------------------------------------------- #
# DVOC — failure modes all keep the cascade point, honestly flagged
# --------------------------------------------------------------------------- #

def test_dvoc_oscillation_aborts_and_keeps_cascade_point():
    off = ScriptedOffsetter([(10.0, 0.0, 0.9),     # applied -> (610, 600)
                             (-20.0, 0.0, 0.9)])   # flip + growing: abort
    res = refine(SIZE, "x", good_grounder(), off, yes_verifier,
                 epsilon_px=2.0)
    assert res.dvoc_outcome == "oscillating" and res.refined_dvoc is False
    assert res.point_exact == (600.0, 600.0) and res.point == (600, 600)
    assert len(off.calls) == 2
    last = dvoc_rounds(res)[-1]
    assert last["outcome"] == "oscillating" and "applied" not in last


def test_dvoc_sign_flip_with_shrinking_magnitude_is_not_oscillation():
    off = ScriptedOffsetter([(10.0, 0.0, 0.9), (-5.0, 0.0, 0.9),
                             (0.5, 0.0, 0.9), (0.25, 0.0, 0.9)])
    res = refine(SIZE, "x", good_grounder(), off, yes_verifier,
                 epsilon_px=2.0)
    assert res.dvoc_outcome == "converged"
    # 600 + 10 - 0.5*5 + 0.25*0.5 + 0.25*0.25
    assert res.point_exact == (607.6875, 600.0)


def test_dvoc_max_rounds_keeps_cascade_point():
    off = ScriptedOffsetter([(10.0, 0.0, 0.9)] * 4)  # never small
    res = refine(SIZE, "x", good_grounder(), off, yes_verifier,
                 epsilon_px=2.0)  # default max_rounds=4
    assert res.dvoc_outcome == "not_converged" and res.refined_dvoc is False
    assert res.point_exact == (600.0, 600.0)
    assert len(off.calls) == 4


def test_dvoc_offsetter_failures_fail_closed():
    def boom(point, box):
        raise RuntimeError("offset model down")

    res = refine(SIZE, "x", good_grounder(), boom, yes_verifier,
                 epsilon_px=2.0)
    assert res.dvoc_outcome == "offsetter_error"
    assert res.point_exact == (600.0, 600.0)
    assert "offset model down" in dvoc_rounds(res)[-1]["error"]

    for bad in (None, "banana", (float("nan"), 0.0, 0.9)):
        off = ScriptedOffsetter([bad])
        res = refine(SIZE, "x", good_grounder(), off, yes_verifier,
                     epsilon_px=2.0)
        assert res.dvoc_outcome == "offsetter_error"
        assert res.point_exact == (600.0, 600.0)


def test_dvoc_no_cascade_point_no_refinement():
    off = ScriptedOffsetter([(1.0, 1.0, 0.9)])
    res = refine(SIZE, "missing", ScriptedGrounder(None, None), off,
                 yes_verifier, epsilon_px=2.0)
    assert res.found is False and res.dvoc_outcome == "no_point"
    assert off.calls == []  # the offsetter is never consulted


def test_refine_bad_inputs_are_loud():
    with pytest.raises(ValueError):
        refine(SIZE, "x", good_grounder(), None, yes_verifier)
    with pytest.raises(ValueError):
        refine(SIZE, "x", good_grounder(), ScriptedOffsetter([]),
               yes_verifier, max_rounds=0)
    with pytest.raises(ValueError):
        refine(SIZE, "x", good_grounder(), ScriptedOffsetter([]),
               yes_verifier, epsilon_px=0)


# --------------------------------------------------------------------------- #
# capture_id — minted at observation, bound to size, foreign rejected
# --------------------------------------------------------------------------- #

def test_capture_id_minted_and_unique():
    a = ground(SIZE, "x", good_grounder(), yes_verifier)
    b = ground(SIZE, "x", good_grounder(), yes_verifier)
    assert re.fullmatch(r"[0-9a-f]{32}", a.capture_id)
    assert a.capture_id != b.capture_id
    d = a.to_dict()
    assert d["capture_id"] == a.capture_id
    assert d["refined_dvoc"] is False and d["dvoc_outcome"] == ""
    import json
    json.dumps(d)


def test_assert_fresh_accepts_own_observation():
    res = ground(SIZE, "x", good_grounder(), yes_verifier)
    assert assert_fresh(res, image_size=SIZE) == res.capture_id
    assert assert_fresh(res.to_dict(), image_size=SIZE) == res.capture_id


def test_assert_fresh_rejects_size_change_as_stale():
    res = ground(SIZE, "x", good_grounder(), yes_verifier)
    with pytest.raises(StaleCaptureError, match="stale"):
        assert_fresh(res, image_size=(800, 600))
    d = res.to_dict()
    d["image_size"] = [800, 600]
    with pytest.raises(StaleCaptureError, match="stale"):
        assert_fresh(d, image_size=SIZE)


def test_assert_fresh_rejects_foreign_and_missing_ids():
    assert issubclass(StaleCaptureError, ValueError)
    foreign = GroundResult(query="x", image_size=SIZE, found=False,
                           capture_id="ab" * 16)  # well-formed, unminted
    with pytest.raises(StaleCaptureError, match="foreign"):
        assert_fresh(foreign, image_size=SIZE)
    missing = GroundResult(query="x", image_size=SIZE, found=False,
                           capture_id="")
    with pytest.raises(StaleCaptureError, match="no capture_id"):
        assert_fresh(missing, image_size=SIZE)
    res = ground(SIZE, "x", good_grounder(), yes_verifier)
    from dataclasses import replace
    tampered = replace(res, capture_id="zz" * 16)  # not even hex
    with pytest.raises(StaleCaptureError, match="foreign"):
        assert_fresh(tampered, image_size=SIZE)
    with pytest.raises(StaleCaptureError):
        assert_fresh("not a result", image_size=SIZE)


def test_refined_result_keeps_its_capture():
    off = ScriptedOffsetter([(1.0, 0.0, 0.9), (0.5, 0.0, 0.9)])
    res = refine(SIZE, "x", good_grounder(), off, yes_verifier,
                 epsilon_px=2.0)
    assert res.refined_dvoc is True
    assert assert_fresh(res, image_size=SIZE) == res.capture_id


# --------------------------------------------------------------------------- #
# LoopGuard — the verdict table
# --------------------------------------------------------------------------- #

def test_loopguard_single_observation_is_ok():
    assert LoopGuard().observe("act", "s1") == OK


def test_loopguard_repeat_needs_four_in_window():
    g = LoopGuard()
    verdicts = [g.observe("act", f"s{i}") for i in range(4)]
    assert verdicts == [OK, OK, OK, REPEAT]  # states change: pure REPEAT


def test_loopguard_stagnant_needs_three_identical_states():
    g = LoopGuard()
    assert g.observe("a", "frozen") == OK
    assert g.observe("b", "frozen") == OK
    assert g.observe("c", "frozen") == STAGNANT  # actions differ; world froze


def test_loopguard_cycle_is_trailing_aba():
    g = LoopGuard()
    assert g.observe("a", "s1") == OK
    assert g.observe("b", "s2") == OK
    assert g.observe("a", "s3") == CYCLE
    assert g.observe("b", "s4") == CYCLE  # B->A->B is the same ping-pong


def test_loopguard_stagnant_beats_cycle():
    g = LoopGuard()
    g.observe("a", "frozen")
    g.observe("b", "frozen")
    # trailing actions form A->B->A AND the world never moved: STAGNANT
    assert g.observe("a", "frozen") == STAGNANT


def test_loopguard_no_false_cycle_on_abca():
    g = LoopGuard()
    verdicts = [g.observe(a, f"s{i}")
                for i, a in enumerate(["a", "b", "c", "a"])]
    assert verdicts[-1] == OK  # trailing triple is B,C,A — no ping-pong


def test_loopguard_window_really_slides():
    g = LoopGuard(window=5)
    seq = ["a", "a", "a", "b", "c", "d", "e", "a"]
    verdicts = [g.observe(a, f"s{i}") for i, a in enumerate(seq)]
    # the final "a" is the only one left in the 5-window: no REPEAT
    assert verdicts == [OK] * len(seq)


def test_loopguard_deterministic_verdict_table():
    script = [("open", "s1"), ("read", "s2"), ("open", "s3"),
              ("read", "s4"), ("open", "s5"), ("open", "s6"),
              ("open", "s7"), ("open", "s8")]
    expected = [OK, OK, CYCLE, CYCLE, CYCLE, REPEAT, REPEAT, REPEAT]
    for _ in range(2):  # two fresh guards, identical verdicts
        g = LoopGuard()
        assert [g.observe(a, s) for a, s in script] == expected


def test_loopguard_accepts_tuple_fingerprints():
    g = LoopGuard()
    fp = (0x2A0F, "elements-hash")  # (HWND, hash) — the Windows-Use shape
    assert g.observe("a", fp) == OK
    assert g.observe("b", fp) == OK
    assert g.observe("c", fp) == STAGNANT


def test_loopguard_reset_and_window_validation():
    with pytest.raises(ValueError):
        LoopGuard(window=0)
    g = LoopGuard()
    for i in range(4):
        g.observe("act", f"s{i}")
    assert len(g) == 4
    g.reset()
    assert len(g) == 0 and g.observe("act", "s9") == OK
