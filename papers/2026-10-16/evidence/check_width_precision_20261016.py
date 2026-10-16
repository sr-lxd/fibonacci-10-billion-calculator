"""Compare Binet-log decimal-width evaluations at 256 and 1024 MPFR bits."""
from __future__ import annotations

import json
from pathlib import Path
import gmpy2

N = 10_000_000_000
ROOT = Path(__file__).resolve().parent


def expression(bits: int):
    with gmpy2.local_context(gmpy2.get_context(), precision=bits):
        five = gmpy2.mpfr(5)
        phi = (1 + gmpy2.sqrt(five)) / 2
        return gmpy2.mpfr(N) * gmpy2.log10(phi) - gmpy2.log10(five) / 2


def main() -> None:
    x256 = expression(256)
    x1024 = expression(1024)
    with gmpy2.local_context(gmpy2.get_context(), precision=1024):
        delta = abs(gmpy2.mpfr(x256) - x1024)
        fractional = x1024 - gmpy2.floor(x1024)
        distance = min(fractional, 1-fractional)
    result = {"n": N, "mpfr_version": gmpy2.mpfr_version(),
              "precision_bits": [256, 1024],
              "floor_256": int(gmpy2.floor(x256)),
              "floor_1024": int(gmpy2.floor(x1024)),
              "fraction_1024": str(fractional),
              "absolute_difference_256_vs_1024": str(delta),
              "distance_to_nearest_integer_1024": str(distance),
              "is_formal_interval_certificate": False}
    assert result["floor_256"] == result["floor_1024"] == 2_089_876_402
    out = ROOT / "experiments_20261016" / "width_precision_20261016.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
