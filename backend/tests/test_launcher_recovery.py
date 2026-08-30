"""Un-brickable launcher (UPDATES.md §1-§4) — journal reconcile, backups + DB snapshot,
last-known-good, revert. Drives SwapManager with temp dirs + fake run.dist trees; no
backend, no subprocess."""

import json

from launcher import SwapManager, _release_version


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
