"""Un-brickable launcher (UPDATES.md §1-§4) — journal reconcile, backups + DB snapshot,
last-known-good, revert. Drives SwapManager with temp dirs + fake run.dist trees; no
backend, no subprocess."""

import json
from pathlib import Path

import pytest

from launcher import SwapManager, _release_version, _rename_with_retry, _WinJob


def _dist(path, version):
    path.mkdir(parents=True, exist_ok=True)
    (path / "RELEASE.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (path / "run.exe").write_text("bin-" + version, encoding="utf-8")
    return path


def _sm(tmp_path, **kw):
    live = _dist(tmp_path / "run.dist", "1.0.0")
    state = tmp_path / "data"
    state.mkdir()
    db = state / "tmf.sqlite"
    db.write_text("db-v1", encoding="utf-8")
    return SwapManager(live, state, db_files=[db], **kw), live, state, db


# --- swap + backup + db snapshot ------------------------------------------

def test_apply_staged_swaps_with_backup_and_db_snapshot(tmp_path):
    sm, live, state, db = _sm(tmp_path)
    staged = _dist(tmp_path / "staged", "1.1.0")
    assert sm.apply_staged({"staged_dir": str(staged), "version": "1.1.0"}) is True
    assert _release_version(live) == "1.1.0"          # new build is live
    assert not staged.exists()                         # staged consumed
    baks = list((state / "backups").glob("bak-*"))
    assert len(baks) == 1
    assert json.loads((baks[0] / "meta.json").read_text())["version"] == "1.0.0"
    assert (baks[0] / "db-snapshot" / "tmf.sqlite").read_text() == "db-v1"   # OLD db snapshotted
    assert not sm.journal.exists()


# --- journal reconciliation (the un-brickable core) -----------------------

def test_reconcile_completes_forward_when_staged_intact(tmp_path):
    sm, live, state, db = _sm(tmp_path)
    staged = _dist(tmp_path / "staged", "2.0.0")
    backup = state / "backups" / "bak-x"
    (state / "backups").mkdir(parents=True)
    live.rename(backup)                                # simulate crash AFTER live->backup
    sm._write_journal({"step": "backed_up", "staged": str(staged),
                       "backup": str(backup), "live": str(live)})
    assert not live.exists()                           # the danger state
    action = sm.reconcile()
    assert action == "completed" and live.exists() and _release_version(live) == "2.0.0"
    assert not sm.journal.exists()


def test_reconcile_reverses_when_staged_gone(tmp_path):
    sm, live, state, db = _sm(tmp_path)
    backup = state / "backups" / "bak-y"
    (state / "backups").mkdir(parents=True)
    live.rename(backup)
    sm._write_journal({"step": "backed_up", "staged": str(tmp_path / "gone"),
                       "backup": str(backup), "live": str(live)})
    action = sm.reconcile()
    assert action == "reversed" and live.exists() and _release_version(live) == "1.0.0"


def test_reconcile_swapped_just_cleans(tmp_path):
    sm, live, state, db = _sm(tmp_path)
    sm._write_journal({"step": "swapped", "backup": str(state / "backups" / "b"), "live": str(live)})
    assert sm.reconcile() == "cleaned"
    assert live.exists() and not sm.journal.exists()


# --- last known good + revert + db restore --------------------------------

def test_revert_to_last_known_good_restores_binary_and_db(tmp_path):
    sm, live, state, db = _sm(tmp_path)
    sm.mark_last_known_good()                          # snapshot the good 1.0.0 + its db-v1
    # a bad upgrade lands and corrupts the db
    staged = _dist(tmp_path / "staged", "9.9.9-bad")
    sm.apply_staged({"staged_dir": str(staged), "version": "9.9.9-bad"})
    db.write_text("db-v2-corrupt", encoding="utf-8")
    assert _release_version(live) == "9.9.9-bad"
    assert sm.revert_to_last_known_good() is True
    assert _release_version(live) == "1.0.0"           # binary reverted
    assert db.read_text() == "db-v1"                    # db snapshot restored


# --- swap rename resilience + failure breadcrumb -------------------------

def test_rename_with_retry_succeeds_after_a_transient_lock(tmp_path, monkeypatch):
    monkeypatch.setattr("launcher.time.sleep", lambda _s: None)
    src = tmp_path / "a"
    src.mkdir()
    dst = tmp_path / "b"
    real = Path.rename
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError(32, "The process cannot access the file because it is being used")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    _rename_with_retry(src, dst, attempts=5, base_delay=0)
    assert calls["n"] == 3 and dst.exists() and not src.exists()


def test_rename_with_retry_eventually_gives_up(tmp_path, monkeypatch):
    monkeypatch.setattr("launcher.time.sleep", lambda _s: None)
    monkeypatch.setattr(Path, "rename", lambda self, target: (_ for _ in ()).throw(OSError(32, "locked")))
    with pytest.raises(OSError):
        _rename_with_retry(tmp_path / "x", tmp_path / "y", attempts=3, base_delay=0)


def test_apply_staged_records_and_bumps_swap_error_breadcrumb(tmp_path, monkeypatch):
    sm, live, state, db = _sm(tmp_path)
    staged = _dist(tmp_path / "staged", "1.1.0")
    monkeypatch.setattr("launcher.time.sleep", lambda _s: None)
    monkeypatch.setattr(Path, "rename",
                        lambda self, target: (_ for _ in ()).throw(OSError(32, "in use: run.dist")))
    assert sm.apply_staged({"staged_dir": str(staged), "version": "1.1.0"}) is False
    err = json.loads((state / "last_swap_error.json").read_text())
    assert err["version"] == "1.1.0" and err["strikes"] == 1 and "run.dist" in err["error"]
    assert sm.apply_staged({"staged_dir": str(staged), "version": "1.1.0"}) is False
    assert json.loads((state / "last_swap_error.json").read_text())["strikes"] == 2


def test_apply_staged_clears_a_stale_swap_error_on_success(tmp_path):
    sm, live, state, db = _sm(tmp_path)
    (state / "last_swap_error.json").write_text('{"version": "old", "strikes": 2}', encoding="utf-8")
    staged = _dist(tmp_path / "staged", "1.1.0")
    assert sm.apply_staged({"staged_dir": str(staged), "version": "1.1.0"}) is True
    assert not (state / "last_swap_error.json").exists()


def test_winjob_is_safe_to_construct_and_use_everywhere(tmp_path):
    """Real Job Object on Windows, no-op elsewhere — either way it must never raise, even
    handed a bogus process handle, and terminate_and_close must be idempotent."""
    j = _WinJob()
    j.assign(type("P", (), {"_handle": 0})())
    j.terminate_and_close()
    j.terminate_and_close()


def test_prune_keeps_only_n_backups_but_never_lkg(tmp_path):
    sm, live, state, db = _sm(tmp_path, keep_backups=1)
    sm.mark_last_known_good()                           # a protected LKG backup
    for v in ("1.1.0", "1.2.0", "1.3.0"):
        staged = _dist(tmp_path / f"s-{v}", v)
        sm.apply_staged({"staged_dir": str(staged), "version": v})
    lkg_id = json.loads(sm.lkg_ptr.read_text())["backup_id"]
    remaining = {p.name for p in (state / "backups").glob("bak-*") if p.is_dir()}
    assert lkg_id in remaining                          # LKG never evicted
    non_lkg = [n for n in remaining if n != lkg_id]
    assert len(non_lkg) <= 1                            # keep_backups=1 honored
