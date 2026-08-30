"""Station launcher — supervises the backend and applies staged updates on relaunch,
un-brickably (UPDATES.md §1-§4, §11 items 1-4).

Loop:  start backend -> gate on /healthz -> on exit 42 apply the staged swap
(journal-first, rename-only) -> restart. A boot that never becomes healthy twice in a
row reverts to the last-known-good build (binary + DB snapshot), tries once more, then
STOPS with a clear message — never an unbounded self-heal loop.

Two invariants make this safe:
  1. **Journal-first, rename-only.** A journal is written before any rename and
     reconciled on every startup, so power loss between `live->backup` and
     `staged->live` can never leave the station with no `run.dist` (UPDATES.md §4).
  2. **Persistent state lives OUTSIDE `live`.** The journal, backups, last-known-good
     pointer and DB snapshots sit beside `run.dist`, never inside it — otherwise a swap
     would move them away with the old tree.

Dev (running `python run.py`, no `run.exe`) -> the swap is a no-op and the launcher
just restarts, which still proves the loop. Frozen (`run.dist/run.exe`) -> the staged
`run.dist` replaces the live one.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

RELAUNCH = 42
STOP_UNRECOVERABLE = 70          # launcher gives up after a bad build it can't recover
HERE = Path(__file__).resolve().parent

# `live` is the tree a swap replaces (run.dist when frozen; the source dir in dev).
LIVE = HERE
FROZEN = (HERE / "run.exe").exists()
# Persistent state (config + data) must survive swapping LIVE, so it sits BESIDE it when
# frozen. STATE_ROOT is the external deploy root handed to the backend as TMF_STATE_DIR so
# both agree on where the DB, marker, backups and live config live.
STATE_ROOT = HERE.parent if FROZEN else HERE
STATE = STATE_ROOT / "data"

MARKER = STATE / "relaunch.json"
LOG = STATE / "launcher.log"
HEALTH_URL = os.environ.get("TMF_HEALTH_URL", "http://127.0.0.1:8000/healthz")
BOOT_TIMEOUT_S = int(os.environ.get("TMF_BOOT_TIMEOUT", "120"))       # UPDATES.md §6
GOOD_AFTER_MIN = float(os.environ.get("TMF_GOOD_AFTER_MIN", "30"))    # earns last_known_good
KEEP_BACKUPS = int(os.environ.get("TMF_KEEP_BACKUPS", "2"))


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} launcher: {msg}"
    print(line, flush=True)
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def backend_cmd() -> list[str]:
    exe = HERE / "run.exe"
    return [str(exe)] if exe.exists() else [sys.executable, str(HERE / "run.py")]


def _release_version(dist: Path) -> str | None:
    rel = dist / "RELEASE.json"
    try:
        return json.loads(rel.read_text(encoding="utf-8")).get("version") if rel.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------- swap core
class SwapManager:
    """Journal-first, rename-only swaps + backups + last-known-good + DB snapshots.

    All paths are injected so this is unit-testable with temp dirs and fake `run.dist`
    trees — no real backend, no subprocess.
    """

    def __init__(self, live: Path, state: Path, *, db_files: list[Path] | None = None,
                 keep_backups: int = KEEP_BACKUPS, clock=time.time) -> None:
        self.live = Path(live)
        self.state = Path(state)
        self.backups = self.state / "backups"
        self.journal = self.state / "swap-journal.json"
        self.lkg_ptr = self.state / "last_known_good.json"
        self.db_files = [Path(p) for p in (db_files or [])]
        self.keep = keep_backups
        self.clock = clock
        self._seq = 0

    def _new_backup_id(self, suffix: str = "") -> str:
        self._seq += 1
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock()))
        return f"bak-{stamp}-{self._seq}{suffix}"

    # -- journal --
    def _write_journal(self, d: dict) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        tmp = self.journal.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(self.journal)   # atomic

    def _clear_journal(self) -> None:
        self.journal.unlink(missing_ok=True)

    def reconcile(self) -> str:
        """Complete or reverse an interrupted swap. Runs at every startup BEFORE the
        backend, so `live` is guaranteed present afterwards. Returns the action taken."""
        if not self.journal.is_file():
            return "none"
        try:
            j = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._clear_journal()
            return "none"
        step = j.get("step")
        backup = Path(j.get("backup", ""))
        staged = Path(j.get("staged", ""))
        action = "cleaned"
        if step == "backed_up":
            # THE danger state: live was moved to backup, staged not yet moved in — live
            # is missing. Complete forward if the staged tree is intact, else reverse.
            if staged.is_dir():
                staged.rename(self.live)
                action = "completed"
            elif backup.is_dir():
                backup.rename(self.live)
                action = "reversed"
            else:
                action = "none"
        elif step == "swapped":
            action = "cleaned"          # swap finished; only the journal lingered
        elif not self.live.exists() and backup.is_dir():
            backup.rename(self.live)    # moves hadn't started but live is somehow gone
            action = "reversed"
        log(f"journal reconcile: {step} -> {action}")
        self._clear_journal()
        return action

    # -- swap --
    def apply_staged(self, marker: dict) -> bool:
        staged = marker.get("staged_dir")
        if not staged:
            log("relaunch with no staged_dir - restart only (dev / no-op swap)")
            return False
        staged_dir = Path(staged)
        if not staged_dir.is_dir():
            log(f"staged dir missing: {staged_dir} - aborting swap, keep current")
            return False
        bid = self._new_backup_id()
        backup = self.backups / bid
        self.backups.mkdir(parents=True, exist_ok=True)
        self._write_journal({"step": "journaled", "staged": str(staged_dir), "backup": str(backup),
                             "live": str(self.live), "version": marker.get("version"),
                             "started_at": self.clock()})
        try:
            self.live.rename(backup)                         # 1. live -> backup (atomic)
            self._write_journal({"step": "backed_up", "staged": str(staged_dir),
                                 "backup": str(backup), "live": str(self.live)})
            staged_dir.rename(self.live)                     # 2. staged -> live (atomic)
            self._write_journal({"step": "swapped", "backup": str(backup), "live": str(self.live)})
        except OSError as exc:
            log(f"swap FAILED: {exc} - reconciling")
            self.reconcile()
            return False
        self._write_backup_meta(backup, _release_version(backup))   # + DB snapshot of the OLD build
        self._clear_journal()
        self._prune()
        log(f"swap done -> {_release_version(self.live)}; backup {bid}")
        return True

    def _write_backup_meta(self, backup: Path, version: str | None) -> None:
        db_dir = backup / "db-snapshot"
        db_dir.mkdir(parents=True, exist_ok=True)
        for f in self.db_files:                              # copy WHILE the backend is DOWN
            if f.is_file():
                shutil.copy2(f, db_dir / f.name)
        meta = {"backup_id": backup.name, "version": version, "installed_at": self.clock(),
                "last_known_good": False, "db_snapshot": str(db_dir)}
        (backup / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def _prune(self) -> None:
        """Keep the newest `keep` backups; NEVER evict the last-known-good."""
        lkg = self._lkg_id()
        baks = sorted([p for p in self.backups.glob("bak-*") if p.is_dir()],
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for old in baks[self.keep:]:
            if old.name != lkg:
                shutil.rmtree(old, ignore_errors=True)

    # -- last known good --
    def _lkg_id(self) -> str | None:
        try:
            return json.loads(self.lkg_ptr.read_text(encoding="utf-8")).get("backup_id")
        except (OSError, json.JSONDecodeError):
            return None

    def mark_last_known_good(self) -> None:
        """The CURRENT live build is a good rollback target: snapshot it as a backup and
        point last_known_good at it (earned after sustained healthy uptime)."""
        bid = self._new_backup_id("-lkg")
        backup = self.backups / bid
        if backup.exists():
            return
        self.backups.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(self.live, backup)
        except (OSError, shutil.Error) as exc:
            log(f"last_known_good snapshot skipped: {exc}")
            return
        self._write_backup_meta(backup, _release_version(self.live))
        self.lkg_ptr.write_text(json.dumps({"backup_id": bid, "version": _release_version(self.live),
                                            "marked_at": self.clock()}), encoding="utf-8")
        log(f"last_known_good = {bid} ({_release_version(self.live)})")
        self._prune()

    def revert_to_last_known_good(self) -> bool:
        bid = self._lkg_id()
        if not bid:
            log("no last_known_good to revert to")
            return False
        return self.revert_to(bid)

    def revert_to(self, backup_id: str) -> bool:
        backup = self.backups / backup_id
        if not backup.is_dir():
            log(f"revert target missing: {backup_id}")
            return False
        # journal the reverse swap too, so a crash mid-revert is still reconcilable.
        self._write_journal({"step": "journaled", "staged": str(backup), "backup": str(self.live),
                             "live": str(self.live), "revert": True, "started_at": self.clock()})
        aside = self.backups / f"{self.live.name}.replaced-{int(self.clock())}"
        try:
            self.live.rename(aside)
            self._write_journal({"step": "backed_up", "staged": str(backup), "backup": str(aside),
                                 "live": str(self.live)})
            shutil.copytree(backup, self.live)               # copy LKG in (keep the backup)
            self._write_journal({"step": "swapped", "backup": str(aside), "live": str(self.live)})
            self._restore_db_snapshot(backup)
        except (OSError, shutil.Error) as exc:
            log(f"revert FAILED: {exc} - reconciling")
            self.reconcile()
            return False
        shutil.rmtree(aside, ignore_errors=True)
        self._clear_journal()
        log(f"reverted to {backup_id} ({_release_version(self.live)})")
        return True

    def _restore_db_snapshot(self, backup: Path) -> None:
        db_dir = backup / "db-snapshot"
        if not db_dir.is_dir():
            return
        for f in self.db_files:
            snap = db_dir / f.name
            if snap.is_file():
                f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snap, f)


# --------------------------------------------------------------------------- boot gate
def _await_boot(proc: subprocess.Popen) -> bool:
    """True once /healthz returns 200; False if the backend exits first or times out."""
    deadline = time.time() + BOOT_TIMEOUT_S
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=3) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(1)
    return False


def _db_files() -> list[Path]:
    """The DB file(s) to snapshot — the single sqlite file plus its WAL sidecars."""
    base = Path(os.environ.get("TMF_DB_PATH", STATE / "tmf.sqlite"))
    return [base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")]


def _shield_break() -> None:
    """Survive the CTRL_BREAK station.py sends to stop the windowed app (the backend
    child gets it too and shuts down gracefully; shielding keeps the launcher alive to
    observe that clean exit). SIGINT (dev Ctrl-C) is untouched."""
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        try:
            signal.signal(sigbreak, lambda *_: None)
        except (ValueError, OSError):
            pass


def main() -> int:
    log(f"launcher up ({'frozen' if FROZEN else 'source'}); state={STATE}")
    _shield_break()
    swap = SwapManager(LIVE, STATE, db_files=_db_files())
    swap.reconcile()                       # finish/undo any interrupted swap BEFORE booting

    strikes = 0
    reverted = False
    child_env = {**os.environ, "TMF_STATE_DIR": str(STATE_ROOT)}   # external config+data
    while True:
        proc = subprocess.Popen(backend_cmd(), cwd=str(HERE), env=child_env)
        log(f"backend started pid={proc.pid}")
        healthy = _await_boot(proc)
        lkg_timer: threading.Timer | None = None
        if healthy:
            strikes, reverted = 0, False
            # Earn last_known_good after sustained uptime (not "completed a run"), so an
            # idle station over a weekend can still mark a good build.
            lkg_timer = threading.Timer(GOOD_AFTER_MIN * 60,
                                        lambda: proc.poll() is None and swap.mark_last_known_good())
            lkg_timer.daemon = True
            lkg_timer.start()
        rc = proc.wait()
        if lkg_timer is not None:
            lkg_timer.cancel()
        log(f"backend exited rc={rc} (healthy_boot={healthy})")

        if not healthy:
            strikes += 1
            log(f"failed boot (strike {strikes}/2)")
            if strikes >= 2:
                if not reverted and swap.revert_to_last_known_good():
                    reverted, strikes = True, 0      # give the reverted build ONE more try
                    continue
                log("UNRECOVERABLE: two bad boots and no healthy fallback — stopping. "
                    "A person must fix the build/config on this bench.")
                return STOP_UNRECOVERABLE
            continue                                 # retry the same build once more

        if rc != RELAUNCH:
            log("normal exit - launcher stopping")
            return rc

        if not MARKER.is_file():
            log("relaunch code but no marker - restart as-is")
            continue
        marker = json.loads(MARKER.read_text(encoding="utf-8"))
        if marker.get("rollback"):
            # local-backup revert — no re-ingest, so the anti-rollback tripwire is bypassed
            done = swap.revert_to(marker["rollback"])
            MARKER.unlink(missing_ok=True)
            log(f"rollback to {marker['rollback']} (done={done})")
        else:
            swapped = swap.apply_staged(marker)
            MARKER.unlink(missing_ok=True)
            log(f"relaunching for {marker.get('version', '?')} (swapped={swapped})")


if __name__ == "__main__":
    raise SystemExit(main())
