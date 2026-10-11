# F1 25 MotionEx: units and signs measured on real recordings

Research date: 2026-10-11 (branch `feat/technique`). EA's spec (`docs/research/f1-udp-spec.md` §5.13) gives units for
local velocity, angular velocity and the chassis angles, but not for wheel slip ratio, wheel slip angle or wheel
speed. Pitwall decodes four MotionEx quantities for the player car (`adapters/f1/adapter.py`, `_on_motion_ex`) and
this note records what the real game sends. It is kept out of `f1-udp-spec.md` because `test_f1_protocol` parses
that file.

Evidence tier: **recorded** (real PS5 captures, F1 25 v1.26, UDP format 2025). Nothing here is live-validated.
Format 2026 sends the same 273-byte struct per EA's 2026 spec; that is spec-implemented only.

## Captures

| Capture | Use | Committed |
|---|---|---|
| `tests/fixtures/recorded/f1_25_2025_ps5_monza_race-excerpt.pwcap` | race lap 3, 560-2250 m: 1940 MotionEx and 1940 Motion packets, 59.9 Hz, same frame ids | yes |
| `tests/fixtures/recorded/f1_25_2025_ps5_austria_race-excerpt.pwcap` | start, lap changes, finish: 2224 each | yes |
| Owner's Miami race (`data/captures/20261011-010607`) | 18148 MotionEx, one session UID | no (other players' names) |
| Owner's Silverstone Reverse race (`20261010-205449`) | balance thresholds | no |

## Findings

| Quantity | Finding | How it was measured |
|---|---|---|
| Rate and pairing | MotionEx arrives with every Motion packet: same `frameIdentifier`, same session UID | packet counts per capture |
| `angularVelocityY` | Yaw rate in rad/s, exactly d(yaw)/dt; **negative turning right**. Pitwall stores `yaw_rate_rps = -angularVelocityY` so that + = right, the sign of the steering | corr and ratio 1.000 with the differentiated `Motion.yaw` (Monza, Austria); corr with steering -0.94 Monza, -0.69 Austria, -0.93 Silverstone Reverse; sign agreement 0.99 / 0.87 / 0.997 |
| `wheelSlipRatio` | Unitless, (wheel - car speed) / car speed: **negative under braking, positive with wheelspin** | fronts under brake >= 0.8: median -0.04 in every capture; rears at full throttle below 150 km/h +0.06 to +0.12; +0.76 at the Austria standing start. With ABS on, a front never went below -0.18 |
| `wheelSlipAngle` | Radians, per wheel (typically within +/-0.13) | fit on Monza: rear = beta - 1.66 r/v, front = beta + 2.09 r/v + delta (R^2 >= 0.97), i.e. a wheelbase of about 3.75 m |
| `chassisYaw` | Body slip angle in radians: atan2(`localVelocityX`, `localVelocityZ`) | 99th percentile of the difference below 1e-3 rad over Monza (float32 rounding) |
| `wheelSpeed` | m/s | wheel speed / car speed: 1.00 fronts, 1.02 rears |
| `frontWheelsAngle` | radians, about 0.30-0.34 x steering | not used by pitwall yet |

### The sign of the body slip tells a slide from a slow turn

`chassisYaw` has a magnitude that is not enough on its own. At Monza's second Rettifilo apex the car slowed to
28 km/h on near-full lock and the body slip reached **8.1 degrees** with the rear slip angle at 0.5 degrees: the
normal (kinematic) slip of a slow, tight turn, not a slide. There the body slip has the **opposite** sign to
`yaw_rate_rps` (all 77 samples above 4 degrees). The real slides in the Austria excerpt (lap 1 at 174-179 km/h and
202-205 km/h, lap 3 at 154-160 km/h; 5.4 to 6.7 degrees, the rear slip angle above the front, the driver
counter-steering) have the **same** sign as `yaw_rate_rps`. `technique.balance` therefore counts a slide only when
the body slip points tail out (same sign as the rotation), or on a counter-steer run.

### Assists seen

ABS was on in every real capture; traction control full (Miami, Silverstone Reverse, Monza) or medium (Austria);
the session's braking assist was 2 (medium). Lock-up detection is therefore validated on synthetic data only.

## Lap distance and positions (racing line)

* F1 positions are precise: lap-to-lap lateral noise std 0.04 m; same-driver laps differ by a median of 0.7-0.9 m,
  90th percentile 2.3-2.8 m, maximum about 6 m.
* Re-measured with `technique.line` (2026-10-11, scratch replay): Miami laps 1-2 against lap 3, whole-lap median
  |offset| 0.92 / 0.95 m, maximum 5.8 / 6.5 m; Silverstone Reverse 0.75 / 0.67 m; GT7 (owner's capture, "Unidentified
  GT7 circuit 3.80 km", derived lap distance) 0.45 / 0.79 m.

## Scripts

The design scripts lived in the session scratch folder (not committed): `frames.py` (joins Motion, MotionEx,
CarTelemetry and LapData per frame), `decode_motionex.py`, `signcheck.py`, `spin.py`, `line_proto.py`,
`line_drift.py`, `balance_final.py` and `inputs_proto.py`. The committed checks are
`tests/recorded/test_technique_recorded.py` (signs, units, the slow-turn body slip and the Austria slides).
