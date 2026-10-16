#!/usr/bin/env python3
"""External transactional updater for Subtitle Universe Spellcheck.

This module deliberately uses only the Python standard library.  The running
application copies (or freezes) it outside the installation before invoking it,
so the complete application directory can be exchanged and rolled back.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence


class UpdateApplyError(RuntimeError):
    """Raised when an update cannot be completed safely."""


def wait_for_process_exit(process_id: int, timeout: float = 60.0) -> bool:
    """Wait until *process_id* no longer exists without platform dependencies."""
    if process_id <= 0:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        except OSError:
            return True
        time.sleep(0.1)
    return False


def _copy_preserved_path(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)


def _default_process_launcher(command: Sequence[str]) -> object:
    options = {"close_fds": True}
    if os.name == "nt":
        options["creationflags"] = 0x00000008  # DETACHED_PROCESS
    else:
        options["start_new_session"] = True
        options.update(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return subprocess.Popen(list(command), **options)


def _load_plan(plan_path: Path) -> dict:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UpdateApplyError("The update plan could not be read.") from error
    if not isinstance(plan, dict) or plan.get("schema") != 1:
        raise UpdateApplyError("The update plan is not supported.")
    return plan


def apply_update_plan(
    plan_path: Path,
    *,
    wait_for_exit: Callable[[int, float], bool] = wait_for_process_exit,
    command_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    process_launcher: Callable[[Sequence[str]], object] = _default_process_launcher,
) -> None:
    """Apply one staged distribution exchange and roll back on validation failure."""
    plan_path = Path(plan_path).resolve()
    plan = _load_plan(plan_path)
    try:
        installation = Path(plan["installation_root"]).resolve()
        payload = Path(plan["payload_root"]).resolve()
        backup = Path(plan["backup_root"]).resolve()
        wait_pid = int(plan.get("wait_for_pid", 0))
        health_command = [str(part) for part in plan["health_check_command"]]
        expected_output = str(plan["expected_health_output"])
        restart_command = [str(part) for part in plan["restart_command"]]
        rollback_restart = [str(part) for part in plan["rollback_restart_command"]]
        preserve_paths = [Path(str(value)) for value in plan.get("preserve_paths", [])]
        remove_after_success = [
            Path(str(value)).resolve() for value in plan.get("remove_after_success", [])
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise UpdateApplyError("The update plan is incomplete.") from error

    if not installation.is_dir() or not payload.is_dir():
        raise UpdateApplyError("The installed or staged application is missing.")
    if backup.exists():
        raise UpdateApplyError("The update backup location already exists.")
    for relative in preserve_paths:
        if relative.is_absolute() or ".." in relative.parts:
            raise UpdateApplyError("The update plan contains an unsafe preserved path.")
    if not wait_for_exit(wait_pid, 60.0):
        raise UpdateApplyError("The running application did not close in time.")

    exchanged = False
    try:
        installation.rename(backup)
        try:
            payload.rename(installation)
        except Exception:
            backup.rename(installation)
            raise
        exchanged = True
        for relative in preserve_paths:
            _copy_preserved_path(backup / relative, installation / relative)

        completed = command_runner(
            health_command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0 or expected_output not in completed.stdout:
            raise UpdateApplyError("The new application failed its startup validation.")
        process_launcher(restart_command)
    except Exception as error:
        if exchanged:
            failed_installation = installation.with_name(installation.name + ".failed-update")
            try:
                if failed_installation.exists():
                    shutil.rmtree(failed_installation)
                installation.rename(failed_installation)
                backup.rename(installation)
                shutil.rmtree(failed_installation, ignore_errors=True)
                process_launcher(rollback_restart)
            except Exception as rollback_error:
                raise UpdateApplyError(
                    "The update failed and automatic rollback also failed. "
                    f"The previous installation remains at {backup}."
                ) from rollback_error
            raise UpdateApplyError("The update failed and was rolled back.") from error
        if isinstance(error, UpdateApplyError):
            raise
        raise UpdateApplyError("The update could not replace the installation.") from error
    else:
        # The new version is already validated and running.  A locked backup is
        # cleanup debris, not a reason to report the successful exchange as failed.
        shutil.rmtree(backup, ignore_errors=True)
        for temporary_path in remove_after_success:
            shutil.rmtree(temporary_path, ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("Usage: update_helper.py PLAN.json", file=sys.stderr)
        return 2
    try:
        apply_update_plan(Path(arguments[0]))
    except UpdateApplyError as error:
        print(f"Update failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
