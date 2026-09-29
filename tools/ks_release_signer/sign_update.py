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
  KS_ARTIFACT_SCOPE       full | app-payload              (default full)

KS_ARTIFACT_SCOPE picks WHICH of RELEASE.json's two hashes becomes the signed
`full_artifact_hash` field — "full" (build_release.py's whole-run.dist zip) or "app-payload"
(package_app_payload_artifact's smaller app/+instrument_libs-only zip, for a release that only
touched app-owned code — docs/decisions/0002-nuitka-compile-scope.md). There is deliberately no
separate "scope" field on the signed manifest: the station DETECTS which kind it received by
inspecting the hash-verified zip's own content (a top-level run.exe means "full") rather than
trusting an out-of-band claim — see core/services/updates.py's _stage_zip_bytes docstring for why
a second, unsigned field here would be a real signature-bypass gap. Whichever scope you sign here,
publish the MATCHING zip (release-build/<slug>-<ver>.zip for full, release-build/<slug>-<ver>-
app-payload.zip for app-payload) as the release's ONE `.zip` asset (UPDATES.md §3: exactly one
`.ksupdate`, exactly one matching `.zip`, standard name — do not publish both for one release).

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

    seed_hex = os.environ.get("KS_INTERMEDIATE_SEED", "").strip()
    if seed_hex:
        cert = json.loads(os.environ["KS_INTERMEDIATE_CERT"])
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))
    else:
        # DEV / pre-Keystation: no ceremony secrets available. Mint an EPHEMERAL self-signed key so
        # the .ksupdate still exists + parses — the stub provider flags it verified:false and a
        # client installs it only with `updates.allow_unverified: true` (DEPLOY_STATION.md). Set the
        # real KS_INTERMEDIATE_SEED/CERT once Keystation is stood up and the same release becomes
        # trusted (no other change). NEVER treat a dev-signed release as trusted.
        print("WARNING: KS_INTERMEDIATE_SEED not set — DEV-signing an UNTRUSTED .ksupdate "
              "(installs only where updates.allow_unverified=true; use Keystation secrets for trust).",
              file=sys.stderr)
        key = Ed25519PrivateKey.generate()
        cert = {"key_version": 0, "dev": True}

    artifact_scope = os.environ.get("KS_ARTIFACT_SCOPE", "full").strip() or "full"
    if artifact_scope not in ("full", "app-payload"):
        raise SystemExit(f"KS_ARTIFACT_SCOPE must be 'full' or 'app-payload', got {artifact_scope!r}")
    hash_key = "app_payload_artifact_hash" if artifact_scope == "app-payload" else "full_artifact_hash"
    if artifact_scope == "app-payload" and not rel.get(hash_key):
        raise SystemExit(
            f"KS_ARTIFACT_SCOPE=app-payload but {release_json} has no '{hash_key}' — "
            "run build_release.py --track app first (package_app_payload_artifact only produces "
            "one when there is app-owned payload to package).")
    full_hash = rel[hash_key] if rel.get(hash_key) else \
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
          f"(scope={artifact_scope}, hash {full_hash[:12]}…, kv {manifest['signed_by_key_version']}) "
          f"— publish the MATCHING zip as this release's one .zip asset")
    return 0


def _hash_of(rel: dict, release_json: str) -> str:
    # RELEASE.json already SHA-256s every file; hash that manifest as the artifact id.
    return hashlib.sha256(open(release_json, "rb").read()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
