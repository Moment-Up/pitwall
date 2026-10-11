"""Salsa20/20 stream cipher, implemented from D. J. Bernstein's "Salsa20 specification" (2005).

Gran Turismo 7 encrypts every telemetry datagram with Salsa20/20 (32-byte key, 8-byte nonce, 64-bit block
counter starting at 0). pitwall implements the cipher itself instead of adding a native dependency: the
algorithm is tiny, fully specified, and the spec ships test vectors (see ``tests/unit/test_gt7.py``).

The functions below follow the specification's structure and naming:

* ``quarterround``  - spec section 3, exposed for the spec's test vectors.
* ``salsa20_hash``  - spec section 7: ten double rounds (columnround then rowround) plus the feed-forward
  addition, on a 64-byte input. ``_core`` is the same function unrolled on sixteen local integers.
* ``salsa20_expand`` - spec section 9 (32-byte key form): the 16 input words are
  ``sigma0, k[0:16], sigma1, n[0:16], sigma2, k[16:32], sigma3`` where ``n`` is the 8-byte nonce followed by the
  little-endian 64-bit block counter.
* ``Salsa20.xor`` - spec section 10: ciphertext = plaintext XOR the concatenated expansion outputs for
  counters 0, 1, 2, ... (encryption and decryption are the same operation).

Speed: pure-Python ARX costs ~35 us per 64-byte block, which would be ~0.2 ms per 368-byte GT7 packet. The
blocks of one keystream are independent (they differ only in the counter word), so ``Salsa20.keystream``
computes them together: block ``k``'s word ``i`` occupies bits ``64k .. 64k+31`` of one Python integer, with
32 zero guard bits above it. Every operation in the core is then lane-wise:

* addition: a lane sum is at most 33 bits, the carry lands in that lane's guard bits and the lane mask
  (``0x00000000FFFFFFFF`` repeated) clears it - exactly addition mod 2^32;
* rotation ``((t << c) | (t >> (32 - c))) & lanes`` on a masked ``t``: bits pushed above bit 31 land in the
  guard and are masked off, and bits shifted down out of a lane land in the guard of the lane below - also
  masked off - so each lane rotates independently;
* XOR is bitwise and never crosses lanes.

The same unrolled code therefore computes one block (mask ``0xFFFFFFFF``) or N blocks at once for little more
than the cost of one: ~47 us per 368-byte packet on the M4 Max with CPython 3.12 (4x faster than block by
block), i.e. ~0.3 % of a core at 60 packets/s. Correctness is pinned by the spec's vectors, the eSTREAM set-1
vector and multi-block consistency tests (and was cross-checked against libnettle during development,
including block counters carrying across 2^32).
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

_M = 0xFFFFFFFF
_WORDS = struct.Struct("<16I")
_SIGMA = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)  # "expand 32-byte k" as four LE words
_MAX_LANES = 16  # blocks computed per pass (bounds the size of the packed integers)

KEY_BYTES = 32
NONCE_BYTES = 8
BLOCK_BYTES = 64


def _rotl(v: int, c: int) -> int:
    return ((v << c) & _M) | (v >> (32 - c))


def quarterround(y0: int, y1: int, y2: int, y3: int) -> tuple[int, int, int, int]:
    """Spec section 3: the invertible ARX map on four 32-bit words."""
    z1 = y1 ^ _rotl((y0 + y3) & _M, 7)
    z2 = y2 ^ _rotl((z1 + y0) & _M, 9)
    z3 = y3 ^ _rotl((z2 + z1) & _M, 13)
    z0 = y0 ^ _rotl((z3 + z2) & _M, 18)
    return z0, z1, z2, z3


def _core(w: Sequence[int], m: int) -> tuple[int, ...]:
    """Salsa20 hash on 16 (lane-packed) words: 10 x (columnround, rowround), then add the input word-wise.

    ``m`` is the lane mask: ``0xFFFFFFFF`` for a single block, or that pattern repeated every 64 bits when the
    words carry several blocks side by side (see the module docstring).
    """
    x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15 = w
    for _ in range(10):
        # columnround: quarterround on (y0,y4,y8,y12), (y5,y9,y13,y1), (y10,y14,y2,y6), (y15,y3,y7,y11)
        t = (x0 + x12) & m
        x4 ^= ((t << 7) | (t >> 25)) & m
        t = (x4 + x0) & m
        x8 ^= ((t << 9) | (t >> 23)) & m
        t = (x8 + x4) & m
        x12 ^= ((t << 13) | (t >> 19)) & m
        t = (x12 + x8) & m
        x0 ^= ((t << 18) | (t >> 14)) & m

        t = (x5 + x1) & m
        x9 ^= ((t << 7) | (t >> 25)) & m
        t = (x9 + x5) & m
        x13 ^= ((t << 9) | (t >> 23)) & m
        t = (x13 + x9) & m
        x1 ^= ((t << 13) | (t >> 19)) & m
        t = (x1 + x13) & m
        x5 ^= ((t << 18) | (t >> 14)) & m

        t = (x10 + x6) & m
        x14 ^= ((t << 7) | (t >> 25)) & m
        t = (x14 + x10) & m
        x2 ^= ((t << 9) | (t >> 23)) & m
        t = (x2 + x14) & m
        x6 ^= ((t << 13) | (t >> 19)) & m
        t = (x6 + x2) & m
        x10 ^= ((t << 18) | (t >> 14)) & m

        t = (x15 + x11) & m
        x3 ^= ((t << 7) | (t >> 25)) & m
        t = (x3 + x15) & m
        x7 ^= ((t << 9) | (t >> 23)) & m
        t = (x7 + x3) & m
        x11 ^= ((t << 13) | (t >> 19)) & m
        t = (x11 + x7) & m
        x15 ^= ((t << 18) | (t >> 14)) & m

        # rowround: quarterround on (y0,y1,y2,y3), (y5,y6,y7,y4), (y10,y11,y8,y9), (y15,y12,y13,y14)
        t = (x0 + x3) & m
        x1 ^= ((t << 7) | (t >> 25)) & m
        t = (x1 + x0) & m
        x2 ^= ((t << 9) | (t >> 23)) & m
        t = (x2 + x1) & m
        x3 ^= ((t << 13) | (t >> 19)) & m
        t = (x3 + x2) & m
        x0 ^= ((t << 18) | (t >> 14)) & m

        t = (x5 + x4) & m
        x6 ^= ((t << 7) | (t >> 25)) & m
        t = (x6 + x5) & m
        x7 ^= ((t << 9) | (t >> 23)) & m
        t = (x7 + x6) & m
        x4 ^= ((t << 13) | (t >> 19)) & m
        t = (x4 + x7) & m
        x5 ^= ((t << 18) | (t >> 14)) & m

        t = (x10 + x9) & m
        x11 ^= ((t << 7) | (t >> 25)) & m
        t = (x11 + x10) & m
        x8 ^= ((t << 9) | (t >> 23)) & m
        t = (x8 + x11) & m
        x9 ^= ((t << 13) | (t >> 19)) & m
        t = (x9 + x8) & m
        x10 ^= ((t << 18) | (t >> 14)) & m

        t = (x15 + x14) & m
        x12 ^= ((t << 7) | (t >> 25)) & m
        t = (x12 + x15) & m
        x13 ^= ((t << 9) | (t >> 23)) & m
        t = (x13 + x12) & m
        x14 ^= ((t << 13) | (t >> 19)) & m
        t = (x14 + x13) & m
        x15 ^= ((t << 18) | (t >> 14)) & m
    return (
        (x0 + w[0]) & m,
        (x1 + w[1]) & m,
        (x2 + w[2]) & m,
        (x3 + w[3]) & m,
        (x4 + w[4]) & m,
        (x5 + w[5]) & m,
        (x6 + w[6]) & m,
        (x7 + w[7]) & m,
        (x8 + w[8]) & m,
        (x9 + w[9]) & m,
        (x10 + w[10]) & m,
        (x11 + w[11]) & m,
        (x12 + w[12]) & m,
        (x13 + w[13]) & m,
        (x14 + w[14]) & m,
        (x15 + w[15]) & m,
    )


def salsa20_hash(block: bytes) -> bytes:
    """Spec section 7: the Salsa20 hash function on a 64-byte sequence."""
    if len(block) != BLOCK_BYTES:
        raise ValueError(f"Salsa20 hash input must be {BLOCK_BYTES} bytes, got {len(block)}")
    return _WORDS.pack(*_core(_WORDS.unpack(block), _M))


def salsa20_expand(key: bytes, n: bytes) -> bytes:
    """Spec section 9: Salsa20_k(n) for a 32-byte key ``k`` and a 16-byte ``n`` (nonce || LE counter)."""
    if len(key) != KEY_BYTES or len(n) != 16:
        raise ValueError("Salsa20 expansion needs a 32-byte key and a 16-byte n")
    k = struct.unpack("<8I", key)
    nw = struct.unpack("<4I", n)
    words = (_SIGMA[0], *k[0:4], _SIGMA[1], *nw, _SIGMA[2], *k[4:8], _SIGMA[3])
    return _WORDS.pack(*_core(words, _M))


def _lanes(values: Sequence[int]) -> int:
    """Pack 32-bit ``values`` into consecutive 64-bit lanes of one integer (lane 0 = least significant)."""
    return int.from_bytes(b"".join(struct.pack("<II", v, 0) for v in values), "little")


class Salsa20:
    """Salsa20/20 with a fixed 32-byte key; ``xor`` encrypts or decrypts (the operation is symmetric)."""

    __slots__ = ("_k",)

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError(f"Salsa20 key must be {KEY_BYTES} bytes, got {len(key)}")
        self._k = struct.unpack("<8I", key)

    def keystream(self, nonce: bytes, length: int, counter: int = 0) -> bytes:
        """``length`` keystream bytes for ``nonce``, starting at 64-byte block ``counter``."""
        if len(nonce) != NONCE_BYTES:
            raise ValueError(f"Salsa20 nonce must be {NONCE_BYTES} bytes, got {len(nonce)}")
        if length < 0 or counter < 0:
            raise ValueError("length and counter must be non-negative")
        n0, n1 = struct.unpack("<2I", nonce)
        fixed = (_SIGMA[0], *self._k[0:4], _SIGMA[1], n0, n1, 0, 0, _SIGMA[2], *self._k[4:8], _SIGMA[3])
        out: list[bytes] = []
        remaining = -(-length // BLOCK_BYTES)
        block = counter
        while remaining > 0:
            lanes = min(remaining, _MAX_LANES)
            rep = _lanes([1] * lanes)  # 1 in every lane: multiplying replicates a word into all lanes
            words = [v * rep for v in fixed]
            words[8] = _lanes([(block + j) & _M for j in range(lanes)])  # counter, low word
            words[9] = _lanes([((block + j) >> 32) & _M for j in range(lanes)])  # counter, high word
            packed = [x.to_bytes(8 * lanes, "little") for x in _core(words, _M * rep)]
            # lane j of word i -> bytes 4i..4i+3 of block j
            out.append(b"".join([packed[i][o : o + 4] for o in range(0, 8 * lanes, 8) for i in range(16)]))
            block += lanes
            remaining -= lanes
        return b"".join(out)[:length]

    def xor(self, nonce: bytes, data: bytes, counter: int = 0) -> bytes:
        """Encrypt/decrypt ``data`` (XOR with the keystream for ``nonce`` from block ``counter``)."""
        n = len(data)
        if n == 0:
            return b""
        ks = self.keystream(nonce, n, counter)
        return (int.from_bytes(data, "little") ^ int.from_bytes(ks, "little")).to_bytes(n, "little")
