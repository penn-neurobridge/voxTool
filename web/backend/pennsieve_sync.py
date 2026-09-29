"""Push finished annotations to Pennsieve.

Drives the `pennsieve` CLI rather than the REST API. The agent it ships with
already does chunked, resumable uploads and refreshes its own tokens, and it
owns the credentials in ``~/.pennsieve/config.ini`` — so this module never sees
an API key, never stores one, and cannot leak one into a log.

The CLI prints ASCII tables rather than JSON, so the parsing here is
deliberately forgiving: anything unexpected comes back as "could not read"
instead of a wrong answer, because the destination of a patient file is the one
thing that must never be guessed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

CLI = os.environ.get("VOXTOOL_PENNSIEVE_CLI", "pennsieve")
_TIMEOUT = 60
_AGENT_DOWN = "unable to connect to pennsieve agent"


class PennsieveError(RuntimeError):
    pass


@dataclass
class Status:
    installed: bool = False
    agent_running: bool = False
    user: str = ""
    workspace: str = ""
    workspace_id: str = ""
    datasets: list[dict] = field(default_factory=list)
    active_dataset: str = ""
    error: str = ""

    def to_json(self) -> dict:
        return {
            "installed": self.installed,
            "agent_running": self.agent_running,
            "user": self.user,
            "workspace": self.workspace,
            "workspace_id": self.workspace_id,
            "datasets": self.datasets,
            "active_dataset": self.active_dataset,
            "error": self.error,
        }


def _run(args: list[str], timeout: int = _TIMEOUT) -> tuple[int, str]:
    """Run the CLI and return (exit code, combined output)."""
    try:
        proc = subprocess.run(
            [CLI, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise PennsieveError("The Pennsieve CLI is not installed on this machine.") from e
    except subprocess.TimeoutExpired as e:
        raise PennsieveError(f"`{CLI} {' '.join(args)}` timed out after {timeout}s.") from e
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _table_rows(output: str) -> list[list[str]]:
    """Pull the cells out of the CLI's ASCII tables."""
    rows = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if any(cells):
            rows.append(cells)
    return rows


def is_installed() -> bool:
    return shutil.which(CLI) is not None


def start_agent(wait: int = 15) -> bool:
    """Start the background agent. Returns True once it answers."""
    if not is_installed():
        return False
    subprocess.Popen(
        [CLI, "agent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(wait):
        code, out = _run(["whoami"], timeout=10)
        if code == 0 and _AGENT_DOWN not in out.lower():
            return True
        time.sleep(1)
    return False


def status(auto_start: bool = False) -> Status:
    st = Status(installed=is_installed())
    if not st.installed:
        st.error = (
            "The Pennsieve CLI was not found. Install it from "
            "docs.pennsieve.io, then sign in with `pennsieve profile create`."
        )
        return st

    code, out = _run(["whoami"])
    if _AGENT_DOWN in out.lower():
        if auto_start and start_agent():
            code, out = _run(["whoami"])
        else:
            st.error = "The Pennsieve agent is not running."
            return st
    if code != 0:
        st.error = _first_error(out) or "Could not read the Pennsieve account."
        return st

    st.agent_running = True
    for cells in _table_rows(out):
        if len(cells) != 2:
            continue
        key, value = cells[0].upper(), cells[1]
        if key == "NAME":
            st.user = value
        elif key == "ORGANIZATION":
            st.workspace = value
        elif key == "ORGANIZATION ID":
            st.workspace_id = value

    code, out = _run(["dataset", "list"])
    if code == 0:
        for cells in _table_rows(out):
            # Skip the header and the single-cell title row.
            if len(cells) < 2 or cells[0].upper() == "NAME":
                continue
            node_id = next((c for c in cells if c.startswith("N:dataset:")), "")
            if node_id:
                st.datasets.append({"name": cells[0], "id": node_id})

    code, out = _run(["dataset"])
    if code == 0:
        for cells in _table_rows(out):
            node_id = next((c for c in cells if c.startswith("N:dataset:")), "")
            if node_id:
                st.active_dataset = node_id
                break
    return st


def _first_error(out: str) -> str:
    for line in out.splitlines():
        if line.lower().startswith("error:"):
            return line.split(":", 1)[1].strip()
    return ""


def remote_filename(scan_filename: str, when: float | None = None) -> str:
    """`sub-03_ct.nii.gz` -> `sub-03_voxel_coordinates_20260929-1432.json`.

    Naming it after the scan keeps it identifiable whichever way the lab
    organises datasets, and the timestamp means re-annotating never overwrites
    an earlier result. Losing a previous annotation is far worse than having
    two of them.
    """
    base = os.path.basename(scan_filename or "scan")
    for suffix in (".nii.gz", ".nii", ".gz"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    base = re.sub(r"[_-]?ct$", "", base, flags=re.IGNORECASE) or "scan"
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(when or time.time()))
    return f"{base}_voxel_coordinates_{stamp}.json"


def upload(
    local_path: str,
    dataset_id: str,
    target_path: str = "",
    dry_run: bool = True,
) -> dict:
    """Send one file to a dataset. With dry_run, reports the plan and stops."""
    if not os.path.isfile(local_path):
        raise PennsieveError(f"Nothing to upload at {local_path}.")
    if not dataset_id:
        raise PennsieveError("No dataset chosen.")

    plan = {
        "file": os.path.basename(local_path),
        "bytes": os.path.getsize(local_path),
        "dataset": dataset_id,
        "target_path": target_path,
        "dry_run": bool(dry_run),
    }
    if dry_run:
        plan["uploaded"] = False
        plan["message"] = "Dry run — nothing was sent."
        return plan

    code, out = _run(["dataset", "use", dataset_id])
    if code != 0:
        raise PennsieveError(_first_error(out) or "Could not select that dataset.")

    args = ["manifest", "create"]
    if target_path:
        args += ["--target_path", target_path]
    args.append(local_path)
    code, out = _run(args, timeout=120)
    if code != 0:
        raise PennsieveError(_first_error(out) or "Could not create the upload manifest.")

    manifest_id = _manifest_id(out)
    if not manifest_id:
        raise PennsieveError(f"Could not read a manifest id from: {out.strip()[:200]}")

    code, out = _run(["upload", "manifest", manifest_id], timeout=600)
    if code != 0:
        raise PennsieveError(_first_error(out) or "The upload failed.")

    plan["uploaded"] = True
    plan["manifest_id"] = manifest_id
    plan["message"] = out.strip()[:400]
    return plan


def _manifest_id(out: str) -> str:
    m = re.search(r"manifest\s*(?:id)?\s*[:=]?\s*(\d+)", out, re.IGNORECASE)
    if m:
        return m.group(1)
    for cells in _table_rows(out):
        for cell in cells:
            if cell.isdigit():
                return cell
    return ""
