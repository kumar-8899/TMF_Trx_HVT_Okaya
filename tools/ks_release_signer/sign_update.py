"""Sign a framework release manifest -> .ksupdate (CI step; SECURE_DISTRIBUTION.md §5-6).

Reads the built artifact's RELEASE.json (version + full_artifact_hash) and mints a
signed Keystation manifest bundle {manifest, intermediate_cert, signature} the station's
core verifies. Serves BOTH tiers (TEMPLATE.md two-tier model): the framework repo mints
a `framework`-track manifest; a derived customer app mints an `app`-track manifest that
pins the framework version it was built against. Signing key material + release shape
come from the environment (GitHub Actions secrets / the app repo's release.yml):

  KS_INTERMEDIATE_SEED    hex 32-byte Ed25519 seed of the intermediate key
  KS_INTERMEDIATE_CERT    the root-signed intermediate cert (JSON) minted at the ceremony
  KS_TRACK                framework | app                 (default framework)
  KS_PINNED_FW_VERSION    framework version this app pins (REQUIRED when KS_TRACK=app)
  KS_PINNED_CORE_VERSION  core version floor              (optional)
  KS_CHANNEL              stable | beta | dev             (default stable)
  KS_MIN_ABI              min core ABI required           (default 1)
  KS_CRITICALITY          optional | recommended | required (default recommended)

Usage:  python sign_update.py <RELEASE.json> <out.ksupdate>

The root private key is NEVER here — the cert is produced offline (root ceremony);
CI only holds the rotatable intermediate seed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.dirname(__file__))
import canonical  # vendored verbatim from the Keystation issuer


def main() -> int:
    release_json, out_path = sys.argv[1], sys.argv[2]
    rel = json.loads(open(release_json, encoding="utf-8").read())

    seed_hex = os.environ["KS_INTERMEDIATE_SEED"].strip()
    cert = json.loads(os.environ["KS_INTERMEDIATE_CERT"])
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))

    full_hash = rel["full_artifact_hash"] if "full_artifact_hash" in rel else \
        _hash_of(rel, release_json)

    track = os.environ.get("KS_TRACK") or rel.get("track") or "framework"
    pinned_fw = os.environ.get("KS_PINNED_FW_VERSION") or rel.get("pinned_fw_version")
    if track == "app" and not pinned_fw:
        raise SystemExit("KS_TRACK=app requires KS_PINNED_FW_VERSION (the framework version pinned)")

    manifest = {
        "release_id": str(uuid.uuid4()),
        "track": track,
        "version": rel["version"],
        "channel": os.environ.get("KS_CHANNEL", "stable"),
        "abi_version": -1,
        "min_abi_required": int(os.environ.get("KS_MIN_ABI", "1")),
        "pinned_core_version": os.environ.get("KS_PINNED_CORE_VERSION"),
        "pinned_fw_version": pinned_fw,
        "full_artifact_hash": full_hash,
        "delta_entries": [],
        "build_timestamp": int(rel.get("built_at", time.time())),
        "sbom_hash": rel.get("sbom_hash") or hashlib.sha256(b"no-sbom").hexdigest(),
        "release_notes_hash": None,
        "criticality": os.environ.get("KS_CRITICALITY", "recommended"),
        "signed_by_key_version": int(cert["key_version"]),
    }
    signature = key.sign(canonical.manifest_signing_bytes(manifest)).hex()
    bundle = {"manifest": manifest, "intermediate_cert": cert, "signature": signature}
    open(out_path, "w", encoding="utf-8").write(json.dumps(bundle, indent=2))
    pin = f", pins fw {pinned_fw}" if pinned_fw else ""
    print(f"signed {out_path}: {track} {manifest['version']}{pin} "
          f"(hash {full_hash[:12]}…, kv {manifest['signed_by_key_version']})")
    return 0


def _hash_of(rel: dict, release_json: str) -> str:
    # RELEASE.json already SHA-256s every file; hash that manifest as the artifact id.
    return hashlib.sha256(open(release_json, "rb").read()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
