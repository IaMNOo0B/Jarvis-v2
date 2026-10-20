"""Tests for jarvis/golden_pairs.py — correction-to-pair pipeline."""

import pytest

from jarvis.golden_pairs import GoldenPair, PairStore, detect_correction


class TestDetectCorrection:
    def test_plain_correction(self):
        assert detect_correction("no, do it in Hinglish instead") is not None

    def test_hinglish_correction(self):
        assert detect_correction("nahi yaar aisa nahi") is not None

    def test_wrong(self):
        assert detect_correction("that's wrong") is not None

    def test_galat(self):
        assert detect_correction("galat hai ye") is not None

    def test_ordinary_message(self):
        assert detect_correction("what's the weather?") is None

    def test_ordinary_hinglish(self):
        assert detect_correction("bhai ye kya hai") is None


class TestPairStore:
    def test_save_and_load(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(GoldenPair(context="weather", bad_response="formal",
                              good_response="casual Hinglish"))
        pairs = store.all()
        assert len(pairs) == 1
        assert pairs[0].good_response == "casual Hinglish"

    def test_relevant_retrieval(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(GoldenPair(context="weather in Mumbai",
                              bad_response="formal English",
                              good_response="casual Hinglish"))
        store.save(GoldenPair(context="python tutorial",
                              bad_response="textbook",
                              good_response="friendly examples"))
        rel = store.relevant("Mumbai weather today")
        assert len(rel) == 1
        assert "Hinglish" in rel[0].good_response

    def test_format_for_prompt(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(GoldenPair(context="weather", bad_response="x",
                              good_response="y"))
        out = store.format_for_prompt(store.all())
        assert "LEARNED FROM CORRECTIONS" in out
        assert "weather" in out

    def test_empty_store(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        assert store.all() == []
        assert store.relevant("anything") == []
        assert store.format_for_prompt([]) == ""
