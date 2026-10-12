"""Spotter: calls cars alongside in F1 25 races (spoken calls plus iPad bars). No LLM anywhere on this path.

Data path (docs/architecture.md, "Spotter fast path"): the F1 adapter emits one ``FieldMotion`` per Motion packet
(two packet references, no decode); ``SessionManager`` hands it to ``SpotterWorker.submit`` (one ``SimpleQueue.put``);
the worker thread decodes every car (``geometry``), runs the pure ``SpotterEngine`` on the game clock, publishes the
``spotter`` block of the live snapshot and hands its calls to the radio hub (``voice.spotter_radio``), which plays
audio synthesised ahead of time (``voice.spotter_audio``).

Evidence tier: recorded-tested on the owner's PS5 F1 25 races (format 2025), not live-validated; format 2026 is
spec-implemented and synthetic only. Other games send the player's car only, so they can have no spotter.
"""
