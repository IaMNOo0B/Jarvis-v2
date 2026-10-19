# JARVIS — Everything We Learned, In Simple Words
*All 28 research cycles + scout hunts, one line each. No jargon.*

## Safety (the "don't break things" stuff)
1. **Fault trees** — Listed every way the "are you sure?" button could fail. Found 8 weak spots, each with a fix.
2. **Attack trees** — Same, but from a hacker's view: every way someone could break in.
3. **Threat model** — The full security map: 36 attack ways, 7 holes openly listed, 8 risks accepted with reasons.
4. **SMT/Z3** — A math prover. Useful for exactly one check (skills can't grab extra permissions). Skipped everywhere else.
5. **Program synthesis** — Verdict: skip. Too much machinery, too little gain.
6. **Data classification** — Four labels for your data (public/personal/sensitive/secret). Secrets never leave your machine, ever. Closes 2 open holes.
7. **MCP servers** — A bad server is worse than a bad skill (it's a bad neighbor with a key). Sandboxed, firewalled, quarantined. Skills ship first.

## The Brain (the thinking part)
8. **Underspecification** — When you say something vague: ask if guessing wrong could break something, just do it if harmless.
9. **Asking economics** — The math behind asking: ask when what it gains beats what it costs you. "Delete this file" → always ask.
10. **Brain spec** — The brain judges, code enforces, never the reverse. Three tiers: tiny CPU → 7B graphics card → cloud.
11. **Bayesian experiments** — Fancy math for picking tests. Verdict: just try all 10 options, 2 hours, done.
12. **Causal discovery** — Figuring out WHY something broke. The math needs too much data — instead JARVIS re-runs things in a safe sandbox.
13. **Bounded rationality** — Good-enough decisions fast, not perfect decisions slowly.
14. **Discriminator protocol** — Testing if JARVIS picks the best plan well enough: needs 94% right before we trust it.
15. **Benchmark spec** — The complete test plan for your 2060 graphics card. Ready to run on your PC.

## Voice (the talking part)
16. **Voice loop spec** — No echo (guard built into the speaker), interrupting works without going mute, remembers only words actually spoken.
17. **Reliability spec** — The promises: works 95% of time, never skips your approval, recovers from crash in 60 seconds.

## Memory (the remembering part)
18. **Memory spec** — Two kinds: "what happened" (fades over time) and "what is true" (facts). Web-learned stuff goes to quarantine.
19. **Session store** — The diary that can't be erased: every action recorded, crash → wakes up exactly where it left off.
20. **Claim verification** — Breaking statements into checkable pieces.
21. **Source trust** — Scoring whether a source is lying.
22. **Memory write-gate** — Six gates deciding what gets remembered.
23. **Conflict resolution** — When sources disagree: weigh, check, or honestly say "I can't decide, here are both sides."

## Building it right
24. **Skill system** — A jail with a guest list: declare permissions, get quarantined, circuit breakers, nothing silent.
25. **Setup spec** — One installer, preflight checks, verified downloads, signed updates, zero terminal ever.
26. **Approval UX** — Fewer, sharper questions. Dangerous ones need typed confirmation. Weekly review of auto-approvals.
27. **Chat UI** — Ten brain states shown clearly, every action in a feed with Undo, approvals you can't be tricked by.
28. **PC control** — See first (Windows UI map), click second, verify third. Never click what it hasn't seen.
29. **Proactivity** — Notice things, but show quietly, speak only if summoned. 3 interruptions/day max.
30. **Phone remote** — Your phone is a window, not a root account. Read-only default, dangerous stuff never available remotely.

## The audit
31. **Provenance audit** — Checked my own homework: 2 contradictions fixed, 1 math error corrected (143 not 141), mystery study sourced, ledgers updated.

## Scout's gems (the hunt)
- **Qwen3-ASR** — faster-whisper's successor, Hindi included, streams natively.
- **PersonaPlex-7B** — Listens and speaks at once, butler voice from a 10-second sample.
- **llama-server MCP** — The server runs tools itself; could kill a layer of our code.
- **Kinetic-4B** — Bengaluru LoRA beating Claude at tool-calling; the playbook for our brain.
- **Ternary-Bonsai** — 1-bit 8B model on CPU; graceful degradation when GPU is busy.
- **My_Jarvis (Bangla)** — Code-switched voice peer; patterns transfer to Hinglish.
- **Chatterbox** — The Hindi voice (from the morning hunt).
- **OpenGCUA** — One Python program per step, 53% fewer steps (your "true gem").

## What needs YOU (can't be learned, only decided)
1. Where the phone's read/write line sits
2. Whether the approval PIN is okay
3. How long shared sessions live
4. Your real Hinglish voice messages (for the test set)
5. The 2060 benchmarking weekend (measurements only your PC can give)
6. The final go-ahead to build

## The one-line version
**JARVIS v2 is fully designed on paper: a brain that judges (never enforces), a gate that can't be skipped, memory that can't be poisoned, voice that can't echo, and approvals that can't be faked — with every number awaiting measurement on your 2060 and every build awaiting your word.**
