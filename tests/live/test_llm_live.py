"""Real local-LLM test (opt-in: `uv run pytest -m llm`). Skips if the endpoint is unreachable."""

from __future__ import annotations

import pytest

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.ai.providers import OpenAICompatibleProvider
from pitwall.config import Settings

pytestmark = pytest.mark.llm


async def test_local_llm_answers_from_facts_and_is_grounded() -> None:
    s = Settings()
    p = OpenAICompatibleProvider(s.llm_base_url, s.llm_model, s.llm_api_key, timeout_s=180)
    h = await p.health()
    if not h.ok:
        await p.aclose()
        pytest.skip(f"LLM endpoint unavailable: {h.detail}")
    fs = FactSheet()
    fs.add("session", "Session: F1 25 at Spa, Practice 1, car McLaren, weather clear, track 31 C.")
    fs.add(
        "corners",
        "T5 (right-hander, apex at 2210 m); average time vs reference +0.184s over 4 laps; "
        "brake point on average 14 m earlier than reference; reference brakes at 2050 m lap distance.",
        corner="T5",
    )
    fs.add(
        "observations",
        "Coaching observation (lap 6, confidence 0.95): T5: you're braking about 15 m earlier "
        "than your reference (lap 3), losing 0.19 s through the corner. Seen on 4 of the last 5 laps.",
        corner="T5",
    )
    ans = await RaceEngineer(p, max_tokens=200).answer("Why am I losing time through turn 5?", fs)
    await p.aclose()
    print(f"\n[{ans.latency_ms} ms, attempts={ans.llm_attempts}, fallback={ans.fallback}] {ans.text}")
    assert ans.grounded
    assert not ans.fallback, f"model failed grounding twice: {ans.grounding_issues}"
    assert any(n in ans.text for n in ("14", "15")), "should mention the measured braking delta"
