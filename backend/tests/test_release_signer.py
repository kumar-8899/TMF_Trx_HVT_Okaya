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


def _release_json(tmp_path, version="1.2.0"):
    p = tmp_path / "RELEASE.json"
    p.write_text(json.dumps({
        "product": "exeliq.acme_eol", "version": version,
        "full_artifact_hash": hashlib.sha256(b"artifact").hexdigest(),
        "built_at": int(time.time()), "sbom_hash": hashlib.sha256(b"sbom").hexdigest(),
    }), encoding="utf-8")
    return p


def _sign(tmp_path, env_extra) -> dict:
    seed, _pub, cert = _keypair_and_cert()
    env = {**os.environ, "KS_INTERMEDIATE_SEED": seed,
           "KS_INTERMEDIATE_CERT": json.dumps(cert), **env_extra}
    out = tmp_path / "out.ksupdate"
    r = subprocess.run([sys.executable, str(SIGNER / "sign_update.py"),
                        str(_release_json(tmp_path)), str(out)],
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
