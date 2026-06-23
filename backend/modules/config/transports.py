"""Transport catalog — the single source that drives the instrument UI.

Each transport declares a typed field list and an `address_template`. The frontend
renders one generic form from this; LabVIEW owns the actual driver. Adding a new
instrument transport = add an entry here, no UI code (the scalability contract).

Field types the UI knows: string | number | password | select (with `options`).
`address_template` previews the canonical resource via `str.format(**params)`.
"""

from __future__ import annotations


def _f(key, label, type="string", *, required=False, default=None, placeholder="", help="", options=None):
    d = {"key": key, "label": label, "type": type, "required": required,
         "default": default, "placeholder": placeholder, "help": help}
    if options is not None:
        d["options"] = options
    return d


_BAUD = ["9600", "19200", "38400", "57600", "115200"]
_PARITY = ["N", "E", "O"]
_CAN_BITRATE = ["125000", "250000", "500000", "1000000"]

# Order = display order in the transport picker.
TRANSPORTS: list[dict] = [
    {
        "id": "visa", "label": "VISA (NI-VISA)",
        "address_template": "{resource}",
        "fields": [
            _f("resource", "VISA resource", required=True,
               placeholder="TCPIP0::192.168.0.10::INSTR",
               help="Any NI-VISA resource: TCPIP / USB / GPIB / ASRL."),
        ],
    },
    {
        "id": "modbus_tcp", "label": "Modbus TCP",
        "address_template": "{host}:{port} (unit {unit_id})",
        "fields": [
            _f("host", "Host / IP", required=True, placeholder="192.168.0.20"),
            _f("port", "Port", type="number", default=502),
            _f("unit_id", "Unit ID", type="number", default=1),
        ],
    },
    {
        "id": "modbus_rtu", "label": "Modbus RTU (serial)",
        "address_template": "{com_port}@{baud} {data_bits}{parity}{stop_bits} (unit {unit_id})",
        "fields": [
            _f("com_port", "COM port", required=True, placeholder="COM3 / /dev/ttyUSB0"),
            _f("baud", "Baud", type="select", default="9600", options=_BAUD),
            _f("parity", "Parity", type="select", default="N", options=_PARITY),
            _f("data_bits", "Data bits", type="number", default=8),
            _f("stop_bits", "Stop bits", type="number", default=1),
            _f("unit_id", "Unit ID", type="number", default=1),
        ],
    },
    {
        "id": "can", "label": "CAN bus",
        "address_template": "{channel}@{bitrate}",
        "fields": [
            _f("channel", "Channel", required=True, placeholder="can0 / PCAN_USBBUS1"),
            _f("bitrate", "Bitrate", type="select", default="250000", options=_CAN_BITRATE),
            _f("arbitration_id", "Arbitration ID", placeholder="0x123", help="Optional default frame ID (hex)."),
        ],
    },
    {
        "id": "nidaq", "label": "NI-DAQmx",
        "address_template": "{device}/{channel}",
        "fields": [
            _f("device", "Device", required=True, placeholder="Dev1"),
            _f("channel", "Channel", required=True, placeholder="ai0"),
        ],
    },
    {
        "id": "serial", "label": "Serial / ASRL",
        "address_template": "{com_port}@{baud} {data_bits}{parity}{stop_bits}",
        "fields": [
            _f("com_port", "COM port", required=True, placeholder="COM3 / /dev/ttyUSB0"),
            _f("baud", "Baud", type="select", default="115200", options=_BAUD),
            _f("parity", "Parity", type="select", default="N", options=_PARITY),
            _f("data_bits", "Data bits", type="number", default=8),
            _f("stop_bits", "Stop bits", type="number", default=1),
        ],
    },
    {
        "id": "raw_tcp", "label": "Raw TCP/IP socket",
        "address_template": "{host}:{port}",
        "fields": [
            _f("host", "Host / IP", required=True, placeholder="192.168.0.30"),
            _f("port", "Port", type="number", default=5025, help="e.g. 5025 for SCPI-raw."),
        ],
    },
]

_BY_ID = {t["id"]: t for t in TRANSPORTS}


def get(transport_id: str) -> dict | None:
    return _BY_ID.get(transport_id)


def render_address(transport_id: str, params: dict) -> str:
    """Best-effort canonical resource string for display/logging. Missing fields
    render blank rather than raising (the form may be mid-edit)."""
    t = _BY_ID.get(transport_id)
    if not t:
        return ""

    class _Blank(dict):
        def __missing__(self, k):  # noqa: D401
            return ""
    try:
        return t["address_template"].format_map(_Blank(params or {})).strip()
    except Exception:  # noqa: BLE001 — never let a template break the API
        return ""


def missing_required(transport_id: str, params: dict) -> list[str]:
    t = _BY_ID.get(transport_id)
    if not t:
        return []
    params = params or {}
    return [f["key"] for f in t["fields"]
            if f.get("required") and not str(params.get(f["key"], "")).strip()]
