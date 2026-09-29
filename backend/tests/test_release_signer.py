"""ks_release_signer — app-track signing (secure distribution P-b1, two-tier model).

Proves the vendored signer mints both framework- and app-track manifests and that the
signature is valid over the byte-exact canonical form (so the station's Rust core
accepts it). No DLL needed: verify the Ed25519 signature here with `cryptography`.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

REPO = Path(__file__).resolve().parents[2]
SIGNER = REPO / "tools" / "ks_release_signer"
sys.path.insert(0, str(SIGNER))
import canonical  # vendored verbatim from the Keystation issuer


def _keypair_and_cert():
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes_raw().hex()
    pub = key.public_key().public_bytes_raw().hex()
    now = int(time.time())
    cert = {"pubkey": pub, "key_version": 1, "valid_from": now - 86400,
            "valid_until": now + 86400, "signed_by_reserve": False, "signature": ""}
    return seed, pub, cert


def _release_json(tmp_path, version="1.2.0", app_payload_hash=None):
    data = {
        "product": "exeliq.acme_eol", "version": version,
        "full_artifact_hash": hashlib.sha256(b"artifact").hexdigest(),
        "built_at": int(time.time()), "sbom_hash": hashlib.sha256(b"sbom").hexdigest(),
    }
    if app_payload_hash:
        data["app_payload_artifact_hash"] = app_payload_hash
    p = tmp_path / "RELEASE.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _sign(tmp_path, env_extra, *, app_payload_hash=None) -> dict:
    seed, _pub, cert = _keypair_and_cert()
    env = {**os.environ, "KS_INTERMEDIATE_SEED": seed,
           "KS_INTERMEDIATE_CERT": json.dumps(cert), **env_extra}
    out = tmp_path / "out.ksupdate"
    r = subprocess.run([sys.executable, str(SIGNER / "sign_update.py"),
                        str(_release_json(tmp_path, app_payload_hash=app_payload_hash)), str(out)],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return json.loads(out.read_text())


def _verify(bundle) -> bool:
    m, cert, sig = bundle["manifest"], bundle["intermediate_cert"], bundle["signature"]
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(cert["pubkey"]))
    try:
        pub.verify(bytes.fromhex(sig), canonical.manifest_signing_bytes(m))
        return True
    except Exception:  # noqa: BLE001
        return False


def test_framework_track_default(tmp_path):
    b = _sign(tmp_path, {})
    assert b["manifest"]["track"] == "framework"
    assert b["manifest"]["pinned_fw_version"] is None
    assert _verify(b), "framework manifest signature must verify byte-exact"


def test_app_track_pins_framework(tmp_path):
    b = _sign(tmp_path, {"KS_TRACK": "app", "KS_PINNED_FW_VERSION": "1.1.0"})
    m = b["manifest"]
    assert m["track"] == "app" and m["pinned_fw_version"] == "1.1.0"
    assert _verify(b), "app manifest signature must verify byte-exact"


def test_app_track_requires_pin(tmp_path):
    seed, _pub, cert = _keypair_and_cert()
    env = {**os.environ, "KS_INTERMEDIATE_SEED": seed,
           "KS_INTERMEDIATE_CERT": json.dumps(cert), "KS_TRACK": "app"}
    r = subprocess.run([sys.executable, str(SIGNER / "sign_update.py"),
                        str(_release_json(tmp_path)), str(tmp_path / "x.ksupdate")],
                       env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "KS_PINNED_FW_VERSION" in (r.stderr + r.stdout)


def test_tamper_breaks_signature(tmp_path):
    b = _sign(tmp_path, {"KS_TRACK": "app", "KS_PINNED_FW_VERSION": "1.1.0"})
    b["manifest"]["version"] = "9.9.9"
    assert not _verify(b), "a modified manifest must fail verification"


# --- KS_ARTIFACT_SCOPE: which of RELEASE.json's two hashes gets signed --------------------------
# The signed manifest itself never carries a "scope" field (see updates.py's _stage_zip_bytes
# docstring for why: manifest_signing_bytes() mirrors a FIXED Rust struct, so any extra Python
# dict key rides along UNSIGNED — a real signature-bypass gap). The station instead detects scope
# from the hash-verified zip's own content. These tests lock in the signing-time half of that.

def test_default_scope_signs_the_full_artifact_hash(tmp_path):
    b = _sign(tmp_path, {})
    assert b["manifest"]["full_artifact_hash"] == hashlib.sha256(b"artifact").hexdigest()
    assert "scope" not in b["manifest"]           # never a field on the signed manifest
    assert _verify(b)


def test_app_payload_scope_signs_the_app_payload_hash_instead(tmp_path):
    payload_hash = hashlib.sha256(b"app-payload-artifact").hexdigest()
    b = _sign(tmp_path, {"KS_ARTIFACT_SCOPE": "app-payload"}, app_payload_hash=payload_hash)
    assert b["manifest"]["full_artifact_hash"] == payload_hash    # same signed FIELD, different SOURCE
    assert b["manifest"]["full_artifact_hash"] != hashlib.sha256(b"artifact").hexdigest()
    assert "scope" not in b["manifest"]
    assert _verify(b), "app-payload-scope manifest signature must still verify byte-exact"


def test_app_payload_scope_requires_the_hash_to_exist(tmp_path):
    seed, _pub, cert = _keypair_and_cert()
    env = {**os.environ, "KS_INTERMEDIATE_SEED": seed, "KS_INTERMEDIATE_CERT": json.dumps(cert),
           "KS_ARTIFACT_SCOPE": "app-payload"}
    r = subprocess.run([sys.executable, str(SIGNER / "sign_update.py"),
                        str(_release_json(tmp_path)),                 # no app_payload_artifact_hash
                        str(tmp_path / "x.ksupdate")],
                       env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "app_payload_artifact_hash" in (r.stderr + r.stdout)


def test_invalid_artifact_scope_rejected(tmp_path):
    seed, _pub, cert = _keypair_and_cert()
    env = {**os.environ, "KS_INTERMEDIATE_SEED": seed, "KS_INTERMEDIATE_CERT": json.dumps(cert),
           "KS_ARTIFACT_SCOPE": "bogus"}
    r = subprocess.run([sys.executable, str(SIGNER / "sign_update.py"),
                        str(_release_json(tmp_path)), str(tmp_path / "x.ksupdate")],
                       env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "KS_ARTIFACT_SCOPE" in (r.stderr + r.stdout)
