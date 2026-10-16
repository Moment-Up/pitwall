"""Assetto Corsa Competizione on a Windows PC: Kunos' shared memory (``Local\\acpmf_physics`` / ``_graphics`` /
``_static``), read on the gaming PC (see ``adapter.py``).

The pages are read by ``pitwall.ingest.acc_shm_reader``, which hands each whole page to the router as a tagged
snapshot (``PHYS`` / ``GRPH`` / ``STAT``, ``packets.py``); this package is the pure decoder.
"""

from pitwall.adapters.acc.adapter import ACC_INFO, AccAdapter
from pitwall.adapters.acc.packets import (
    GRAPHICS_PAGE,
    PAGES,
    PHYSICS_PAGE,
    STATIC_PAGE,
    SYNTHETIC_CAR_MODEL,
    TAG_GRAPHICS,
    TAG_PHYSICS,
    TAG_STATIC,
    AccStatus,
    Page,
)

__all__ = [
    "ACC_INFO",
    "GRAPHICS_PAGE",
    "PAGES",
    "PHYSICS_PAGE",
    "STATIC_PAGE",
    "SYNTHETIC_CAR_MODEL",
    "TAG_GRAPHICS",
    "TAG_PHYSICS",
    "TAG_STATIC",
    "AccAdapter",
    "AccStatus",
    "Page",
]
