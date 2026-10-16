"""Independent small-modulus checks against a retained F(10^10) digit file."""
from __future__ import annotations

from decimal import Decimal, localcontext
import json
from pathlib import Path

N = 10_000_000_000
ROOT = Path(__file__).resolve().parent
FILE = ROOT / "experiments_20261015" / "linux_native_10b_reference" / "output.txt"
OUT = ROOT / "experiments_20261016" / "decimal_residues_20261016.json"
PRIMES = (1_000_000_007, 1_000_000_009, 2_147_483_647)


def fib_pair_mod(n: int, modulus: int) -> tuple[int, int]:
    """Fast doubling using bounded Python integers; returns F(n), F(n+1)."""
    a, b = 0, 1
    for bit in bin(n)[2:]:
        c = a * (2 * b - a) % modulus
        d = (a * a + b * b) % modulus
        a, b = (d, (c + d) % modulus) if bit == "1" else (c, d)
    return a, b


def main() -> None:
    count = sum_digits = alternate = 0
    leading = bytearray()
    tail = bytearray()
    with FILE.open("rb") as stream:
        while block := stream.read(8 << 20):
            if len(leading) < 20:
                leading.extend(block[:20-len(leading)])
            tail = (tail + block)[-20:]
            if not block.isdigit():
                raise ValueError(f"non-digit block at byte {count}")
            sum_digits += sum(block) - 48 * len(block)
            even_bytes, odd_bytes = block[::2], block[1::2]
            local_alternate = (sum(even_bytes) - 48 * len(even_bytes)
                               - sum(odd_bytes) + 48 * len(odd_bytes))
            alternate += local_alternate if count % 2 == 0 else -local_alternate
            count += len(block)
    # For an odd number of digits, first/last powers of 10 have the same sign mod 11.
    decimal_mod_9 = sum_digits % 9
    decimal_mod_11 = alternate % 11 if count % 2 else -alternate % 11
    residues = {str(m): fib_pair_mod(N, m)[0] for m in (9, 11, *PRIMES)}
    cassini = {}
    for prime in PRIMES:
        fn, fn1 = fib_pair_mod(N, prime)
        fnminus1 = (fn1 - fn) % prime
        actual = (fn1 * fnminus1 - fn * fn) % prime
        expected = 1  # N is even.
        assert actual == expected
        cassini[str(prime)] = {"F_n": fn, "F_n_minus_1": fnminus1,
                               "F_n_plus_1": fn1, "lhs": actual, "rhs": expected}
    assert decimal_mod_9 == residues["9"]
    assert decimal_mod_11 == residues["11"]
    period_mod_100000 = 1_500_000
    a, b = 0, 1
    for _ in range(N % period_mod_100000):
        a, b = b, (a+b) % 100_000
    assert a == int(tail[-5:])
    with localcontext() as ctx:
        ctx.prec = 90
        phi = (Decimal(1) + Decimal(5).sqrt()) / 2
        log10 = Decimal(10).ln()
        log_fib = Decimal(N) * phi.ln() / log10 - Decimal(5).ln() / (2*log10)
        floor_log = int(log_fib)
        fraction = log_fib - floor_log
        first5 = int((log10 * (fraction + 4)).exp())
        assert first5 == int(leading[:5])
        digits_predicted = floor_log + 1
        assert digits_predicted == count
    result = {"file": str(FILE), "n": N, "digit_count": count,
              "decimal_mod_9": decimal_mod_9, "decimal_mod_11": decimal_mod_11,
              "expected_mod_9": residues["9"], "expected_mod_11": residues["11"],
              "digit_sum": sum_digits, "alternating_sum": alternate,
              "cassini_prime_checks": cassini, "pisano_period_mod_100000": period_mod_100000,
              "last5": tail[-5:].decode(), "leading5": leading[:5].decode(),
              "log10_fraction_80_digit_context": str(fraction),
              "log10_digit_count": digits_predicted}
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
