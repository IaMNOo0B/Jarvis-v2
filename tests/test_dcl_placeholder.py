"""Tests for the DCL placeholder round-trip (Presidio/LLM-Guard vault
pattern, megascan Team 16 steal #2).

substitute() swaps SECRET/PERSONAL spans for stable placeholders and
keeps the mapping in an in-memory Vault; restore() swaps them back on
the reply path. The raw value must never appear in the clean text, the
same value must always wear the same placeholder, hallucinated
placeholders must pass through (counted, never invented), and the
validate() hook must spare look-alike strings.
"""

from jarvis import dcl as dcl_mod
from jarvis.dcl import (
    DCL,
    DataClass,
    Vault,
    restore,
    substitute,
)

# Real-shaped provider keys (constructed, never real credentials).
GROQ_KEY = "gsk_" + "Ab1" * 17 + "Z"                    # body: 52 alnum
OPENROUTER_KEY = "sk-or-v1-" + "0123456789abcdef" * 4    # body: 64 hex
NVIDIA_KEY = "nvapi-" + "Ab3_" * 11                      # body: 44 token chars
GEMINI_KEY = "AIza" + "aB3-" * 8 + "xY9"                 # 39 chars total
PERPLEXITY_KEY = "pplx-" + "a1B2" * 12                   # body: 48 alnum
XAI_KEY = "xai-" + "Zx9" * 16                            # body: 48 alnum

# Look-alikes: recognizer candidates that the validators must reject.
FAKE_GROQ = "gsk_" + "a" * 10                            # body too short
FAKE_GEMINI = "AIza" + "b" * 20                          # total != 39
FAKE_XAI = "xai-" + "q" * 10                             # body too short
FAKE_OPENROUTER = "sk-or-v1-" + "z" * 8                  # body non-hex, short

EMAIL = "owais.khan@example.com"


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_round_trip_secret():
    text = f"My Groq key is {GROQ_KEY} — do not share it."
    clean, vault = substitute(text)
    assert GROQ_KEY not in clean
    assert "<SECRET_1>" in clean
    assert len(vault) == 1
    # A model-style reply referencing the placeholder restores exactly.
    reply = "I checked <SECRET_1> for you — it is active and valid."
    assert restore(reply, vault) == \
        f"I checked {GROQ_KEY} for you — it is active and valid."
    assert vault.unknown_seen == 0


def test_round_trip_over_running_text_is_exact():
    text = f"groq {GROQ_KEY} and gemini {GEMINI_KEY} end"
    clean, vault = substitute(text)
    assert restore(clean, vault) == text


def test_personal_email_round_trips():
    d = DCL()
    clean, vault = d.substitute(f"Please email me at {EMAIL} tomorrow.")
    assert EMAIL not in clean
    assert vault["<PERSONAL_1>"] == EMAIL
    assert restore(clean, vault) == f"Please email me at {EMAIL} tomorrow."


def test_luhn_card_round_trips():
    text = "card 4111111111111111 on file"
    clean, vault = substitute(text)
    assert "4111111111111111" not in clean
    # The card regex's span also consumes one trailing separator char
    # (pre-existing DCL span behaviour) -- the vault stores the span
    # verbatim, which is what makes the round-trip byte-exact.
    assert vault["<SECRET_1>"].strip() == "4111111111111111"
    assert restore(clean, vault) == text


def test_registered_secret_round_trips():
    d = DCL()
    d.register_secret("vault-word", "Xq7!s3cr3t-value")
    text = "The vault word is Xq7!s3cr3t-value, ok?"
    clean, vault = d.substitute(text)
    assert "Xq7!s3cr3t-value" not in clean
    assert "<SECRET_1>" in clean
    assert restore(clean, vault) == text


# ---------------------------------------------------------------------------
# Dedup + numbering
# ---------------------------------------------------------------------------

def test_same_value_same_placeholder():
    text = f"Key one: {GROQ_KEY}. Again the same key: {GROQ_KEY}."
    clean, vault = substitute(text)
    assert clean.count("<SECRET_1>") == 2
    assert "<SECRET_2>" not in clean
    assert len(vault) == 1


def test_numbering_per_class_in_appearance_order():
    text = f"groq {GROQ_KEY} then gemini {GEMINI_KEY} then mail {EMAIL}"
    clean, vault = substitute(text)
    assert vault["<SECRET_1>"] == GROQ_KEY
    assert vault["<SECRET_2>"] == GEMINI_KEY
    assert vault["<PERSONAL_1>"] == EMAIL


def test_shared_vault_keeps_identity_across_calls():
    vault = Vault()
    clean1, vault = substitute(f"first {GROQ_KEY}", vault)
    clean2, vault = substitute(f"second {GEMINI_KEY} and again {GROQ_KEY}",
                               vault)
    assert "<SECRET_1>" in clean1
    assert "<SECRET_1>" in clean2  # same key -> same placeholder, new call
    assert vault["<SECRET_2>"] == GEMINI_KEY
    assert len(vault) == 2


# ---------------------------------------------------------------------------
# Hallucinated placeholders
# ---------------------------------------------------------------------------

def test_hallucinated_placeholders_pass_through_and_count():
    _, vault = substitute(f"the key is {GROQ_KEY} ok")
    out = restore("Try <SECRET_9> or <PERSONAL_3> instead.", vault)
    assert out == "Try <SECRET_9> or <PERSONAL_3> instead."
    assert vault.unknown_seen == 2
    out2 = restore("Your <SECRET_1> and also <SECRET_9>.", vault)
    assert GROQ_KEY in out2
    assert "<SECRET_9>" in out2
    assert vault.unknown_seen == 3


def test_restore_with_none_vault_is_noop():
    assert restore("has <SECRET_1> inside", None) == "has <SECRET_1> inside"


# ---------------------------------------------------------------------------
# validate() hook -- false-positive control
# ---------------------------------------------------------------------------

def test_all_provider_key_shapes_substitute():
    keys = [GROQ_KEY, OPENROUTER_KEY, NVIDIA_KEY,
            GEMINI_KEY, PERPLEXITY_KEY, XAI_KEY]
    text = " ".join(keys)
    clean, vault = substitute(text)
    for k in keys:
        assert k not in clean
    assert len(vault) == 6
    assert restore(clean, vault) == text


def test_validator_rejects_lookalikes():
    fakes = [FAKE_GROQ, FAKE_GEMINI, FAKE_XAI, FAKE_OPENROUTER]
    text = "notes: " + " ".join(fakes)
    clean, vault = substitute(text)
    assert clean == text
    assert len(vault) == 0


def test_validator_hook_is_what_spares_the_lookalike():
    # The recognizer regex DOES match the fake (it is a candidate);
    # only the attached validate() hook keeps it out of the vault.
    recognizers = {name: (rx, val) for name, rx, val
                   in dcl_mod._PROVIDER_KEY_RECOGNIZERS}
    rx, validate = recognizers["provider-key-groq"]
    assert rx.search(FAKE_GROQ) is not None
    assert validate(FAKE_GROQ) is False
    assert validate(GROQ_KEY) is True
    assert dcl_mod._PATTERN_VALIDATORS["provider-key-groq"] is validate


# ---------------------------------------------------------------------------
# Context boost (substitution path only)
# ---------------------------------------------------------------------------

def test_context_boost_raises_personal_to_secret():
    d = DCL()
    text = f"My password recovery email is {EMAIL}."
    cls, _ = d.classify(text)
    assert cls == DataClass.PERSONAL  # classify() itself is unchanged
    clean, vault = d.substitute(text)
    assert EMAIL not in clean
    assert vault["<SECRET_1>"] == EMAIL  # boosted: SECRET handling


def test_no_label_context_stays_personal():
    d = DCL()
    clean, vault = d.substitute(f"Please email me at {EMAIL} tomorrow.")
    assert vault["<PERSONAL_1>"] == EMAIL
    assert "<SECRET_1>" not in vault


# ---------------------------------------------------------------------------
# Boundaries + hygiene
# ---------------------------------------------------------------------------

def test_sensitive_spans_pass_through_by_design():
    # substitute() vaults SECRET/PERSONAL only (documented scope);
    # SENSITIVE content is redact()'s job, not the vault's.
    text = "Call me on +91 98765 43210 please."
    clean, vault = substitute(text)
    assert "+91 98765 43210" in clean
    assert len(vault) == 0


def test_clean_text_untouched():
    clean, vault = substitute("The weather is nice today.")
    assert clean == "The weather is nice today."
    assert len(vault) == 0
    assert restore("nothing to restore", vault) == "nothing to restore"
    assert vault.unknown_seen == 0


def test_vault_repr_hides_values_and_vault_cannot_persist():
    _, vault = substitute(f"k {GROQ_KEY}")
    assert GROQ_KEY not in repr(vault)
    assert not hasattr(vault, "save")


def test_non_string_input_is_safe():
    clean, vault = substitute(None)
    assert clean is None
    assert len(vault) == 0
