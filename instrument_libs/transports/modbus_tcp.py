"""Modbus/TCP transport (real hardware). Stdlib sockets only — no pymodbus — so the
repo installs standalone and sim + conformance run without it (a real relay card is
not needed to gate the library). Blocking socket I/O runs in a thread executor so it
never stalls the event loop (mirrors transports/visa.py).

The framework transport contract is string-in / string-out (`query`/`write`); this
transport translates a tiny command grammar into Modbus function codes so the library's
CMD table stays the human review surface and the base fault model (timeout / disconnect
/ garbage / delay / error_response) applies unchanged:

    query("R1 <addr>")          FC01 read 1 coil             -> "1" | "0"
    query("R2 <addr>")          FC02 read 1 discrete input   -> "1" | "0"
    query("R3 <addr>")          FC03 read 1 holding reg      -> "<uint16>"
    query("R4 <addr>")          FC04 read 1 input reg        -> "<uint16>"
    query("R4F <addr>")         FC04 read 2 input regs, IEEE-754 float32 -> "<float>"
    write("W5 <addr> ON|OFF")   FC05 write 1 coil (0xFF00/0x0000)

`<addr>` accepts decimal or 0x-hex (int(tok, 0)). A Modbus exception reply becomes a
structured DeviceError; any socket failure becomes TransportDisconnected.

`R4F` assembles the two 16-bit registers into a 32-bit IEEE-754 float. `float_word_order=`
picks which register is the most-significant half: "lo_hi" (default) = low address holds the
LOW word ("LSB on lower address, MSB on higher address" — a common meter convention); "hi_lo" =
low address holds the HIGH word (plain big-endian "ABCD"). Byte order within each register is
always Modbus big-endian.

Two wire framings (`framing=`): "tcp" = native Modbus/TCP (MBAP header, port 502);
"rtu" = Modbus RTU tunnelled over a raw TCP socket (unit + PDU + CRC16, no MBAP), the
common mode for serial-to-Ethernet relay boards (Waveshare/Elfin, default port 4196).
"""

from __future__ import annotations

import asyncio
import socket
import struct

from instrumentlib.errors import DeviceError, GarbageResponse, TransportDisconnected
from instrumentlib.transport import Transport


def _crc16(data: bytes) -> bytes:
    """Modbus RTU CRC-16 (poly 0xA001), returned little-endian (lo, hi) for appending."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return struct.pack("<H", crc)


class ModbusTcpTransport(Transport):
    def __init__(self, host: str, *, port: int = 502, unit_id: int = 1,
                 timeout_ms: int = 5000, framing: str = "tcp",
                 float_word_order: str = "lo_hi"):
        self.host = host
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.timeout_ms = int(timeout_ms)
        self.framing = framing
        if framing not in ("tcp", "rtu"):
            raise ValueError(f"framing must be 'tcp' or 'rtu', got {framing!r}")
        self.float_word_order = float_word_order
        if float_word_order not in ("lo_hi", "hi_lo"):
            raise ValueError(f"float_word_order must be 'lo_hi' or 'hi_lo', got {float_word_order!r}")
        self._sock: socket.socket | None = None
        self._tid = 0

    async def _run(self, fn, *a):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *a)

    async def connect(self) -> None:
        def _open():
            s = socket.create_connection((self.host, self.port), timeout=self.timeout_ms / 1000.0)
            s.settimeout(self.timeout_ms / 1000.0)
            return s
        try:
            self._sock = await self._run(_open)
        except Exception as exc:  # noqa: BLE001 — surface as a structured disconnect
            raise TransportDisconnected(f"Modbus connect failed: {exc}",
                                        detail=f"{self.host}:{self.port}") from exc

    async def disconnect(self) -> None:
        if self._sock is not None:
            try:
                await self._run(self._sock.close)
            except Exception:  # noqa: BLE001
                pass
        self._sock = None

    # ---- Modbus/TCP framing (MBAP header + PDU) ---------------------------

    def _txn(self, pdu: bytes) -> bytes:
        """Send one request PDU, return the response PDU (function byte + data)."""
        sock = self._sock
        if sock is None:
            raise TransportDisconnected("Modbus not connected", detail=repr(pdu))
        try:
            body = self._txn_rtu(pdu) if self.framing == "rtu" else self._txn_tcp(pdu)
        except (OSError, socket.timeout) as exc:
            raise TransportDisconnected(f"Modbus I/O failed: {exc}",
                                        detail=f"{self.host}:{self.port}") from exc
        if body and (body[0] & 0x80):             # exception response: fn|0x80, exc code
            code = body[1] if len(body) > 1 else 0
            raise DeviceError(f"Modbus exception 0x{code:02X}", detail=f"fn=0x{body[0] & 0x7F:02X}")
        return body

    def _txn_tcp(self, pdu: bytes) -> bytes:
        self._tid = (self._tid + 1) & 0xFFFF
        frame = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit_id) + pdu
        self._sock.sendall(frame)                 # type: ignore[union-attr]
        tid, _proto, length, _unit = struct.unpack(">HHHB", self._recv_exact(7))
        body = self._recv_exact(length - 1)       # length counts unit_id + PDU
        if tid != self._tid:
            # A stale/delayed reply (e.g. from a slow RTU<->TCP gateway) sitting in the
            # socket buffer would otherwise be silently accepted as this call's answer —
            # the MBAP transaction id exists precisely to catch this. Force a reconnect
            # (closes + reopens the socket) rather than try to resync in place: whatever
            # is left in the buffer after a mismatch is not trustworthy.
            raise TransportDisconnected(
                f"Modbus/TCP transaction id mismatch (sent {self._tid}, got {tid}) — "
                "stream desynced", detail=f"{self.host}:{self.port}")
        return body

    def _txn_rtu(self, pdu: bytes) -> bytes:
        """RTU-over-TCP: [unit | PDU | CRC16]. No length field, so the response size is
        derived from the (echoed) function code, then the CRC is verified."""
        frame = bytes([self.unit_id]) + pdu
        self._sock.sendall(frame + _crc16(frame))  # type: ignore[union-attr]
        head = self._recv_exact(2)                 # unit + function
        fn = head[1]
        if fn & 0x80:
            rest = self._recv_exact(3)             # exc code + CRC(2)
        elif fn in (1, 2, 3, 4):                   # count-prefixed reads
            bc = self._recv_exact(1)
            rest = bc + self._recv_exact(bc[0] + 2)
        elif fn in (5, 6, 15, 16):                 # echoed writes: 4 data bytes + CRC(2)
            rest = self._recv_exact(6)
        else:
            raise GarbageResponse(f"unexpected RTU function 0x{fn:02X}")
        full = head + rest
        if _crc16(full[:-2]) != full[-2:]:
            raise GarbageResponse("RTU CRC mismatch", detail=full.hex())
        return full[1:-2]                          # strip unit + CRC -> fn + data

    def _recv_exact(self, n: int) -> bytes:
        sock = self._sock
        assert sock is not None
        chunks: list[bytes] = []
        got = 0
        while got < n:
            part = sock.recv(n - got)
            if not part:
                raise TransportDisconnected("Modbus link closed mid-frame")
            chunks.append(part)
            got += len(part)
        return b"".join(chunks)

    # ---- string command grammar (library CMD table) ----------------------

    async def query(self, cmd: str) -> str:
        return await self._run(self._query, cmd)

    def _query(self, cmd: str) -> str:
        op, *rest = cmd.split()
        if op in ("R1", "R2"):                    # read 1 coil / discrete input
            addr = int(rest[0], 0)
            fn = 1 if op == "R1" else 2
            body = self._txn(struct.pack(">BHH", fn, addr, 1))
            # body = fn, byte_count, data[0..]
            if len(body) < 3:
                raise GarbageResponse(f"short Modbus read reply {body!r}", detail=cmd)
            return "1" if (body[2] & 0x01) else "0"
        if op in ("R3", "R4"):                    # read 1 holding (FC03) / input (FC04) register
            addr = int(rest[0], 0)
            fn = 3 if op == "R3" else 4
            body = self._txn(struct.pack(">BHH", fn, addr, 1))
            if len(body) < 4:
                raise GarbageResponse(f"short Modbus register reply {body!r}", detail=cmd)
            return str(struct.unpack(">H", body[2:4])[0])
        if op == "R4F":                           # FC04 read 2 input regs -> IEEE-754 float32
            addr = int(rest[0], 0)
            body = self._txn(struct.pack(">BHH", 4, addr, 2))
            if len(body) < 6:
                raise GarbageResponse(f"short Modbus float reply {body!r}", detail=cmd)
            w0, w1 = struct.unpack(">HH", body[2:6])   # w0 @ addr, w1 @ addr+1
            hi, lo = (w1, w0) if self.float_word_order == "lo_hi" else (w0, w1)
            return repr(struct.unpack(">f", struct.pack(">HH", hi, lo))[0])
        raise GarbageResponse(f"unknown Modbus query {cmd!r}", detail=cmd)

    async def write(self, cmd: str) -> None:
        await self._run(self._write, cmd)

    def _write(self, cmd: str) -> None:
        op, *rest = cmd.split()
        if op == "W5":                            # write single coil
            addr = int(rest[0], 0)
            value = 0xFF00 if rest[1].upper() == "ON" else 0x0000
            self._txn(struct.pack(">BHH", 5, addr, value))
            return
        raise DeviceError(f"unknown Modbus write {cmd!r}", detail=cmd)
