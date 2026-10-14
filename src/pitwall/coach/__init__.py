"""In-lap coaching: deterministic, time-critical driver cues (no LLM anywhere in this package).

``cues`` turns the driver's own reference lap into live braking calls and corner reminders (for the habits
``habits`` tracks) that are timed against measured audio latency. Post-lap coaching (observations, lap summaries)
lives in ``analysis.coaching`` and ``voice.proactive``.
"""
