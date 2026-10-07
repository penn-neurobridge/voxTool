"""Push finished annotations to Pennsieve.

Drives the `pennsieve` CLI rather than the REST API. The agent it ships with
already does chunked, resumable uploads and refreshes its own tokens, and it
owns the credentials in ``~/.pennsieve/config.ini`` — so this module never sees
an API key, never stores one, and cannot leak one into a log.

The CLI prints ASCII tables rather than JSON, so the parsing here is
deliberately forgiving: anything unexpected comes back as "could not read"
instead of a wrong answer, because the destination of a patient file is the one
thing that must never be guessed.

Nor can its exit codes be trusted. Every command exits 0 whether or not the
agent refused it, so each step that matters is checked by reading the agent's
state back afterwards rather than by believing the command worked.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

import local_mode

CLI = os.environ.get("VOXTOOL_PENNSIEVE_CLI", "pennsieve")
_TIMEOUT = 60
# How long an upload waits for Pennsieve to confirm the file, in seconds.
UPLOAD_WAIT = 90
_AGENT_DOWN = "unable to connect to pennsieve agent"

# Per-file states in `pennsieve manifest list`.
_SENT = {"UPLOADED", "IMPORTED", "FINALIZED", "VERIFIED"}
_IN_DATASET = {"FINALIZED", "VERIFIED"}
_FAILED = {"FAILED", "REMOVED"}

_MESSAGES = {
    "imported": "Uploaded. Pennsieve has it in the dataset.",
    "sent": (
        "Sent. Pennsieve is still importing it, so it can take a minute to "
        "appear in the dataset."
    ),
    "pending": (
        "Still uploading in the background. Check the dataset in a few minutes "
        "before trying again, or you may end up with two copies."
    ),
}


class PennsieveError(RuntimeError):
    pass


class PennsieveTimeout(PennsieveError):
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
    restricted: bool = False
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
            "restricted": self.restricted,
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
        raise PennsieveTimeout(f"`{CLI} {' '.join(args)}` timed out after {timeout}s.") from e
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


def _message(out: str) -> str:
    """The first line of CLI output worth showing a person."""
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith(("+", "|", "Initializing DB")):
            return line[:200]
    return "no reason given"


def allowed_datasets() -> set[str]:
    """Dataset ids this machine may upload to, from VOXTOOL_PENNSIEVE_DATASETS.

    Comma-separated `N:dataset:` ids; unset means any dataset the account can
    see. While testing it pins uploads to the sandbox, so a wrong pick in the
    dialog cannot reach a real dataset.
    """
    raw = os.environ.get("VOXTOOL_PENNSIEVE_DATASETS", "")
    return {d.strip() for d in raw.split(",") if d.strip()}


def outbox_dir() -> str:
    """Where a file waits while the agent uploads it.

    The agent reads the file in the background after the CLI returns, so it
    has to outlive the request that wrote it.
    """
    path = os.path.join(local_mode.app_data_dir(), "pennsieve-outbox")
    os.makedirs(path, exist_ok=True)
    return path


def is_installed() -> bool:
    return shutil.which(CLI) is not None


def start_agent(wait: int = 15) -> bool:
    """Start the background agent. Returns True once it answers."""
    if not is_installed():
        return False
    # The agent resolves relative paths against its own working directory, so
    # start it somewhere known rather than wherever this process happens to be.
    subprocess.Popen(
        [CLI, "agent"],
        cwd=outbox_dir(),
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


def active_dataset() -> str:
    """The agent's active dataset id, or "" if it has none or cannot say."""
    _, out = _run(["dataset"])
    for cells in _table_rows(out):
        node_id = next((c for c in cells if c.startswith("N:dataset:")), "")
        if node_id:
            return node_id
    return ""


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

    allowed = allowed_datasets()
    st.restricted = bool(allowed)
    code, out = _run(["dataset", "list"])
    if code == 0:
        for cells in _table_rows(out):
            # Skip the header and the single-cell title row.
            if len(cells) < 2 or cells[0].upper() == "NAME":
                continue
            node_id = next((c for c in cells if c.startswith("N:dataset:")), "")
            if node_id and (not allowed or node_id in allowed):
                st.datasets.append({"name": cells[0], "id": node_id})

    st.active_dataset = active_dataset()
    return st


def _first_error(out: str) -> str:
    for line in out.splitlines():
        if line.lower().startswith("error:"):
            return line.split(":", 1)[1].strip()
    return ""


def remote_filename(scan_filename: str, when: float | None = None, ext: str = "json") -> str:
    """`sub-03_ct.nii.gz` -> `sub-03_voxel_coordinates_20260929-1432.json`.

    Naming it after the scan keeps it identifiable whichever way the lab
    organises datasets, and the timestamp means re-annotating never overwrites
    an earlier result. Losing a previous annotation is far worse than having
    two of them. The JSON and TXT of one upload share a stamp, so they pair up.
    """
    base = os.path.basename(scan_filename or "scan")
    for suffix in (".nii.gz", ".nii", ".gz"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    base = re.sub(r"[_-]?ct$", "", base, flags=re.IGNORECASE) or "scan"
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(when or time.time()))
    return f"{base}_voxel_coordinates_{stamp}.{ext}"


def upload(
    local_paths: str | list[str],
    dataset_id: str,
    target_path: str = "",
    dry_run: bool = True,
    wait: float | None = None,
) -> dict:
    """Send files to one folder of a dataset, as a single upload. With dry_run,
    reports the plan and stops.

    `state` in the result says how far the files got: "imported" (all in the
    dataset), "sent" (transferred, Pennsieve still importing) or "pending"
    (still uploading when `wait` ran out; the agent carries on regardless).
    """
    paths = [local_paths] if isinstance(local_paths, str) else list(local_paths)
    if not paths:
        raise PennsieveError("Nothing to upload.")
    for path in paths:
        if not os.path.isfile(path):
            raise PennsieveError(f"Nothing to upload at {path}.")
    if not dataset_id:
        raise PennsieveError("No dataset chosen.")
    allowed = allowed_datasets()
    if allowed and dataset_id not in allowed:
        raise PennsieveError(
            "This machine is set up to upload only to "
            f"{', '.join(sorted(allowed))} (VOXTOOL_PENNSIEVE_DATASETS). "
            "Nothing was sent."
        )

    plan = {
        "file": os.path.basename(paths[0]),
        "files": [os.path.basename(p) for p in paths],
        "bytes": sum(os.path.getsize(p) for p in paths),
        "dataset": dataset_id,
        "target_path": target_path,
        "dry_run": bool(dry_run),
    }
    if dry_run:
        plan["uploaded"] = False
        plan["state"] = "preview"
        plan["message"] = "Dry run — nothing was sent."
        return plan

    _use_dataset(dataset_id)
    manifest_id = _create_manifest(paths, target_path)
    try:
        # Starts the transfer, then waits for the agent to announce that an
        # upload finished — any upload, and possibly never. The manifest is
        # the real record, so stop listening early and read that instead.
        _run(["upload", "manifest", manifest_id], timeout=30)
    except PennsieveTimeout:
        pass
    state = _wait_for_files(manifest_id, len(paths), UPLOAD_WAIT if wait is None else wait)

    plan["uploaded"] = state != "pending"
    plan["state"] = state
    plan["manifest_id"] = manifest_id
    plan["message"] = _MESSAGES[state]
    return plan


def _use_dataset(dataset_id: str) -> None:
    """Make dataset_id the agent's active dataset, and prove it.

    `dataset use` exits 0 even when it refuses ("Unknown Dataset: …"), and a
    manifest binds to whichever dataset is active, so believing it would send
    the file into the previous one — possibly in another workspace.
    """
    _, out = _run(["dataset", "use", dataset_id])
    if active_dataset() != dataset_id:
        raise PennsieveError(
            f"Pennsieve did not switch to that dataset ({_message(out)}), so "
            "nothing was sent. Check that it is in the workspace you are "
            "signed in to."
        )


def _create_manifest(paths: list[str], target_path: str) -> str:
    """One manifest for all the files, each indexed exactly once."""
    target = ["--target_path", target_path] if target_path else []
    # `manifest create` reads only its first path; the rest go in with `add`.
    _, out = _run(["manifest", "create", *target, paths[0]], timeout=120)
    # A failed index still hands back a manifest id, with a different message.
    m = re.search(r"Manifest ID:\s*(\d+)\s+Message:\s*Successfully indexed (\d+) files", out)
    if not m or m.group(2) != "1":
        raise PennsieveError(f"Could not prepare the upload: {_message(out)}")
    manifest_id = m.group(1)
    for path in paths[1:]:
        _, out = _run(["manifest", "add", *target, manifest_id, path], timeout=120)
        # `add` reports "indexed 0 files" rather than an error when it fails.
        if not re.search(r"Successfully indexed 1 files", out):
            raise PennsieveError(
                f"Could not add {os.path.basename(path)} to the upload: {_message(out)}"
            )
    return manifest_id


def _file_statuses(manifest_id: str) -> list[str]:
    """Status of each file in a manifest, as `manifest list` reports them."""
    _, out = _run(["manifest", "list", manifest_id])
    return [
        cells[-1].upper()
        for cells in _table_rows(out)
        if len(cells) >= 3 and cells[0].isdigit()
    ]


def _wait_for_files(manifest_id: str, count: int, seconds: float) -> str:
    """Follow a manifest until all its files are in the dataset or time runs out."""
    deadline = time.monotonic() + seconds
    last_sync = 0.0
    while True:
        states = _file_statuses(manifest_id)
        failed = [s for s in states if s in _FAILED]
        if failed:
            raise PennsieveError(
                f"Pennsieve reported the upload as {failed[0].lower()}. Run "
                f"`pennsieve manifest list {manifest_id}` for details."
            )
        complete = len(states) == count
        if complete and all(s in _IN_DATASET for s in states):
            return "imported"
        all_sent = complete and all(s in _SENT for s in states)
        now = time.monotonic()
        if now >= deadline:
            return "sent" if all_sent else "pending"
        if all_sent and now - last_sync >= 10:
            # Only a sync asks the server whether the import has finished. It
            # also waits on an agent event, so a timeout here is normal.
            last_sync = now
            try:
                _run(["manifest", "sync", manifest_id], timeout=20)
            except PennsieveTimeout:
                pass
            continue
        time.sleep(2)
