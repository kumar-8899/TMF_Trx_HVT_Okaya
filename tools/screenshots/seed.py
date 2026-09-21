"""Seed a running station with OBVIOUSLY-DEMO data so the UI looks populated for screenshots.

DEV-ONLY. Talks to the PUBLIC REST API only (stdlib urllib), never touches the DB or files
directly. Idempotent: re-running updates/skips what already exists. No secrets are seeded:
extra users get a server-generated temporary password which is discarded, never printed.

    python seed.py [--base http://127.0.0.1:8000] [--user admin] [--password admin]

Prints ONE line of JSON to stdout (a summary the capture script reads); progress goes to stderr.
Exit code 0 = seeded (some items may be reported as skipped), 1 = could not seed at all.

What it seeds (all labelled "Demo", values are illustrative - never product limits):
  * up to two SIMULATED Python-owned instruments, using whichever driver libraries the station
    has registered (GET /variables/libraries): one power_source, one analog_input. If the
    framework checkout has no driver library, nothing is seeded here and it says so.
  * two published recipes built from the controller's core step types.
  * two demo users (operator / engineer) if the auth API allows.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEMO_NOTE = ("Demo data created for documentation screenshots. Values are illustrative and are "
             "NOT product limits.")

_summary: dict = {"instruments": [], "recipes": [], "users": [], "skipped": [], "needs_restart": False}


def log(msg: str) -> None:
    print(f"seed: {msg}", file=sys.stderr, flush=True)


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(self, method: str, path: str, body=None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw

    def login(self, user: str, password: str) -> None:
        status, body = self.call("POST", "/auth/login",
                                 {"username": user, "credential": {"password": password}})
        if status != 200 or not isinstance(body, dict) or "token" not in body:
            raise SystemExit(f"seed: login as '{user}' failed (HTTP {status}): {body}")
        self.token = body["token"]


def _detail(body) -> str:
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("title") or body)
    return str(body)


# ------------------------------------------------------------------------------ instruments
def seed_instruments(api: Api) -> None:
    status, body = api.call("GET", "/variables/libraries")
    libs = (body or {}).get("libraries", []) if status == 200 and isinstance(body, dict) else []
    if not libs:
        msg = ("no instrument driver library is registered on this station (variables module "
               "library_paths / instrument_libs empty) - no instruments seeded")
        log(msg)
        _summary["skipped"].append(msg)
        return

    def pick(cap: str, prefer: tuple[str, ...]):
        cands = [lib for lib in libs if cap in (lib.get("capabilities") or [])]
        for pid in prefer:
            for lib in cands:
                if lib.get("library_id") == pid:
                    return lib
        return cands[0] if cands else None

    plan = [
        ("demo_psu", "Demo power supply (simulated)", pick("power_source", ("keysight_e36xx",)),
         "SIM::DEMO-PSU"),
        ("demo_daq", "Demo DAQ / meter (simulated)", pick("analog_input", ("keithley_daq6510",)),
         "SIM::DEMO-DAQ"),
    ]
    for iid, label, lib, resource in plan:
        if lib is None:
            _summary["skipped"].append(f"{iid}: no registered library offers the needed capability")
            continue
        params: dict = {}
        for key, spec in (lib.get("connection_params") or {}).items():
            if isinstance(spec, dict) and "default" in spec:
                params[key] = spec["default"]
        params["resource"] = resource
        rec = {
            "id": iid, "label": label, "owner": "python", "library": lib["library_id"],
            "model": f"{lib.get('vendor', '')} {lib.get('model', '')}".strip(),
            "simulated": True, "enabled": True, "params": params,
        }
        st, cur = api.call("GET", f"/config/instruments/{iid}")
        if st == 200 and isinstance(cur, dict):
            same = (cur.get("library") == rec["library"] and cur.get("simulated") is True
                    and cur.get("enabled", True) and (cur.get("params") or {}) == params)
            if same:
                log(f"instrument {iid}: already seeded")
                _summary["instruments"].append({"id": iid, "library": rec["library"], "action": "kept"})
                continue
            st, out = api.call("PUT", f"/config/instruments/{iid}", rec)
            action = "updated"
        else:
            st, out = api.call("POST", "/config/instruments", rec)
            action = "created"
        if st in (200, 201):
            log(f"instrument {iid}: {action} ({rec['library']}, simulated)")
            _summary["instruments"].append({"id": iid, "library": rec["library"], "action": action})
            _summary["needs_restart"] = True   # Python instruments build at backend startup
        else:
            msg = f"instrument {iid}: HTTP {st} {_detail(out)}"
            log(msg)
            _summary["skipped"].append(msg)


# ------------------------------------------------------------------------------ recipes
def _recipes() -> list[dict]:
    return [
        {
            "schema_version": 1,
            "recipe_id": "demo_supply_check",
            "name": "Demo recipe - supply check",
            "model": "DEMO-100",
            "description": "Demo recipe for documentation screenshots. " + DEMO_NOTE,
            "steps": [
                {"id": "operator_ready", "type": "prompt_operator",
                 "params": {"message": "Demo: connect the unit under test, then continue."}},
                {"id": "supply_on", "type": "set_output",
                 "params": {"signal": "demo_supply_voltage", "value": 12, "unit": "V"}},
                {"id": "settle", "type": "wait", "params": {"seconds": 1}},
                {"id": "check_voltage", "type": "measure_and_compare",
                 "params": {"signal": "demo_supply_readback", "name": "Demo supply voltage",
                            "unit": "V", "min": 11, "max": 13}},
                {"id": "supply_off", "type": "set_output",
                 "params": {"signal": "demo_supply_voltage", "value": 0, "unit": "V"}},
            ],
        },
        {
            "schema_version": 1,
            "recipe_id": "demo_sweep_group",
            "name": "Demo recipe - sweep and repeat",
            "model": "DEMO-200",
            "description": "Demo recipe showing composite steps. " + DEMO_NOTE,
            "steps": [
                {"id": "voltage_sweep", "type": "sweep",
                 "params": {"signal": "demo_supply_voltage", "values": [5, 10, 15],
                            "steps": [
                                {"id": "hold", "type": "wait", "params": {"seconds": 0.5}},
                                {"id": "read_point", "type": "measure_and_compare",
                                 "params": {"signal": "demo_supply_readback",
                                            "name": "Demo readback", "unit": "V"}},
                            ]}},
                {"id": "burst", "type": "repeat",
                 "params": {"count": 3,
                            "steps": [{"id": "burst_wait", "type": "wait", "params": {"seconds": 0.2}}]}},
                {"id": "optional_check", "type": "if",
                 "params": {"condition": {"signal": "demo_supply_readback", "above": 0},
                            "steps": [{"id": "group_a", "type": "group", "params": {"steps": [
                                {"id": "note_wait", "type": "wait", "params": {"seconds": 0.1}}]}}]}},
            ],
        },
    ]


def seed_recipes(api: Api) -> None:
    for payload in _recipes():
        rid = payload["recipe_id"]
        st, cur = api.call("GET", f"/recipes/{rid}")
        if st == 200:
            log(f"recipe {rid}: already exists")
            _summary["recipes"].append({"id": rid, "action": "kept"})
            continue
        body = {**payload, "owner": "admin"}
        st, rep = api.call("POST", "/recipes/validate", body)
        if st != 200 or not (isinstance(rep, dict) and rep.get("ok")):
            msg = f"recipe {rid}: validation failed: {_detail(rep)}"
            log(msg)
            _summary["skipped"].append(msg)
            continue
        st, out = api.call("POST", "/recipes", body)
        if st == 409:
            _summary["skipped"].append(f"recipe {rid}: exists as an unpublished draft - left alone")
            continue
        if st != 201 or not isinstance(out, dict):
            msg = f"recipe {rid}: create HTTP {st} {_detail(out)}"
            log(msg)
            _summary["skipped"].append(msg)
            continue
        st, pub = api.call("POST", f"/recipes/{rid}/drafts/{out['draft_id']}/publish")
        if st in (200, 201):
            log(f"recipe {rid}: created + published")
            _summary["recipes"].append({"id": rid, "action": "created"})
        else:
            msg = f"recipe {rid}: publish HTTP {st} {_detail(pub)}"
            log(msg)
            _summary["skipped"].append(msg)


# ------------------------------------------------------------------------------ users
def seed_users(api: Api) -> None:
    for name, role in (("demo_operator", "operator"), ("demo_engineer", "engineer")):
        st, out = api.call("POST", "/auth/users", {"username": name, "role": role})
        if st == 201:
            # The response carries a generated temporary password. It is deliberately dropped.
            log(f"user {name}: created ({role}); temporary password discarded")
            _summary["users"].append({"username": name, "role": role, "action": "created"})
        elif st in (409, 400, 422) and "exist" in _detail(out).lower():
            log(f"user {name}: already exists")
            _summary["users"].append({"username": name, "role": role, "action": "kept"})
        else:
            msg = f"user {name}: HTTP {st} {_detail(out)}"
            log(msg)
            _summary["skipped"].append(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin", help="dev credential (never a real secret)")
    args = ap.parse_args()

    api = Api(args.base)
    api.login(args.user, args.password)
    for step in (seed_instruments, seed_recipes, seed_users):
        try:
            step(api)
        except Exception as exc:  # noqa: BLE001 - keep going, report loudly
            msg = f"{step.__name__} crashed: {exc!r}"
            log(msg)
            _summary["skipped"].append(msg)
    print(json.dumps(_summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
