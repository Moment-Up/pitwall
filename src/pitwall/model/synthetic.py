"""Markers that identify generated (synthetic) telemetry wherever it travels."""

# Every synthetic F1 stream carries this session UID. The session manager flags any session with this UID as
# synthetic, even when it arrives over live UDP, so generated data can never pass as real game data.
SYNTHETIC_SESSION_UID = 0x5EED_0000_0000_0001
