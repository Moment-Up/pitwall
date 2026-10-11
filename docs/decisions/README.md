# Architecture decision records

### ADR-001 Python 3.12 + uv, single process, threads for ingest (2026-10-10)
Ingest needs ~600 packets/s with <30 us decode each, far below one core. A dedicated UDP thread isolates
capture from event-loop stalls. Multi-process or Rust is not justified yet. 3.12 rather than the system's 3.14
because ML/voice wheels (MLX, ONNX) lag new Python releases.

### ADR-002 Adapters are pure functions of bytes
No sockets, clocks or threads in adapters. The ingest layer owns transport and timestamps. This makes
replay byte-exact and every adapter testable without a game.

### ADR-003 One StructDef drives both decoding and synthetic encoding
Decoders and the synthetic generator share layouts, so they cannot drift. The layouts are machine-checked
against EA's verbatim structs in docs/research (conformance tests).

### ADR-004 Raw capture first (`.pwcap`: zstd stream of timestamped datagrams)
Raw data allows reprocessing with improved parsers and is the basis for the recorded-validation tier.
Block-flushed every second, so a crash loses under 1 s. Truncated files are readable.

### ADR-005 SQLite (WAL) with one writer thread; traces as npz blobs
Single host, single user, ~MB per session. PostgreSQL would add ops cost without benefit. Revisit for
multi-user/cloud.

### ADR-006 Distance-domain comparison; corners from speed minima of median clean laps
Time-domain comparison is meaningless once laps diverge. Speed minima work without official track data and
across games. Segments partition the lap so corner deltas sum to the lap delta. Official corner names will be
an optional overlay (see track-reference research).

### ADR-007 Deterministic coaching; the LLM explains facts and is grounding-checked
The LLM never decides timing or invents numbers. Each answer is validated (numbers must round to cited facts),
retried once, then replaced by a deterministic answer. The app works fully offline from the LLM.

### ADR-008 Synthetic data is labelled at the source and namespaced
Synthetic captures carry `synthetic=true` metadata and a reserved session UID. Their track ids are
`synthetic:*`. This prevents pollution of real track models and false claims of compatibility.

### ADR-009 Svelte 5 + Vite + uPlot dashboard, served by FastAPI
Svelte gives small bundles (54 KB gzipped) and good phone performance. uPlot handles long telemetry traces
at 60 fps. Live data is pulled at 20 Hz so clients cannot backpressure ingest.

### ADR-010 Local Qwen exposed to Claude Code via a read-only MCP server
Claude Code cannot officially run on a local model. MCP tools give Qwen second opinions while Claude keeps
ownership of design and validation. Read-only, loopback-only, and it yields to live race sessions.
