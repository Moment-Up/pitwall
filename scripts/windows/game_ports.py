"""Print the UDP ports Pitwall's game integrations listen on, as JSON (for scripts/windows/firewall.ps1).

Run from the repository folder with the project's interpreter (``.venv\\Scripts\\python.exe``) so it sees the same
configuration as the server: ``PITWALL_*`` environment variables, ``.env`` and the Connect page's choices in
``<data dir>/settings.json``. Read-only: it never writes or moves a file. Integrations that bind no port on this PC
(Assetto Corsa: pitwall connects to the game) are left out.

Output: ``[{"key": "f1", "name": "EA SPORTS F1 25", "port": 20777, "enabled": true}, ...]``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pitwall.config import Settings
from pitwall.integrations import SPECS, listens, resolve_configs


def _integrations_section(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    section = data.get("integrations") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def main() -> None:
    settings = Settings()
    configs = resolve_configs(settings, _integrations_section(settings.data_dir / "settings.json"))
    rows = [
        {"key": c.key, "name": SPECS[c.key].name, "port": c.port, "enabled": c.enabled}
        for c in configs.values()
        if listens(c.key)
    ]
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
