"""Vision grounding cascade (Team 18 steal #1) — jarvis/grounding.py +
the pc.ground tool surface and verified-only click path in pc_control.

The laws under test:
  * cascade math is exact: coarse -> crop (3.5x, clamped) -> re-ground ->
    project back, every step recorded in the audit trail;
  * NO vision point is clickable until a verifier confirms the refined
    crop (best-case first-look grounding is wrong ~40% — Team 18);
  * unverified targets are refused AT the click path; UIA clicks are
    exempt (they carry snapshot identity, never pass through here);
  * no grounder configured = an honest answer, never a fabricated point.
"""

import pytest

from jarvis import grounding
from jarvis.grounding import GroundResult, crop_box_for, ground, project
from jarvis import pc_control as pc
from jarvis.pc_control import (
    ActionFailedError, FakeUiaBackend, PCController, TIER_READ,
    as_gate_registry, tool_definitions,
)

SIZE = (1400, 1050)  # /3.5 -> exactly 400x300 crop; all math below is exact


class ScriptedGrounder:
    """Returns `full` for the full view, `crop` for any crop view."""

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


# --------------------------------------------------------------------------- #
# Cascade math — exact
# --------------------------------------------------------------------------- #

def test_cascade_math_is_exact():
    res = ground(SIZE, "save button", good_grounder(), yes_verifier)
    assert res.found is True
    assert res.coarse == (0.5, 0.5)
    assert res.coarse_pixel == (700.0, 525.0)
    # crop: 400x300 centered on (700, 525) -> origin (500, 375)
    assert res.crop_box == (500, 375, 400, 300)
    assert res.refined == (0.25, 0.75)
    # project: 500 + 0.25*400 = 600 ; 375 + 0.75*300 = 600
    assert res.point_exact == (600.0, 600.0)
    assert res.point == (600, 600)
    assert res.confidence == 0.8  # the refined call's confidence wins
    assert res.verified is True and res.clickable is True
    assert res.reason == "verified"


def test_project_helper_exact():
    assert project((500, 375, 400, 300), (0.25, 0.75)) == (600.0, 600.0)
    assert project((0, 0, 100, 100), (0.0, 1.0)) == (0.0, 100.0)


def test_crop_clamped_to_image_bounds():
    g = ScriptedGrounder((0.0, 1.0, 0.9), (0.5, 0.5, 0.9))
    res = ground(SIZE, "corner widget", g, yes_verifier)
    x0, y0, cw, ch = res.crop_box
    assert (x0, y0, cw, ch) == (0, 750, 400, 300)  # clamped, still 400x300
    assert 0 <= x0 and x0 + cw <= SIZE[0]
    assert 0 <= y0 and y0 + ch <= SIZE[1]
    assert res.point_exact == (200.0, 900.0)


def test_crop_box_for_zoom_parameter():
    assert crop_box_for((1000, 500), (500.0, 250.0), zoom=2.0) == \
        (250, 125, 500, 250)
    assert crop_box_for(SIZE, (700.0, 525.0)) == (500, 375, 400, 300)


def test_audit_trail_records_every_step():
    res = ground(SIZE, "save button", good_grounder(), yes_verifier)
    actions = [s["action"] for s in res.steps]
    assert actions == ["ground_full", "crop", "ground_crop", "project",
                       "verify"]
    s1, s2, s3, s4, s5 = res.steps
    assert s1["normalized"] == [0.5, 0.5] and s1["confidence"] == 0.9
    assert s1["pixel"] == [700.0, 525.0]
    assert s2["crop_box"] == [500, 375, 400, 300] and s2["zoom"] == 3.5
    assert s3["view"] == [500, 375, 400, 300]
    assert s3["normalized"] == [0.25, 0.75]
    assert s4["point_exact"] == [600.0, 600.0] and s4["point"] == [600, 600]
    assert s5["verified"] is True


def test_grounder_call_contract():
    g = good_grounder()
    seen = {}

    def verifier(box, query):
        seen["box"], seen["query"] = box, query
        return True

    ground(SIZE, "save button", g, verifier)
    assert g.calls[0] == (None, "save button")          # full view first
    assert g.calls[1] == ((500, 375, 400, 300), "save button")  # then crop
    assert seen == {"box": (500, 375, 400, 300), "query": "save button"}


def test_out_of_range_output_is_clamped_and_noted():
    g = ScriptedGrounder((1.4, -0.2, 2.0), (0.5, 0.5, 0.5))
    res = ground(SIZE, "edge", g, yes_verifier)
    assert res.coarse == (1.0, 0.0)
    assert res.coarse_pixel == (1400.0, 0.0)
    assert res.steps[0]["clamped"] is True


# --------------------------------------------------------------------------- #
# Fail-closed paths
# --------------------------------------------------------------------------- #

def test_not_found_when_grounder_sees_nothing():
    g = ScriptedGrounder(None, (0.5, 0.5, 0.9))
    res = ground(SIZE, "missing thing", g, yes_verifier)
    assert res.found is False and res.point is None
    assert res.clickable is False and res.reason == "not_found"
    assert len(g.calls) == 1  # no crop is attempted without a coarse point


def test_refinement_failure_keeps_coarse_point_but_never_clickable():
    g = ScriptedGrounder((0.5, 0.5, 0.9), None)
    res = ground(SIZE, "save button", g, yes_verifier)
    assert res.found is True and res.refined is None
    assert res.point == (700, 525)  # coarse point, for display only
    assert res.clickable is False and res.reason == "refinement_failed"


def test_grounder_exception_fails_closed():
    def boom(view, query):
        raise RuntimeError("model exploded")

    res = ground(SIZE, "x", boom, yes_verifier)
    assert res.found is False and res.clickable is False
    assert res.reason == "grounder_error"
    assert "model exploded" in res.steps[0]["error"]


def test_malformed_grounder_output_fails_closed():
    g = ScriptedGrounder("banana", (0.5, 0.5, 0.5))
    res = ground(SIZE, "x", g, yes_verifier)
    assert res.found is False and res.reason == "grounder_error"


def test_bad_inputs_are_loud():
    with pytest.raises(ValueError):
        ground((0, 100), "x", good_grounder(), yes_verifier)
    with pytest.raises(ValueError):
        ground(SIZE, "x", None, yes_verifier)


# --------------------------------------------------------------------------- #
# The verifier gate
# --------------------------------------------------------------------------- #

def test_verifier_rejection_means_unverified():
    res = ground(SIZE, "save button", good_grounder(),
                 lambda box, q: False)
    assert res.found is True and res.point == (600, 600)  # point exists…
    assert res.verified is False and res.clickable is False  # …not clickable
    assert res.reason == "unverified"


def test_no_verifier_means_unverified_fail_closed():
    res = ground(SIZE, "save button", good_grounder())  # verifier=None
    assert res.clickable is False and res.reason == "unverified"
    assert res.steps[-1]["verifier"] == "absent"


def test_verifier_exception_means_unverified():
    def boom(box, query):
        raise RuntimeError("verifier down")

    res = ground(SIZE, "save button", good_grounder(), boom)
    assert res.verified is False and res.clickable is False
    assert res.reason == "unverified"
    assert "verifier down" in res.steps[-1]["error"]


# --------------------------------------------------------------------------- #
# PCController: tool surface + click-path refusal
# --------------------------------------------------------------------------- #

def _controller(**kw):
    return PCController(backend=FakeUiaBackend(), **kw)


def test_pc_ground_tool_definition_is_tier1_read():
    defs = {t["name"]: t for t in tool_definitions()}
    g = defs["pc.ground"]
    assert g["tier"] == TIER_READ == 1
    assert g["capabilities"] == ["ui.read"]
    assert g["schema"]["required"] == ["query"]
    assert as_gate_registry()["pc.ground"]["tier"] == 1


def test_no_grounder_configured_is_honest():
    backend = FakeUiaBackend()
    ctl = PCController(backend=backend)
    out = ctl.ground_target("save button")
    assert out["ok"] is False and out["available"] is False
    assert out["reason"] == "no grounder configured"
    assert out["point"] is None and out["clickable"] is False
    # short-circuits before any screenshot: nothing wasted, nothing faked
    assert backend.calls_to("capture_pixels") == []


def test_ground_target_end_to_end_dict():
    ctl = _controller(grounder=good_grounder(), verifier=yes_verifier)
    out = ctl.ground_target("save button")
    assert out["ok"] is True and out["available"] is True
    assert out["found"] is True and out["clickable"] is True
    assert out["reason"] == "verified"
    assert out["image_size"] == [64, 48]  # FakeUiaBackend's frame
    assert len(out["steps"]) == 5


def test_per_call_grounder_overrides_configured():
    ctl = _controller(grounder=ScriptedGrounder(None, None))
    out = ctl.ground_target("save button", grounder=good_grounder(),
                            verifier=yes_verifier)
    assert out["found"] is True


def test_click_grounded_refuses_unverified():
    backend = FakeUiaBackend()
    ctl = PCController(backend=backend, grounder=good_grounder(),
                       verifier=lambda box, q: False)
    out = ctl.ground_target("save button")
    assert out["point"] is not None and out["clickable"] is False
    with pytest.raises(ActionFailedError, match="unverified"):
        ctl.click_grounded(out)
    assert backend.calls_to("click_at") == []  # nothing was clicked


def test_click_grounded_refuses_groundresult_object_too():
    res = ground(SIZE, "save button", good_grounder())  # no verifier
    assert isinstance(res, GroundResult) and res.clickable is False
    ctl = _controller()
    with pytest.raises(ActionFailedError):
        ctl.click_grounded(res)
    with pytest.raises(ActionFailedError):
        ctl.click_grounded({"clickable": True})  # no point -> refuse
    with pytest.raises(ActionFailedError):
        ctl.click_grounded("not a result")


def test_click_grounded_clicks_verified_point_exactly():
    backend = FakeUiaBackend()
    ctl = PCController(backend=backend, grounder=good_grounder(),
                       verifier=yes_verifier)
    out = ctl.ground_target("save button")
    res = ctl.click_grounded(out)
    assert res["ok"] is True and res["provenance"] == "vision"
    clicks = backend.calls_to("click_at")
    assert len(clicks) == 1
    assert list(clicks[0][1]) == out["point"]  # exactly the proposed point


def test_uia_click_path_is_exempt_from_verifier_gate():
    # No grounder/verifier configured at all: UIA clicks still work —
    # they carry snapshot identity and never pass through the vision gate.
    backend = FakeUiaBackend(elements=[
        {"element_id": "42", "role": "button", "name": "Save",
         "bounding_box": (10, 10, 80, 30), "elevated": False}])
    ctl = PCController(backend=backend)
    ctl.observe()
    assert ctl.click_element("42")["ok"] is True
    assert len(backend.calls_to("click")) == 1


def test_ground_target_empty_query_refused():
    ctl = _controller(grounder=good_grounder(), verifier=yes_verifier)
    with pytest.raises(ActionFailedError):
        ctl.ground_target("   ")


def test_result_dict_roundtrip():
    res = ground(SIZE, "save button", good_grounder(), yes_verifier)
    d = res.to_dict()
    assert d["crop_box"] == [500, 375, 400, 300]
    assert d["point"] == [600, 600] and d["clickable"] is True
    import json
    json.dumps(d)  # the audit trail must be JSON-safe for session logs
