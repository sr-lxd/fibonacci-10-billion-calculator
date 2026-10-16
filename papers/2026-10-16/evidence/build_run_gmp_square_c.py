"""Build and guard-run the independent C LoadLibrary GMP square reproducer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time

import psutil

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "experiments_20261016" / "native_c_reproducer"
DLL = Path(r"C:\Users\lusun\AppData\Roaming\Python\Python313\site-packages\gmpy2.libs\libgmp-10.dll")
EXPECTED_DLL_SHA = "829adcf025d22e641c6816b431fbe5b226a39b390c7205192d480151646fe9c9"
VCVARS = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat")
SOURCE = ROOT / "gmp_square_minimal.c"
EXE = OUT / "gmp_square_minimal.exe"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = ("@echo off\r\n"
           "call \"" + str(VCVARS) + "\" >nul\r\n"
           "cl /nologo /utf-8 /O2 /W4 /Fo\"" + str(OUT / "gmp_square_minimal.obj")
           + "\" \"" + str(SOURCE) + "\" /link /OUT:\"" + str(EXE) + "\"\r\n")
    batch = OUT / "build.cmd"
    batch.write_bytes(cmd.encode("utf-8"))
    data = batch.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and data.count(b"\n") == data.count(b"\r\n")
    run = subprocess.run(["cmd.exe", "/d", "/c", str(batch)], cwd=OUT,
                         capture_output=True, timeout=120)
    (OUT / "build_stdout.txt").write_bytes(run.stdout)
    (OUT / "build_stderr.txt").write_bytes(run.stderr)
    if run.returncode != 0:
        raise RuntimeError(run.stdout.decode(errors="replace") + run.stderr.decode(errors="replace"))
    print("BUILT", str(EXE), sha(EXE), flush=True)


def guarded_run(bits: int) -> dict:
    case = OUT / str(bits)
    case.mkdir(exist_ok=True)
    start = time.perf_counter()
    peak_wset = peak_private = 0
    minimum_available = psutil.virtual_memory().available
    guard = None
    with (case / "stdout.txt").open("wb") as stdout, (case / "stderr.txt").open("wb") as stderr:
        process = subprocess.Popen([str(EXE), str(DLL), str(bits)], cwd=case,
                                   stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        ps = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                memory = ps.memory_info()
                available = psutil.virtual_memory().available
                peak_wset = max(peak_wset, memory.rss)
                peak_private = max(peak_private, memory.private)
                minimum_available = min(minimum_available, available)
                if available < 6 * (1 << 30):
                    guard = "available_physical_below_6_GiB"
                    process.kill()
                if time.perf_counter() - start > 90:
                    guard = "timeout_90_s"
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(.05)
        exit_code = process.wait()
    result = {"bits": bits, "exit_code": exit_code, "guard": guard,
              "elapsed_s": time.perf_counter()-start,
              "peak_wset_bytes": peak_wset, "peak_private_bytes": peak_private,
              "min_available_physical_bytes": minimum_available,
              "stdout": (case / "stdout.txt").read_text(errors="replace"),
              "stderr": (case / "stderr.txt").read_text(errors="replace")}
    (case / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("RESULT", json.dumps(result), flush=True)
    return result


def main() -> None:
    assert sha(DLL) == EXPECTED_DLL_SHA
    build()
    small = guarded_run(1_000)
    success = guarded_run(2_147_352_576)
    failure = guarded_run(2_147_352_577)
    assert small["exit_code"] == success["exit_code"] == 0
    assert failure["exit_code"] != 0 and failure["guard"] is None
    manifest = {"source_sha256": sha(SOURCE), "exe_sha256": sha(EXE),
                "dll": str(DLL), "dll_sha256": sha(DLL),
                "compiler": str(VCVARS), "cases": [small, success, failure]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
