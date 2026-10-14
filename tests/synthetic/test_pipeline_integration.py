"""End-to-end synthetic validation: UDP socket -> capture -> decode -> laps -> SQLite -> analysis -> API.

SYNTHETIC: these prove our pipeline against generated packets with known ground truth. They are NOT
evidence that a real console/PC game is compatible (see tests/recorded and tests/live).
"""

from __future__ import annotations

import itertools
import socket
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.ingest.sources import UdpListener
from pitwall.sim.scenarios import write_synthetic_capture
from pitwall.storage import repo
from tests.conftest import DecodedSession

pytestmark = pytest.mark.synthetic


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_udp_listener_receives_records_and_forwards(tmp_path: Path, demo_session: DecodedSession) -> None:
    port = _free_udp_port()
    got: list[CapturedPacket] = []
    lst = UdpListener(port, got.append, bind="127.0.0.1", capture_dir=tmp_path)
    lst.start()
    sent = demo_session.packets[:3000]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
        for i, p in enumerate(sent):
            tx.sendto(p.data, ("127.0.0.1", port))
            if i % 200 == 0:
                time.sleep(0.002)  # stay below the loopback buffer
    deadline = time.time() + 5
    while len(got) < len(sent) and time.time() < deadline:
        time.sleep(0.02)
    lst.stop()
    assert len(got) == len(sent), "packet loss on loopback"
    assert [g.data for g in got] == [p.data for p in sent]
    assert all(b.t_recv_ns >= a.t_recv_ns for a, b in itertools.pairwise(got))
    (cap,) = list(tmp_path.glob("*.pwcap"))
    assert [p.data for p in CaptureReader(cap)] == [p.data for p in sent]


@pytest.fixture
def replayed(tmp_path: Path) -> tuple[Runtime, str]:
    cap = tmp_path / "captures" / "demo.pwcap"
    write_synthetic_capture(cap)
    rt = Runtime(Settings(data_dir=tmp_path, llm_enabled=False))
    r = rt.start_replay(cap, speed=None)
    assert r.done.wait(60)
    rt.worker.join()
    rt.writer.flush()
    with rt.db.read() as c:
        sid = repo.latest_session_id(c)
    assert sid
    yield rt, sid
    rt.close()


def test_replay_persists_session_laps_and_observations(replayed: tuple[Runtime, str]) -> None:
    rt, sid = replayed
    with rt.db.read() as c:
        s = repo.get_session(c, sid)
        laps = repo.list_laps(c, sid)
        obs = repo.list_observations(c, sid)
        events = repo.list_events(c, sid)
        setups = repo.setup_history(c, sid)
    assert s and s["synthetic"] and s["track_id"] == "synthetic:coaching-demo"
    assert s["track_name"] == "Pitwall Park (synthetic)" and s["ended_unix"] is not None
    # the habits demo (sim.scenarios.coaching_demo, learned corner names): lap 5 has a flashback, lap 10 is invalid
    assert [lap["lap_number"] for lap in laps] == list(range(1, 11))
    assert [lap["clean"] for lap in laps] == [True, True, True, True, False, True, True, True, True, False]
    assert "flashback" in laps[4]["flags"] and "invalid" in laps[9]["flags"]
    kinds = sorted((o["lap_number"], o["kind"], o["corner"]) for o in obs)
    assert kinds == sorted(
        [(n, "low_min_speed", "T4") for n in range(2, 11)]  # 9 km/h slow at design-T7 on laps 2-10 (a habit)
        + [(n, "brake_early", "T5") for n in (3, 4, 5)]  # 15 m early into design-T8 on laps 3-5 (a habit, sorted)
        + [(6, "low_min_speed", "T1"), (9, "late_throttle", "T2")]  # a small and a big one-off
    )
    assert {e["kind"] for e in events} >= {"session_started", "flashback", "session_ended"}
    assert len(setups) == 1
    assert rt.worker.errors == 0 and rt.writer.errors == 0


def test_raw_capture_reprocessing_is_deterministic(tmp_path: Path) -> None:
    """Replaying the same raw capture twice yields identical laps (raw data enables reprocessing)."""
    cap = tmp_path / "captures" / "d.pwcap"
    write_synthetic_capture(cap)
    results = []
    for run in range(2):
        rt = Runtime(Settings(data_dir=tmp_path / f"run{run}", llm_enabled=False))
        rt.start_replay(cap, speed=None).done.wait(60)
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            sid = repo.latest_session_id(c)
            assert sid
            results.append([(lap["lap_time_ms"], lap["n_samples"], lap["flags"]) for lap in repo.list_laps(c, sid)])
        rt.close()
    assert results[0] == results[1]


def test_format_2026_end_to_end(tmp_path: Path) -> None:
    from pitwall.sim.scenarios import coaching_demo

    sc = coaching_demo()
    sc.packet_format = 2026
    cap = tmp_path / "captures" / "d2026.pwcap"
    write_synthetic_capture(cap, sc)
    rt = Runtime(Settings(data_dir=tmp_path, llm_enabled=False))
    rt.start_replay(cap, speed=None).done.wait(60)
    rt.worker.join()
    rt.writer.flush()
    with rt.db.read() as c:
        sid = repo.latest_session_id(c)
        assert sid
        obs = repo.list_observations(c, sid)
        info = repo.get_session(c, sid)
    rt.close()
    assert info and info["info"]["packet_format"] == 2026
    assert len(obs) == 14  # as in format 2025 (test_replay_persists_session_laps_and_observations)


# ---------------------------------------------------------------- HTTP API
@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from pitwall.api.app import create_app

    settings = Settings(data_dir=tmp_path, llm_enabled=False, access_token="secret-token")
    cap = settings.capture_dir / "demo.pwcap"
    write_synthetic_capture(cap)
    app = create_app(settings, start_udp=False)
    with TestClient(app) as c:
        rt: Runtime = app.state.runtime
        rt.start_replay(cap, speed=None).done.wait(60)
        rt.worker.join()
        rt.writer.flush()
        yield c


def test_api_end_to_end(client: TestClient) -> None:
    assert client.get("/api/health").json()["laps_processed"] >= 5
    sessions = client.get("/api/sessions").json()
    sid = sessions[0]["id"]
    assert sessions[0]["lap_count"] == 10 and sessions[0]["synthetic"]
    detail = client.get(f"/api/sessions/{sid}").json()
    lap_ids = [lap["id"] for lap in detail["laps"]]
    an = client.get(f"/api/sessions/{sid}/analysis").json()
    assert an["track_model"]["corners"] and an["corner_summary"]
    comp = client.get(f"/api/compare?ref={lap_ids[0]}&lap={lap_ids[2]}").json()
    assert comp["comparison"]["total_delta_s"] == pytest.approx(0.324, abs=0.002)  # lap 3: T5 early and T4 slow
    assert comp["observations"][0]["kind"] == "brake_early"
    trace = client.get(f"/api/laps/{lap_ids[0]}/trace?step=5").json()
    assert len(trace["d"]) == len(trace["speed_kph"]) > 700
    report = client.get(f"/api/sessions/{sid}/report").json()
    assert "SYNTHETIC DATA" in report["markdown"] and "braking about 14 m earlier" in report["markdown"]
    caps = client.get("/api/capabilities").json()
    assert any(r["implemented"] for r in caps) and any(r["status"] == "unsupported" for r in caps)


def test_api_simulate_writes_the_demo_anew_with_what_to_look_for(client: TestClient) -> None:
    """Drive's "Try a demo replay" and Settings › System POST /api/simulate: the capture is written anew with this
    version's scenario (never an older demo left in the folder) and the answer carries its story."""
    from pitwall.sim.scenarios import COACHING_DEMO_STORY

    body = client.post("/api/simulate", json={"scenario": "coaching-demo", "packet_format": 2025}).json()
    assert body["synthetic"] and body["path"].endswith("synthetic-coaching-demo-2025.pwcap")
    assert len(body["lap_times_ms"]) == 10 and body["story"] == COACHING_DEMO_STORY.to_dict()
    meta = CaptureReader(Path(body["path"])).meta
    assert meta.synthetic and meta.extra["story"] == body["story"]
    other = client.post("/api/simulate", json={"scenario": "technique-demo", "packet_format": 2025}).json()
    assert other["story"] is None


def test_api_engineer_deterministic_without_llm(client: TestClient) -> None:
    r = client.post("/api/engineer/ask", json={"question": "Where am I losing the most time?", "use_llm": False})
    body = r.json()
    assert r.status_code == 200 and body["fallback"] and body["grounded"] and "[F" in body["cited_text"]
    assert "[F" not in body["text"] and "confidence" not in body["text"] and body["facts"]  # ids stay internal
    hist = client.get(f"/api/engineer/history?session_id={body['session_id']}").json()
    assert [m["role"] for m in hist][-2:] == ["user", "engineer"]


def test_api_lan_clients_need_token(tmp_path: Path) -> None:
    from pitwall.api.app import create_app

    app = create_app(Settings(data_dir=tmp_path, llm_enabled=False, access_token="tok"), start_udp=False)
    with TestClient(app, client=("192.168.1.50", 50000)) as c:
        assert c.get("/api/health").status_code == 401
        assert c.get("/api/health", headers={"X-Pitwall-Token": "wrong"}).status_code == 401
        ok = c.get("/api/health?token=tok")
        assert ok.status_code == 200 and "pitwall_token" in ok.headers.get("set-cookie", "")
        assert c.get("/api/health").status_code == 200  # cookie now set


def test_api_replay_path_is_confined_to_capture_dir(client: TestClient) -> None:
    r = client.post("/api/replay", json={"path": "/etc/passwd", "speed": None})
    assert r.status_code == 400
