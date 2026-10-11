"""``pitwall update`` and the hidden ``pitwall install-finish`` (registered on the main Typer app by ``cli.py``).

Exit codes (the same in install.sh and install.ps1): 0 ok or already up to date, 1 error, 2 usage or unsupported
(a git checkout, an unknown folder, a release older than v0.2.0), 3 telemetry live, 4 needs you (a data conflict,
a running Pitwall in the way, a question with no terminal, low disk), 5 verification failed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from pitwall.install.github import ReleaseInfo

DOCS = "https://github.com/Moment-Up/pitwall/blob/main/docs/install.md#updating"
GIT_DOCS = "https://github.com/Moment-Up/pitwall/blob/main/docs/install.md#a-git-clone"


def _service_mode(service: bool | None) -> str:
    """``pitwall update`` keeps the background service as it is (moves ours to the new version, adds none) unless
    ``--service`` / ``--no-service`` says otherwise. Only the installers ask whether to add one."""
    if service is True:
        return "yes"
    if service is False:
        return "no"
    return "keep"


def _here(root: Path) -> bool:
    try:
        return Path.cwd().resolve() == root.resolve()
    except OSError:
        return False


def _date(published: str | None) -> str:
    if not published:
        return "date unknown"
    try:
        t = time.strptime(published[:10], "%Y-%m-%d")
    except ValueError:
        return published[:10]
    return f"{t.tm_mday} {time.strftime('%b %Y', t)}"


def _print_release(r: ReleaseInfo) -> None:
    typer.echo(f"\nWhat changed in {r.version} ({_date(r.published_at)})")
    if r.notes:
        for n in r.notes:
            typer.echo(f"  - {n}")
    else:
        typer.echo("  (no list of changes in the release notes)")
    typer.echo(f"Full notes: {r.url}")


def register(app: typer.Typer) -> None:
    @app.command("update", rich_help_panel="Install and update")
    def update(
        check: Annotated[bool, typer.Option("--check", help="Only check GitHub for a newer release")] = False,
        as_json: Annotated[bool, typer.Option("--json", help="With --check: print the status as JSON")] = False,
        yes: Annotated[bool, typer.Option("--yes", "-y", help="Answer yes to every question")] = False,
        version: Annotated[str | None, typer.Option("--version", help="Install this release (e.g. v0.2.0)")] = None,
        pre: Annotated[
            bool, typer.Option("--pre", help="Include pre-releases (automatic when this version is one)")
        ] = False,
        service: Annotated[
            bool | None,
            typer.Option(
                "--service/--no-service",
                help="Also start Pitwall at login if it does not yet, or leave the background service on this "
                "version. Default: a background service you use moves to the new version; none is added",
            ),
        ] = None,
        wait_idle: Annotated[
            float, typer.Option("--wait-idle", metavar="MIN", help="Wait up to MIN minutes for telemetry to stop")
        ] = 0.0,
        rollback: Annotated[bool, typer.Option("--rollback", help="Go back to the previous version")] = False,
        no_backup: Annotated[bool, typer.Option("--no-backup", help="Skip the database backup")] = False,
    ) -> None:
        """Update this Pitwall to the latest release (a release folder; a git checkout updates with git pull).

        It checks the download's SHA-256, installs the new version next to this one, backs up the database, keeps
        your data and settings, and restarts the background service if you use one. Never while someone is driving.
        """
        raise typer.Exit(
            run_update(
                check=check,
                as_json=as_json,
                yes=yes,
                version=version,
                pre=pre,
                service=service,
                wait_idle=wait_idle,
                rollback=rollback,
                no_backup=no_backup,
            )
        )

    @app.command("install-finish", hidden=True)
    def install_finish(
        home: Annotated[Path, typer.Option("--home", help="The install folder (e.g. ~/Pitwall)")],
        version_dir: Annotated[Path | None, typer.Option("--version-dir")] = None,
        from_dir: Annotated[Path | None, typer.Option("--from")] = None,
        service: Annotated[str | None, typer.Option("--service", help="yes | no | ask | keep")] = None,
        yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
        wait_idle: Annotated[float, typer.Option("--wait-idle", metavar="MIN")] = 0.0,
        no_backup: Annotated[bool, typer.Option("--no-backup")] = False,
        installer: Annotated[str, typer.Option("--installer")] = "pitwall update",
        rollback: Annotated[bool, typer.Option("--rollback", hidden=True)] = False,
        allow_older: Annotated[bool, typer.Option("--allow-older", hidden=True)] = False,
    ) -> None:
        """Switch the install folder to a staged version (run by install.sh, install.ps1 and pitwall update)."""
        from pitwall.install.activate import FinishOptions, System, finish
        from pitwall.install.versions import code_root

        system = System()
        mode = service or ("ask" if system.has_terminal() else "keep")
        if mode not in ("yes", "no", "ask", "keep"):
            typer.echo("error: --service must be yes, no, ask or keep", err=True)
            raise typer.Exit(2)
        opts = FinishOptions(
            home=home.expanduser(),
            version_dir=(version_dir or code_root()).expanduser(),
            from_dir=from_dir.expanduser() if from_dir else None,
            service=mode,  # type: ignore[arg-type]
            yes=yes,
            wait_idle_min=wait_idle,
            no_backup=no_backup,
            installer=installer,
            rollback=rollback,
            allow_older=allow_older,
        )
        raise typer.Exit(finish(opts, system))


def fetch_and_remember(data_dir: Path) -> list[ReleaseInfo]:
    """GitHub's releases for ``pitwall update``. The answer (or the failure) also refreshes the update cache that
    Settings > System and ``pitwall doctor`` read, so after an update they do not keep showing an older check's
    result (for example a failed one). The cache is only written into a data folder that already exists."""
    from pitwall.install import github
    from pitwall.install.check import run_check

    if not data_dir.is_dir():
        return github.fetch_releases()
    got: list[ReleaseInfo] = []

    def fetch() -> list[ReleaseInfo]:
        got.extend(github.fetch_releases())  # the full list: --version may name one beyond the cached ten
        return got

    cache = run_check(data_dir, fetch)
    if cache.error is not None:
        raise github.ReleaseError(cache.error)
    return got


def run_update(
    *,
    check: bool,
    as_json: bool,
    yes: bool,
    version: str | None,
    pre: bool,
    service: bool | None,
    wait_idle: float,
    rollback: bool,
    no_backup: bool,
) -> int:
    from pitwall.config import get_settings
    from pitwall.install import github
    from pitwall.install.check import compute_status, run_check
    from pitwall.install.layout import (
        EXIT_ERROR,
        EXIT_LIVE,
        EXIT_NEEDS_USER,
        EXIT_OK,
        EXIT_USAGE,
        InstallError,
        install_lock,
        load_state,
        version_dir,
    )
    from pitwall.install.versions import code_root, current_version, install_kind, parse_version, supports_managed

    root = code_root()
    kind = install_kind(root)
    current = current_version(root)
    # Someone on a pre-release follows pre-releases (the same rule as Settings > System's card).
    cur = parse_version(current)
    pre = pre or (cur is not None and cur.is_pre)

    if check:
        s = get_settings()
        cache = run_check(s.data_dir, github.fetch_releases)
        st = compute_status(cache, current=current, kind=kind, mode=s.update_check, root=root, hide_when_off=False)
        if as_json:
            typer.echo(json.dumps(st, indent=2))
        elif cache.error:
            typer.echo(f"Pitwall {current}: {cache.error}", err=True)
        elif st["update_available"]:
            latest = st["latest"]
            typer.echo(f"Pitwall {current}. Latest release: {latest['version']} ({_date(latest['published_at'])})")
            if st["how"]:
                command = st["how"]["command"]
                if kind != "git" and _here(root):  # already in this folder: no `cd` needed
                    command = "uv run pitwall update"
                typer.echo(f"To update: {command}")
        else:
            typer.echo(f"Pitwall {current} is up to date.")
        return EXIT_ERROR if cache.error else EXIT_OK

    if kind == "git":
        typer.echo(  # plan F8: the owner's live install is a release worktree (a git checkout too)
            f"This copy is a git checkout ({root}), so pitwall update doesn't apply. Update it with git pull, then uv "
            f"sync --all-extras, rebuild the dashboard and restart Pitwall; the owner's release worktree is updated by "
            f"scripts/release.sh (into a fresh worktree). See {GIT_DOCS}",
            err=True,
        )
        return EXIT_USAGE
    if kind == "unknown":
        typer.echo(f"{root} is not a Pitwall release folder, so it cannot update itself. See {DOCS}", err=True)
        return EXIT_USAGE

    from pitwall.install.activate import Finisher, FinishOptions, System, finish
    from pitwall.install.layout import env_port
    from pitwall.install.stage import StageDeps, stage_release, venv_bin

    system = System()
    home = root.parent
    state = load_state(home)
    mode = _service_mode(service)

    typer.echo(f"Pitwall {current} (installed in {home})")
    probe = Finisher(FinishOptions(home=home, version_dir=root, wait_idle_min=wait_idle), system)
    port = env_port(root / ".env")
    if probe.is_busy(port) and wait_idle <= 0:
        typer.echo(
            f"A game is sending telemetry to http://127.0.0.1:{port}/, or paused less than 2 minutes ago (someone is "
            "driving): not updating now. Run this again between sessions, or add --wait-idle 120 to wait up to "
            "2 hours.",
            err=True,
        )
        return EXIT_LIVE

    if rollback:
        if state is None or state.previous is None:
            typer.echo("error: there is no previous version to go back to (install.json lists none)", err=True)
            return EXIT_USAGE
        prev = version_dir(home, state.previous)
        if not prev.is_dir():
            typer.echo(f"error: {prev} is gone: cannot go back to {state.previous}", err=True)
            return EXIT_USAGE
        typer.echo(
            f"Going back to {state.previous}. Note: the database may already have newer columns from {current};"
            " older versions normally ignore them."
        )
        backups = sorted((Path(state.data_dir) / "backups").glob("pitwall-before-*.sqlite3"))
        if backups:
            typer.echo(f"Latest database backup: {backups[-1]}")
        return finish(
            FinishOptions(
                home=home,
                version_dir=prev,
                from_dir=root,
                service=mode,  # type: ignore[arg-type]
                yes=yes,
                wait_idle_min=wait_idle,
                no_backup=no_backup,
                installer="pitwall update",
                rollback=True,
            ),
            system,
        )

    try:
        releases = fetch_and_remember(get_settings().data_dir)
        target = github.choose_target(releases, current, pre=pre, pin=version)
    except github.ReleaseError as e:
        typer.echo(f"error: {e}", err=True)
        return EXIT_ERROR
    if target.release is None:
        typer.echo(f"Pitwall {current} is up to date.")
        return EXIT_OK
    tr = target.release
    if not supports_managed(tr.version):
        typer.echo(f"{tr.version} is older than `pitwall update`: install it by hand (docs/install.md).", err=True)
        return EXIT_USAGE
    typer.echo(f"Latest release: {tr.version} ({_date(tr.published_at)})")
    for r in target.newer if not target.downgrade and version is None else [tr]:
        _print_release(r)
    data_note = state.data_dir if state is not None else "your data folder"
    verb = "Go back to" if target.downgrade else "Update to"
    question = f"\n{verb} {tr.version} now? Your sessions and settings stay in {data_note}."
    if not yes:
        answer = system.ask(question)
        if answer is None:
            typer.echo("No terminal to ask in: run it again with --yes.", err=True)
            return EXIT_NEEDS_USER
        if not answer:
            typer.echo("Not updated.")
            return EXIT_OK
    elif target.downgrade:
        typer.echo(f"{tr.version} is older than {current}: going back (--yes).")

    try:
        with install_lock(home):
            new_dir = stage_release(home, tr.version, StageDeps(echo=typer.echo))
    except InstallError as e:
        typer.echo(f"error: {e.message}", err=True)
        return e.code

    cmd = [
        str(venv_bin(new_dir, "pitwall")),
        "install-finish",
        "--home",
        str(home),
        "--version-dir",
        str(new_dir),
        "--from",
        str(root),
        "--service",
        mode,
        "--installer",
        "pitwall update",
    ]
    if yes:
        cmd.append("--yes")
    if target.downgrade:
        cmd.append("--allow-older")  # asked above (or --yes): install-finish does not ask again
    if wait_idle > 0:
        cmd += ["--wait-idle", f"{wait_idle:g}"]
    if no_backup:
        cmd.append("--no-backup")
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    sys.stdout.flush()
    return subprocess.run(cmd, cwd=new_dir, env=env, check=False).returncode
