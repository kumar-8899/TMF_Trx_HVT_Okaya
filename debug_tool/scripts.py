"""Custom scripts on the client PC (docs/DEBUG_TOOL.md D4) - run ONLY after a human approved that exact text.

Containment, not a sandbox: the script runs as the Windows user who started the tool (no elevation), in `<data>/scripts/`,
with an environment scrubbed of tokens/secrets, one at a time, with a timeout (default 60 s, max 300 s), stdout/stderr capped,
and the whole process tree killed on timeout or runaway output. Every script is saved as `<time>-<sha256 prefix>.<ext>` beside its
output and a `result.json`, so there is always evidence of what ran. (The refusal to run during a test is decided by the caller:
it depends on what the approver ticked.)

Windows note: the tool runs on a *selector* event loop (aiomqtt needs it), which has no asyncio subprocess support, so processes
are started with `subprocess` in a worker thread.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

INTERPRETERS = ("powershell", "cmd", "python")
EXT = {"powershell": ".ps1", "cmd": ".cmd", "python": ".py"}
DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 300
OUTPUT_CAP = 256 * 1024                       # what Claude gets back
RAW_LIMIT = 16 * 1024 * 1024                  # runaway output: kill the script past this much on disk
MAX_ARGS = 20
_SECRET = re.compile(r"(?i)(token|secret|passw|pwd|credential|api[_-]?key|private[_-]?key|connection[_-]?string)")
_DROP = {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONUSERBASE"}


class ScriptError(Exception):
    pass


class ScriptBusy(ScriptError):
    pass


def scrubbed_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a script sees: the operator's own, minus anything that looks like a secret."""
    return {k: v for k, v in (base if base is not None else os.environ).items() if not _SECRET.search(k) and k.upper() not in _DROP}


def encode_script(interpreter: str, text: str) -> bytes:
    """Exactly the bytes that get saved, hashed and run. Windows shells want CRLF; PowerShell 5.1 wants a BOM for UTF-8."""
    if interpreter not in INTERPRETERS:
        raise ScriptError(f"interpreter must be one of {INTERPRETERS}")
    if not text.strip():
        raise ScriptError("the script is empty")
    body = text.replace("\r\n", "\n")
    if interpreter in ("powershell", "cmd"):
        body = body.replace("\n", "\r\n")
    raw = body.encode("utf-8")
    return b"\xef\xbb\xbf" + raw if interpreter == "powershell" else raw


def sha256_of(interpreter: str, text: str) -> str:
    return hashlib.sha256(encode_script(interpreter, text)).hexdigest()


def clamp_timeout(timeout_s: float | None) -> int:
    return max(1, min(int(timeout_s or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S))


def check_args(args: list[str] | None) -> list[str]:
    a = [str(x) for x in (args or [])]
    if len(a) > MAX_ARGS or any(len(x) > 500 for x in a):
        raise ScriptError(f"at most {MAX_ARGS} arguments of 500 characters")
    return a


def _decode(b: bytes) -> str:
    """Python scripts print UTF-8; PowerShell/cmd write the console's OEM code page when redirected. Try UTF-8 first, then OEM."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            return b.decode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", errors="replace")      # type: ignore[attr-defined]
        except (LookupError, AttributeError, OSError):
            pass
    return b.decode("utf-8", errors="replace")


def _cap_text(path: Path, limit: int = OUTPUT_CAP) -> tuple[str, bool]:
    if not path.is_file():
        return "", False
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size <= limit:
            return _decode(fh.read()), False
        head = fh.read(limit // 4)
        fh.seek(size - (limit - limit // 4))
        tail = fh.read()
    return (head.decode("utf-8", errors="replace") + f"\n...({size - limit} bytes omitted)...\n" + tail.decode("utf-8", errors="replace")), True


def _kill_tree(p: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:                                                              # noqa: BLE001
        pass
    try:
        p.kill()
    except Exception:                                                              # noqa: BLE001
        pass


class ScriptRunner:
    def __init__(self, scripts_dir: Path, python_resolver: Callable[[], dict], *, clock: Callable[[], float] = time.time) -> None:
        self.dir = Path(scripts_dir)
        self._python = python_resolver
        self._clock = clock
        self._busy = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def _argv(self, interpreter: str, script: Path, args: list[str]) -> tuple[list[str] | str, dict]:
        info: dict = {}
        if interpreter == "powershell":
            exe = shutil.which("powershell") or shutil.which("pwsh")
            if not exe:
                raise ScriptError("PowerShell was not found on this PC")
            return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args], info
        if interpreter == "cmd":
            bad = [a for a in args if any(c in a for c in '"%^&|<>')]
            if bad:
                raise ScriptError(f"cmd arguments may not contain any of \" % ^ & | < > (got {bad[0]!r}) - use a powershell or python script")
            inner = " ".join([f'"{script}"', *[f'"{a}"' for a in args]])
            # one verbatim command line: cmd's /s /c "..." rule is the only reliable way to run a path that contains spaces
            return f'"{os.environ.get("COMSPEC") or "cmd.exe"}" /d /s /c "{inner}"', info
        py = self._python()
        info = {"python": py}
        return [py["path"], "-I", str(script), *args] if py.get("kind") == "bundled" else [py["path"], str(script), *args], info

    def _run_blocking(self, argv: list[str] | str, cwd: Path, env: dict, timeout_s: int, out: Path, err: Path) -> dict:
        t0 = time.monotonic()
        timed_out = runaway = False
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with out.open("wb") as fo, err.open("wb") as fe:
            p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, creationflags=flags,
                                 start_new_session=(os.name != "nt"))
            while p.poll() is None:
                if time.monotonic() - t0 > timeout_s:
                    timed_out = True
                elif out.stat().st_size > RAW_LIMIT or err.stat().st_size > RAW_LIMIT:
                    runaway = True
                if timed_out or runaway:
                    _kill_tree(p)
                    p.wait(timeout=15)
                    break
                time.sleep(0.1)
            code = p.returncode
        return {"exit_code": -1 if (timed_out or runaway) else code, "timed_out": timed_out, "output_limit_exceeded": runaway,
                "elapsed_s": round(time.monotonic() - t0, 2)}

    async def run(self, interpreter: str, script: str, *, timeout_s: float | None = None, args: list[str] | None = None,
                  approved_by: str | None = None) -> dict:
        data = encode_script(interpreter, script)
        args = check_args(args)
        timeout = clamp_timeout(timeout_s)
        if not self._busy.acquire(blocking=False):
            raise ScriptBusy("another script is still running - one at a time")
        try:
            sha = hashlib.sha256(data).hexdigest()
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._clock()))
            base = f"{stamp}-{sha[:12]}"
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / (base + EXT[interpreter])
            path.write_bytes(data)
            argv, info = await asyncio.to_thread(self._argv, interpreter, path, args)
            out, err = self.dir / f"{base}.out.txt", self.dir / f"{base}.err.txt"
            res = await asyncio.to_thread(self._run_blocking, argv, self.dir, scrubbed_env(), timeout, out, err)
            so, t1 = _cap_text(out)
            se, t2 = _cap_text(err)
            result = {"interpreter": interpreter, "script_file": str(path), "sha256": sha, "args": args, "timeout_s": timeout,
                      "approved_by": approved_by, "ran_at": stamp, **res, "stdout": so, "stderr": se, "output_truncated": t1 or t2,
                      **({"python": {"kind": info["python"].get("kind"), "path": info["python"].get("path"),
                                     "version": info["python"].get("version"), "notes": info["python"].get("notes")}} if info else {})}
            (self.dir / f"{base}.result.json").write_text(json.dumps({k: v for k, v in result.items() if k not in ("stdout", "stderr")},
                                                                      indent=2, default=str), encoding="utf-8")
            return result
        finally:
            self._busy.release()

    def history(self, n: int = 50) -> list[dict]:
        if not self.dir.is_dir():
            return []
        rows = []
        for p in sorted(self.dir.glob("*.result.json"), reverse=True)[:n]:
            try:
                rows.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return rows
