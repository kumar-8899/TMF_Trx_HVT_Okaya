"""Sign a framework release manifest -> .ksupdate (CI step; SECURE_DISTRIBUTION.md §5-6).

Reads the built artifact's RELEASE.json (version + full_artifact_hash) and mints a
signed Keystation manifest bundle {manifest, intermediate_cert, signature} the station's
core verifies. Signing key material comes from the environment (GitHub Actions secrets):

  KS_INTERMEDIATE_SEED   hex 32-byte Ed25519 seed of the intermediate key
  KS_INTERMEDIATE_CERT   the root-signed intermediate cert (JSON) minted at the ceremony
  KS_CHANNEL             stable | beta | dev            (default stable)
  KS_MIN_ABI             min core ABI required          (default 1)
  KS_CRITICALITY         optional | recommended | required (default recommended)

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

    manifest = {
        "release_id": str(uuid.uuid4()),
        "track": "framework",
        "version": rel["version"],
        "channel": os.environ.get("KS_CHANNEL", "stable"),
        "abi_version": -1,
        "min_abi_required": int(os.environ.get("KS_MIN_ABI", "1")),
        "pinned_core_version": None,
        "pinned_fw_version": None,
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
    print(f"signed {out_path}: framework {manifest['version']} "
          f"(hash {full_hash[:12]}…, kv {manifest['signed_by_key_version']})")
    return 0


def _hash_of(rel: dict, release_json: str) -> str:
    # RELEASE.json already SHA-256s every file; hash that manifest as the artifact id.
    return hashlib.sha256(open(release_json, "rb").read()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
