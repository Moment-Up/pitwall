"""Installs and updates of release folders: the one-line installers' Python half and ``pitwall update``.

Layout on disk (docs/install.md "Install with one command")::

    <home>/                     ~/Pitwall (macOS, Linux) or %LOCALAPPDATA%\\Pitwall (Windows)
      install.json              written only by the installers and ``pitwall update`` (layout.InstallState)
      data/                     PITWALL_DATA_DIR: never deleted, moved or merged by an update
      pitwall-v0.2.0/           an unzipped release with its own .venv, .env and .pitwall-ready marker
      pitwall-v0.1.0/           the previous version, kept (never deleted automatically)
      .install.lock/            a mkdir lock shared by install.sh, install.ps1 and Python

Modules:

- ``versions``  tags, SemVer ordering, the running version and what kind of folder the code runs from
- ``github``    the GitHub Releases API (one GET, no token), release notes, choosing the target
- ``layout``    install.json, the lock, ``.env`` editing, disk space
- ``stage``     download, SHA-256, safe unzip, ``uv sync``, the ``.pitwall-ready`` marker
- ``activate``  ``pitwall install-finish``: data folder, backup, ``.env``, background service, install.json
- ``check``     the update-status cache behind ``/api/update``, Settings > System and ``pitwall doctor``
- ``commands``  the Typer commands ``pitwall update`` and the hidden ``pitwall install-finish``

Nothing here runs on the ingest path, and nothing contacts the network unless a person asks (a command, "Check now"
in the dashboard's Settings > System, or opening that page with ``PITWALL_UPDATE_CHECK=auto``; the default is
``manual``).
"""
