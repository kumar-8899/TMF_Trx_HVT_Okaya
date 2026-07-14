"""Byte-exact mirror of the Rust core's canonical signing encoders.

The Issuance server signs leases (and intermediate certs) that the Rust core
verifies offline. Signatures are computed over *canonical bytes*, not JSON text,
so this module must reproduce `core/src/canon.rs`, `cert.rs::signing_bytes`, and
`lease.rs::signing_bytes` exactly. The cross-language contract is enforced by
`tests/test_crosslang.py`, which signs here and verifies with the real core
(`ksverify`).

Rules mirrored from serde:
  * embedded struct JSON (fingerprint_reference / policy) uses declaration-order
    fields, compact separators, no non-ASCII escaping;
  * the entitlement snapshot (a BTreeMap in Rust) serializes with keys sorted
    ascending;
  * length-prefixed byte fields use a u32 big-endian length.
"""
from __future__ import annotations

import json
from typing import Any


# --- primitive encoders (mirror canon.rs) ---------------------------------

def put_bytes(buf: bytearray, b: bytes) -> None:
    buf += len(b).to_bytes(4, "big")
    buf += b


def put_str(buf: bytearray, s: str) -> None:
    put_bytes(buf, s.encode("utf-8"))


def put_opt_str(buf: bytearray, s: str | None) -> None:
    if s is None:
        buf.append(0)
    else:
        buf.append(1)
        put_str(buf, s)


def put_i64(buf: bytearray, v: int) -> None:
    buf += int(v).to_bytes(8, "big", signed=True)


def put_u64(buf: bytearray, v: int) -> None:
    buf += int(v).to_bytes(8, "big", signed=False)


def put_i32(buf: bytearray, v: int) -> None:
    buf += int(v).to_bytes(4, "big", signed=True)


def put_bool(buf: bytearray, v: bool) -> None:
    buf.append(1 if v else 0)


def _json(obj: Any) -> bytes:
    # serde_json compact form: no spaces, UTF-8 (no \uXXXX escaping of non-ASCII).
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# --- structured JSON fragments (must match serde field order) --------------

def fingerprint_reference_json(ref: dict) -> bytes:
    obj = {
        "salt": ref["salt"],
        "threshold": ref["threshold"],
        "components": [
            {"type": c["type"], "hash": c["hash"], "weight": c["weight"]}
            for c in ref["components"]
        ],
    }
    return _json(obj)


def snapshot_json(snapshot: dict[str, dict]) -> bytes:
    # BTreeMap<String, _> => keys sorted ascending; each value already in
    # serde order (kind first).
    ordered = {k: snapshot[k] for k in sorted(snapshot.keys())}
    return _json(ordered)


def policy_json(policy: dict) -> bytes:
    obj = {
        "warning_window_secs": policy["warning_window_secs"],
        "online_refresh_secs": policy["online_refresh_secs"],
        "offline_grace_secs": policy["offline_grace_secs"],
        "event_buffer_cap": policy["event_buffer_cap"],
    }
    return _json(obj)


# --- the two signed payloads ----------------------------------------------

def cert_signing_bytes(cert: dict) -> bytes:
    buf = bytearray()
    put_bytes(buf, bytes.fromhex(cert["pubkey"]))
    put_i32(buf, cert["key_version"])
    put_i64(buf, cert["valid_from"])
    put_i64(buf, cert["valid_until"])
    put_bool(buf, cert.get("signed_by_reserve", False))
    return bytes(buf)


def lease_signing_bytes(lease: dict) -> bytes:
    buf = bytearray()
    put_str(buf, lease["lease_id"])
    put_str(buf, lease["license_id"])
    put_bytes(buf, bytes.fromhex(lease["device_pubkey"]))
    put_bytes(buf, bytes.fromhex(lease["fingerprint_hash"]))
    buf += fingerprint_reference_json(lease["fingerprint_reference"])
    buf += snapshot_json(lease["entitlement_snapshot"])
    buf += policy_json(lease["policy"])
    put_i64(buf, lease["issued_at"])
    put_i64(buf, lease["valid_from"])
    put_i64(buf, lease["valid_until"])
    put_i64(buf, lease["max_launches"] if lease.get("max_launches") is not None else -1)
    put_bytes(buf, bytes.fromhex(lease["nonce"]))
    put_u64(buf, lease["serial"])
    put_i32(buf, lease["signed_by_key_version"])
    put_opt_str(buf, lease.get("licensed_to_name"))
    put_opt_str(buf, lease.get("licensed_to_email"))
    put_opt_str(buf, lease.get("issuer_notice"))
    put_i64(
        buf,
        lease["reported_tripwire_timestamp"]
        if lease.get("reported_tripwire_timestamp") is not None
        else 0,
    )
    return bytes(buf)


# --- release manifest canonical bytes (mirror core/src/manifest.rs) --------

def manifest_signing_bytes(m: dict) -> bytes:
    buf = bytearray()
    put_str(buf, m["release_id"])
    put_str(buf, m["track"])
    put_str(buf, m["version"])
    put_str(buf, m["channel"])
    put_i64(buf, m.get("abi_version", -1) if m.get("abi_version") is not None else -1)
    put_i64(buf, m.get("min_abi_required", -1) if m.get("min_abi_required") is not None else -1)
    put_opt_str(buf, m.get("pinned_core_version"))
    put_opt_str(buf, m.get("pinned_fw_version"))
    put_bytes(buf, bytes.fromhex(m["full_artifact_hash"]))
    # delta_entries: serde field order {from_version, delta_hash, delta_pointer}
    entries = [
        {"from_version": e["from_version"], "delta_hash": e["delta_hash"], "delta_pointer": e["delta_pointer"]}
        for e in m.get("delta_entries", [])
    ]
    buf += _json(entries)
    put_i64(buf, m["build_timestamp"])
    put_opt_str(buf, m.get("sbom_hash"))
    put_opt_str(buf, m.get("release_notes_hash"))
    put_opt_str(buf, m.get("criticality"))
    put_i32(buf, m["signed_by_key_version"])
    return bytes(buf)


# --- activation request (.ksreq) canonical bytes ---------------------------
# Signed by the device key; verified server-side. Mirror in core (make_activation_request).

def request_signing_bytes(req: dict) -> bytes:
    buf = bytearray()
    put_str(buf, req["product_id"])
    put_str(buf, req["runtime"])
    put_bytes(buf, bytes.fromhex(req["device_pubkey"]))
    put_str(buf, req["key_protection_tier"])
    put_bytes(buf, bytes.fromhex(req["fingerprint_hash"]))
    put_str(buf, req["request_type"])
    put_i64(buf, req["client_time"])
    put_bytes(buf, bytes.fromhex(req["nonce"]))
    put_str(buf, req["sdk_version"])
    put_opt_str(buf, req.get("current_lease_id"))
    return bytes(buf)
