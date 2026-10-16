"""Bounded search for the first observed failing bit length in this GMP build.

Each case uses probe_windows_gmp_square.py's disposable child, allocator trace,
memory guard, and timeout.  Binary search assumes a monotone boundary; the
report labels the result as an observed adjacent pair, not a universal limit.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "experiments_20261016" / "isolated_square"
OUT = ROOT / "experiments_20261016" / "bisect_20261016.jsonl"
LOW = 2_140_000_000
HIGH = 2_147_483_647


def checked(bits: int, direct: bool = False) -> dict:
    case = CASES / f"{'direct_gmp_' if direct else ''}bits_{bits}"
    result_path = case / "result.json"
    if not result_path.exists():
        cmd = [sys.executable, str(ROOT / "probe_windows_gmp_square.py"),
               "--bits", str(bits), "--timeout", "90", "--min-available-gib", "6"]
        if direct:
            cmd.append("--direct-gmp")
        run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=105)
        if run.returncode != 0:
            raise RuntimeError(f"probe parent failed for {bits}: {run.stderr[-1000:]}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result["guard"] is not None:
        raise RuntimeError(f"guard fired at {bits}: {result['guard']}")
    if result["exit_code"] == 0:
        verdict = "success"
    elif result["exit_code"] == 3 and result["large_allocation_events"]:
        verdict = "wrapped_request_failure"
    else:
        raise RuntimeError(f"unclassified outcome at {bits}: {result}")
    row = {"bits": bits, "direct_gmp": direct, "verdict": verdict,
           "elapsed_s": result["elapsed_s"],
           "peak_private_bytes": result["peak_private_bytes"],
           "min_available_physical_bytes": result["min_available_physical_bytes"],
           "wrapped_size_t_bytes": result["large_allocation_events"][0]["size_t_bytes"]
               if result["large_allocation_events"] else None,
           "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with OUT.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def main() -> None:
    low, high = LOW, HIGH
    assert checked(low)["verdict"] == "success"
    assert checked(high)["verdict"] == "wrapped_request_failure"
    while high - low > 1:
        mid = (low + high) // 2
        verdict = checked(mid)["verdict"]
        if verdict == "success":
            low = mid
        else:
            high = mid
    last_success = checked(low, direct=True)
    first_failure = checked(high, direct=True)
    summary = {"last_success_bits": low, "first_failure_bits": high,
               "direct_last_success": last_success["verdict"],
               "direct_first_failure": first_failure["verdict"],
               "result_bits_at_first_failure": 2 * high - 1,
               "result_limbs_64bit": (2 * high - 1 + 63) // 64,
               "fft_rounding_length": None,
               "caveat": "Observed adjacent pair under a binary-search monotonicity assumption; native FFT length not measured."}
    (ROOT / "experiments_20261016" / "bisect_summary_20261016.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
