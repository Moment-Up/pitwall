"""Gran Turismo 7 Simulator Interface adapter (encrypted UDP, community-documented protocol).

See docs/research/gt7-protocol.md. ``packets`` holds the byte layouts and Salsa20 framing, ``adapter`` the
normalisation and the derived lap distance / lap completion / track identity, ``salsa20`` the cipher.
"""

from pitwall.adapters.gt7.adapter import GT7_INFO, GT7Adapter, TrackSignature

__all__ = ["GT7_INFO", "GT7Adapter", "TrackSignature"]
