"""Isolate the Windows gmpy2.square failure from Fibonacci and decimal output.

Each input runs in a disposable child process.  The parent samples memory and
enforces a timeout/available-memory guard.  The GMP memory callback is installed
before importing gmpy2 and records the full 64-bit allocation request.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parent / "experiments_20261016" / "isolated_square"


def child(case: Path, bits: int) -> None:
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    from trace_gmp_alloc import install, verify_after_import

    install(case)
    import gmpy2

    verify_after_import()
    binary = Path(gmpy2.gmpy2.__file__)
    (case / "runtime.json").write_text(json.dumps({
        "python": sys.version,
        "gmpy2": gmpy2.version(),
        "gmp": gmpy2.mp_version(),
        "module_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "limb_bits": 64,
        "pointer_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        "long_bits": ctypes.sizeof(ctypes.c_long) * 8,
    }, indent=2), encoding="utf-8")
    x = gmpy2.mpz(1) << (bits - 1)
    print(json.dumps({"event": "before_square", "bits": x.bit_length()}), flush=True)
    y = gmpy2.square(x)
    print(json.dumps({"event": "after_square", "bits": y.bit_length(),
                      "expected_bits": 2 * bits - 1,
                      "equal_sparse_square": y == (gmpy2.mpz(1) << (2 * bits - 2))}), flush=True)


def direct_gmp_child(case: Path, bits: int) -> None:
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    from trace_gmp_alloc import install, STATE

    install(case)
    dll = STATE["dll"]

    class MPZ(ctypes.Structure):
        _fields_ = [("alloc", ctypes.c_int), ("size", ctypes.c_int),
                    ("limbs", ctypes.c_void_p)]

    init_ui = dll.__gmpz_init_set_ui
    init_ui.argtypes = [ctypes.POINTER(MPZ), ctypes.c_ulong]
    init_ui.restype = None
    init = dll.__gmpz_init
    init.argtypes = [ctypes.POINTER(MPZ)]
    init.restype = None
    shift = dll.__gmpz_mul_2exp
    shift.argtypes = [ctypes.POINTER(MPZ), ctypes.POINTER(MPZ), ctypes.c_ulong]
    shift.restype = None
    mul = dll.__gmpz_mul
    mul.argtypes = [ctypes.POINTER(MPZ), ctypes.POINTER(MPZ), ctypes.POINTER(MPZ)]
    mul.restype = None
    clear = dll.__gmpz_clear
    clear.argtypes = [ctypes.POINTER(MPZ)]
    clear.restype = None
    x, y = MPZ(), MPZ()
    init_ui(ctypes.byref(x), 1)
    init(ctypes.byref(y))
    shift(ctypes.byref(x), ctypes.byref(x), bits - 1)
    print(json.dumps({"event": "before_direct_gmp_mul", "bits": bits,
                      "operand_limbs": x.size}), flush=True)
    mul(ctypes.byref(y), ctypes.byref(x), ctypes.byref(x))
    print(json.dumps({"event": "after_direct_gmp_mul", "result_limbs": y.size,
                      "expected_bits": 2 * bits - 1}), flush=True)
    clear(ctypes.byref(y))
    clear(ctypes.byref(x))


def parent(bits: int, timeout: int, min_available_gib: float, direct_gmp: bool) -> dict:
    case = ROOT / f"{'direct_gmp_' if direct_gmp else ''}bits_{bits}"
    case.mkdir(parents=True, exist_ok=False)
    cmd = [sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()),
           "--child", "--case", str(case), "--bits", str(bits)]
    if direct_gmp:
        cmd.append("--direct-gmp")
    start = time.perf_counter()
    guard = None
    peak_private = peak_wset = 0
    min_available = psutil.virtual_memory().available
    with (case / "stdout.jsonl").open("wb") as out, (case / "stderr.txt").open("wb") as err, \
         (case / "memory.jsonl").open("w", encoding="utf-8", buffering=1) as mem:
        proc = subprocess.Popen(cmd, stdout=out, stderr=err,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        p = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                mi = p.memory_info()
                available = psutil.virtual_memory().available
                min_available = min(min_available, available)
                peak_private = max(peak_private, mi.private)
                peak_wset = max(peak_wset, mi.rss)
                mem.write(json.dumps({"elapsed_s": time.perf_counter() - start,
                                      "private_bytes": mi.private, "rss_bytes": mi.rss,
                                      "available_physical_bytes": available}) + "\n")
                if available < min_available_gib * (1 << 30):
                    guard = "available_physical_below_guard"
                    proc.kill()
                elif time.perf_counter() - start > timeout:
                    guard = "timeout"
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(.05)
        exit_code = proc.wait()
    trace = case / "allocation_trace.jsonl"
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()] if trace.exists() else []
    result = {"bits": bits, "direct_gmp": direct_gmp,
              "exit_code": exit_code, "guard": guard,
              "elapsed_s": time.perf_counter() - start,
              "peak_private_bytes": peak_private, "peak_wset_bytes": peak_wset,
              "min_available_physical_bytes": min_available,
              "large_allocation_events": [e for e in events if e.get("kind") in ("allocate", "reallocate")],
              "stderr": (case / "stderr.txt").read_text(encoding="utf-8", errors="replace")}
    (case / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "stderr"}, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--case", type=Path)
    parser.add_argument("--bits", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--min-available-gib", type=float, default=6.0)
    parser.add_argument("--direct-gmp", action="store_true")
    args = parser.parse_args()
    if args.child:
        if args.direct_gmp:
            direct_gmp_child(args.case, args.bits)
        else:
            child(args.case, args.bits)
    else:
        parent(args.bits, args.timeout, args.min_available_gib, args.direct_gmp)
