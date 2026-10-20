"""Speech priority core — SSIP × NVDA semantics in jarvis.tts.

The matrix under test (chunk = one sentence; preemption happens ONLY
at chunk boundaries, so the chunk in flight always finishes honestly):

    arrival \\ playing | URGENT        | NORMAL        | LOW
    -------------------+---------------+---------------+---------------
    URGENT             | FIFO (queue)  | preempts      | preempts
    NORMAL             | queues        | FIFO (queue)  | preempts
    LOW                | queues        | queues        | FIFO (queue)

"Preempts" = the playing item is POSTPONED at the next chunk
boundary (remaining chunks resume when the higher work drains) —
never dropped. Manual postpone() parks a LOW item until resume().
cancel(priority) drops queued work of a class and stops a playing
item of that class. key= gives a slot latest-wins semantics over
STILL-QUEUED items only. on_spoken(chunk_id, text) reports exactly
what left the speakers, in spoken order.

Determinism: no wall-clock semantics exist in the core (preemption
is event-driven), so the fake engine replaces the clock — a word
leaves the speakers only when the test issues a permit. wait_for
polls below are failure safeties, never synchronisation.
"""

import threading
import time

import pytest

from jarvis.tts import (
    INTERRUPTED,
    LOW,
    NORMAL,
    SKIPPED,
    SPOKEN,
    URGENT,
    Engine,
    Speaker,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class ControlledEngine(Engine):
    """A word leaves the speakers only when the test issues a permit.

    With auto=True every word flows immediately (completion tests).
    Otherwise speak_sentence blocks per word on a semaphore, so the
    test controls chunk boundaries exactly.
    """

    name = "controlled"

    def __init__(self, auto: bool = False) -> None:
        self.started: list = []
        self.finished: list = []
        self._permits = threading.Semaphore(0)
        self._auto = auto
        self._cond = threading.Condition()

    # -- test controls --------------------------------------------------- #

    def allow(self, words: int = 1) -> None:
        for _ in range(words):
            self._permits.release()

    def wait_started(self, text: str, timeout: float = 5.0) -> None:
        with self._cond:
            ok = self._cond.wait_for(lambda: text in self.started, timeout)
        assert ok, f"engine never started {text!r}; started={self.started}"

    def wait_finished(self, text: str, timeout: float = 5.0) -> None:
        with self._cond:
            ok = self._cond.wait_for(lambda: text in self.finished, timeout)
        assert ok, f"engine never finished {text!r}; finished={self.finished}"

    # -- Engine contract --------------------------------------------------- #

    def speak_sentence(self, text, on_word):
        with self._cond:
            self.started.append(text)
            self._cond.notify_all()
        for i in range(len(text.split())):
            if not self._auto:
                self._permits.acquire()
            on_word(i)
        with self._cond:
            self.finished.append(text)
            self._cond.notify_all()


def wait_for(pred, timeout=5.0, poll=0.005):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(poll)
    raise AssertionError("timed out waiting for condition")


def make_speaker(engine=None, on_spoken=None):
    states = []
    sp = Speaker(on_state=states.append, engine=engine or ControlledEngine(),
                 on_spoken=on_spoken)
    return sp, states


def spoken_log():
    log = []
    return log, lambda cid, text: log.append((cid, text))


# --------------------------------------------------------------------------- #
# 1. The preempt matrix
# --------------------------------------------------------------------------- #

LOW1 = "low one starts here."
LOW2 = "low two follows now."
URG = "urgent alert now."


def test_urgent_preempts_low_and_low_resumes():
    eng = ControlledEngine()
    log, on_spoken = spoken_log()
    sp, _states = make_speaker(eng, on_spoken)
    utt_low = sp.speak(f"{LOW1} {LOW2}", priority=LOW)
    eng.wait_started(LOW1)
    eng.allow(2)  # mid-chunk: two of four words are out
    utt_urg = sp.speak(URG, priority=URGENT)
    eng.allow(2)  # LOW chunk 1 finishes honestly
    eng.wait_started(URG)
    assert LOW2 not in eng.started  # postponed, NOT dropped, NOT played
    eng.allow(3)
    eng.wait_finished(URG)
    eng.wait_started(LOW2)  # resumed by itself after the urgent drained
    eng.allow(4)
    assert utt_low.wait(5) and utt_urg.wait(5)
    assert eng.finished == [LOW1, URG, LOW2]
    assert utt_low.sentence_status == [SPOKEN, SPOKEN]
    assert utt_low.interrupted_at is None  # a postponement is not a cut
    # Callback stream: spoken order, exact texts, chunk ids identify
    # the chunks (LOW kept ids 1,2; URGENT took 3 — ids are assigned
    # at enqueue, so under preemption they are not fire-ordered).
    assert log == [(1, LOW1), (3, URG), (2, LOW2)]


def test_urgent_preempts_normal_and_normal_resumes():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    n1, n2 = "normal one begins.", "normal two resumes."
    utt_n = sp.speak(f"{n1} {n2}", priority=NORMAL)
    eng.wait_started(n1)
    utt_u = sp.speak(URG, priority=URGENT)
    eng.allow(3)
    eng.wait_started(URG)
    assert n2 not in eng.started
    eng.allow(3)
    eng.wait_started(n2)
    eng.allow(3)
    assert utt_n.wait(5) and utt_u.wait(5)
    assert eng.finished == [n1, URG, n2]
    assert utt_n.sentence_status == [SPOKEN, SPOKEN]


def test_normal_preempts_low():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    utt_low = sp.speak(f"{LOW1} {LOW2}", priority=LOW)
    eng.wait_started(LOW1)
    note = "normal note here."
    utt_n = sp.speak(note, priority=NORMAL)
    eng.allow(4)
    eng.wait_started(note)
    assert LOW2 not in eng.started
    eng.allow(3)
    eng.wait_started(LOW2)
    eng.allow(4)
    assert utt_low.wait(5) and utt_n.wait(5)
    assert eng.finished == [LOW1, note, LOW2]


def test_normal_never_preempts_normal_fifo():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    a1, a2, b = "first part one.", "second part two.", "bee item here."
    utt_a = sp.speak(f"{a1} {a2}", priority=NORMAL)
    eng.wait_started(a1)
    utt_b = sp.speak(b, priority=NORMAL)
    eng.allow(3)
    eng.wait_started(a2)
    assert b not in eng.started  # B may NOT slip between A's chunks
    eng.allow(3)
    eng.wait_started(b)
    eng.allow(3)
    assert utt_a.wait(5) and utt_b.wait(5)
    assert eng.finished == [a1, a2, b]


def test_urgent_fifo_within_class_and_low_waits():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    u1, u2 = "urgent one here.", "urgent two here."
    utt1 = sp.speak(u1, priority=URGENT)
    eng.wait_started(u1)
    utt2 = sp.speak(u2, priority=URGENT)
    utt_low = sp.speak(LOW1, priority=LOW)
    eng.allow(3)
    eng.wait_started(u2)  # FIFO among URGENT peers — never preempted
    assert LOW1 not in eng.started
    eng.allow(3)
    eng.wait_started(LOW1)
    eng.allow(4)
    assert utt1.wait(5) and utt2.wait(5) and utt_low.wait(5)
    assert eng.finished == [u1, u2, LOW1]


def test_low_plays_when_alone():
    eng = ControlledEngine(auto=True)
    sp, _ = make_speaker(eng)
    utt = sp.speak("quiet digest item.", priority=LOW)
    assert utt.wait(5)
    assert utt.sentence_status == [SPOKEN]


# --------------------------------------------------------------------------- #
# 2. Legacy commit interplay (bare speak() against priority items)
# --------------------------------------------------------------------------- #

def test_legacy_commit_postpones_low_and_low_resumes():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    utt_low = sp.speak(f"{LOW1} {LOW2}", priority=LOW)
    eng.wait_started(LOW1)
    reply = "fresh reply here."
    utt_r = sp.speak(reply)  # bare speak(): the conversational commit
    eng.allow(4)
    eng.wait_started(reply)
    assert LOW2 not in eng.started
    eng.allow(3)
    eng.wait_started(LOW2)
    eng.allow(4)
    assert utt_low.wait(5) and utt_r.wait(5)
    assert eng.finished == [LOW1, reply, LOW2]
    # Postponed, not abandoned: the digest completes in full.
    assert utt_low.sentence_status == [SPOKEN, SPOKEN]
    assert utt_low.interrupted_at is None


def test_legacy_commit_queues_behind_urgent():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    utt_u = sp.speak(URG, priority=URGENT)
    eng.wait_started(URG)
    reply = "queued reply here."
    utt_r = sp.speak(reply)  # must NOT kill the alert
    assert eng.started == [URG]
    eng.allow(3)
    eng.wait_started(reply)
    eng.allow(3)
    assert utt_u.wait(5) and utt_r.wait(5)
    assert eng.finished == [URG, reply]
    assert utt_u.sentence_status == [SPOKEN]


# --------------------------------------------------------------------------- #
# 3. postpone() / resume() — the manual park (LOW only)
# --------------------------------------------------------------------------- #

def test_postpone_parks_low_until_resume():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    utt_low = sp.speak(f"{LOW1} {LOW2}", priority=LOW)
    eng.wait_started(LOW1)
    assert sp.postpone() is utt_low
    eng.allow(4)  # chunk in flight finishes honestly, THEN the park
    wait_for(lambda: sp.postponed == [utt_low])
    assert eng.started == [LOW1]  # parked: chunk 2 never started
    assert not utt_low.finished   # parked is not finished
    assert sp.resume() == 1
    assert sp.postponed == []
    assert sp.resume() == 0       # nothing left to un-park
    eng.wait_started(LOW2)
    eng.allow(4)
    assert utt_low.wait(5)
    assert utt_low.sentence_status == [SPOKEN, SPOKEN]


def test_postpone_non_low_returns_none():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    assert sp.postpone() is None  # idle speaker
    utt = sp.speak("normal item here.", priority=NORMAL)
    eng.wait_started("normal item here.")
    assert sp.postpone() is None  # replies are not parkable
    eng.allow(3)
    assert utt.wait(5)


# --------------------------------------------------------------------------- #
# 4. cancel() — per-class drops, current stop, other classes untouched
# --------------------------------------------------------------------------- #

def test_cancel_queued_class_only():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    holder = "holder speaks now."
    utt_h = sp.speak(holder, priority=NORMAL)
    eng.wait_started(holder)
    low = "low queued item."
    utt_low = sp.speak(low, priority=LOW)
    second = "second normal item."
    utt_2 = sp.speak(second, priority=NORMAL)
    dropped = sp.cancel(LOW)
    assert dropped == [utt_low]
    assert utt_low.finished
    assert utt_low.sentence_status == [SKIPPED]
    eng.allow(3)
    eng.wait_started(second)  # the other class is untouched
    eng.allow(3)
    assert utt_h.wait(5) and utt_2.wait(5)
    assert low not in eng.started


def test_cancel_all_stops_current_and_drops_queues():
    eng = ControlledEngine()
    sp, states = make_speaker(eng)
    cur = "current normal item."
    utt_c = sp.speak(cur, priority=NORMAL)
    eng.wait_started(cur)
    utt_low = sp.speak("queued low item.", priority=LOW)
    utt_n2 = sp.speak("queued normal item.", priority=NORMAL)
    result = []
    t = threading.Thread(target=lambda: result.extend(sp.cancel()))
    t.start()
    wait_for(lambda: sp._stop.is_set())  # the stop flag has landed
    eng.allow(1)  # the engine meets the flag at the next word
    t.join(5)
    assert not t.is_alive()
    assert set(result) == {utt_c, utt_low, utt_n2}
    assert utt_c.sentence_status == [INTERRUPTED]
    assert utt_low.sentence_status == [SKIPPED]
    assert utt_n2.sentence_status == [SKIPPED]
    assert eng.started == [cur]  # nothing queued ever reached the engine
    wait_for(lambda: sp.state == "idle")
    assert states == ["speaking", "idle"]


def test_cancel_other_class_leaves_current_playing():
    eng = ControlledEngine(auto=True)
    sp, _ = make_speaker(eng)
    utt = sp.speak("keep me speaking.", priority=NORMAL)
    assert sp.cancel(URGENT) == []  # nothing of that class exists
    assert utt.wait(5)
    assert utt.sentence_status == [SPOKEN]


# --------------------------------------------------------------------------- #
# 5. key= latest-wins — still-queued only, never the playing item
# --------------------------------------------------------------------------- #

def test_latest_wins_replaces_still_queued():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    holder = "holder speaks now."
    utt_h = sp.speak(holder, priority=NORMAL)
    eng.wait_started(holder)
    v1 = "status version one."
    utt_v1 = sp.speak(v1, priority=LOW, key="status")
    v2 = "status version two."
    utt_v2 = sp.speak(v2, priority=LOW, key="status")
    # The replacement is synchronous with the submission.
    assert utt_v1.finished
    assert utt_v1.sentence_status == [SKIPPED]
    eng.allow(3)
    eng.wait_started(v2)
    eng.allow(3)
    assert utt_h.wait(5) and utt_v2.wait(5)
    assert v1 not in eng.started
    assert eng.finished == [holder, v2]


def test_latest_wins_across_classes():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    holder = "holder speaks now."
    utt_h = sp.speak(holder, priority=NORMAL)
    eng.wait_started(holder)
    utt_v1 = sp.speak("tick version one.", priority=LOW, key="tick")
    utt_v2 = sp.speak("tick version two.", priority=URGENT, key="tick")
    assert utt_v1.finished and utt_v1.sentence_status == [SKIPPED]
    eng.allow(3)
    eng.wait_started("tick version two.")  # and it plays at URGENT's turn
    eng.allow(3)
    assert utt_h.wait(5) and utt_v2.wait(5)


def test_latest_wins_never_replaces_playing():
    eng = ControlledEngine()
    sp, _ = make_speaker(eng)
    v1 = "status playing one."
    utt_v1 = sp.speak(v1, priority=NORMAL, key="status")
    eng.wait_started(v1)
    v2 = "status playing two."
    utt_v2 = sp.speak(v2, priority=NORMAL, key="status")
    assert not utt_v1.finished  # already leaving the speakers: safe
    eng.allow(3)
    eng.wait_finished(v1)
    assert utt_v1.sentence_status == [SPOKEN]  # spoken in full
    eng.wait_started(v2)
    eng.allow(3)
    assert utt_v2.wait(5)
    assert eng.finished == [v1, v2]


# --------------------------------------------------------------------------- #
# 6. Index callbacks — exactly what left the speakers
# --------------------------------------------------------------------------- #

def test_on_spoken_full_completion_trace():
    eng = ControlledEngine(auto=True)
    log, on_spoken = spoken_log()
    sp, _ = make_speaker(eng, on_spoken)
    s1, s2 = "One chunk here.", "Two chunk follows."
    utt = sp.speak(f"{s1} {s2}", priority=NORMAL)
    assert utt.wait(5)
    assert log == [(1, s1), (2, s2)]
    assert [cid for cid, _ in log] == utt.chunk_ids


def test_on_spoken_interruption_trace_shows_exact_stop_point():
    eng = ControlledEngine()
    log, on_spoken = spoken_log()
    sp, _ = make_speaker(eng, on_spoken)
    text = "alpha bravo charlie delta echo."
    utt = sp.speak(text, priority=NORMAL)
    eng.wait_started(text)
    eng.allow(3)  # exactly three words leave the speakers
    wait_for(lambda: utt.words_spoken == 3)
    t = threading.Thread(target=sp.interrupt)
    t.start()
    wait_for(lambda: sp._stop.is_set())  # the stop flag has landed
    eng.allow(1)  # the engine meets the flag at the next word boundary
    t.join(5)
    assert not t.is_alive()
    assert utt.wait(5)
    cid = utt.chunk_ids[0]
    # The callback stream stops exactly where the speakers stopped,
    # and it agrees with the Utterance Record word for word.
    assert log == [(cid, "alpha bravo charlie")]
    assert utt.words_spoken_text() == "alpha bravo charlie"
    assert utt.sentence_status == [INTERRUPTED]
    assert sp.dropped_chunk_ids() == [cid]


def test_on_spoken_silent_when_nothing_left():
    # An item cancelled while queued produces no callback at all:
    # nothing left the speakers, so the stream must say nothing.
    eng = ControlledEngine()
    log, on_spoken = spoken_log()
    sp, _ = make_speaker(eng, on_spoken)
    holder = "holder speaks now."
    utt_h = sp.speak(holder, priority=NORMAL)
    eng.wait_started(holder)
    utt_low = sp.speak("never heard item.", priority=LOW)
    sp.cancel(LOW)
    eng.allow(3)
    assert utt_h.wait(5)
    assert log == [(utt_h.chunk_ids[0], holder)]


# --------------------------------------------------------------------------- #
# 7. Watermark × resume — a postponed item survives a barge-in elsewhere
# --------------------------------------------------------------------------- #

def test_postponed_item_survives_interrupt_via_id_rebuild():
    eng = ControlledEngine()
    log, on_spoken = spoken_log()
    sp, _ = make_speaker(eng, on_spoken)
    utt_low = sp.speak(f"{LOW1} {LOW2}", priority=LOW)
    eng.wait_started(LOW1)
    utt_u = sp.speak(URG, priority=URGENT)
    eng.allow(4)  # LOW chunk 1 completes; LOW is postponed (ids 1,2)
    eng.wait_started(URG)
    frozen_id = utt_low.chunk_ids[1]  # snapshot BEFORE the barge-in
    # Barge-in aimed at the URGENT item: the watermark freezes every
    # id assigned so far — including LOW's still-queued chunk 2.
    t = threading.Thread(target=sp.interrupt)
    t.start()
    wait_for(lambda: sp._stop.is_set())
    eng.allow(1)  # URGENT meets the flag before its first word lands
    t.join(5)
    assert not t.is_alive()
    assert utt_u.sentence_status == [INTERRUPTED]
    assert sp._queue.watermark >= frozen_id  # the freeze really landed
    # LOW resumes anyway: its frozen remainder is rebuilt with a
    # fresh id — the frozen id itself never plays (watermark holds).
    eng.wait_started(LOW2)
    assert utt_low.chunk_ids[1] > frozen_id
    eng.allow(4)
    assert utt_low.wait(5)
    assert utt_low.sentence_status == [SPOKEN, SPOKEN]
    assert log == [(1, LOW1), (utt_low.chunk_ids[1], LOW2)]


# --------------------------------------------------------------------------- #
# 8. Validation
# --------------------------------------------------------------------------- #

def test_unknown_priority_rejected():
    sp, _ = make_speaker(ControlledEngine(auto=True))
    with pytest.raises(ValueError):
        sp.speak("hello there.", priority="loud")
    with pytest.raises(ValueError):
        sp.cancel(priority="loud")
