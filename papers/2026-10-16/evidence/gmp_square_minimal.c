/* Reproduce the observed Windows GMP square failure without Python or gmpy2.
 * Usage: gmp_square_minimal.exe <full-path-to-libgmp-10.dll> <operand-bits>
 * Run each input in a disposable, memory-guarded process.
 */
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { int alloc; int size; void *limbs; } mpz_struct;
typedef mpz_struct mpz_t[1];
typedef void (__cdecl *init_ui_fn)(mpz_t, unsigned long);
typedef void (__cdecl *init_fn)(mpz_t);
typedef void (__cdecl *shift_fn)(mpz_t, const mpz_t, unsigned long);
typedef void (__cdecl *mul_fn)(mpz_t, const mpz_t, const mpz_t);
typedef void (__cdecl *clear_fn)(mpz_t);

int main(int argc, char **argv) {
    HMODULE lib;
    init_ui_fn init_ui;
    init_fn init;
    shift_fn shift;
    mul_fn mul;
    clear_fn clear;
    mpz_t x, y;
    unsigned long bits;
    char *end = NULL;

    if (argc != 3) {
        fprintf(stderr, "usage: %s <DLL-path> <operand-bits>\n", argv[0]);
        return 2;
    }
    bits = strtoul(argv[2], &end, 10);
    if (!end || *end || bits < 2 || bits > 2776967654UL) {
        fprintf(stderr, "invalid operand bit length\n");
        return 2;
    }
    lib = LoadLibraryA(argv[1]);
    if (!lib) {
        fprintf(stderr, "LoadLibrary failed: %lu\n", GetLastError());
        return 2;
    }
    init_ui = (init_ui_fn)GetProcAddress(lib, "__gmpz_init_set_ui");
    init = (init_fn)GetProcAddress(lib, "__gmpz_init");
    shift = (shift_fn)GetProcAddress(lib, "__gmpz_mul_2exp");
    mul = (mul_fn)GetProcAddress(lib, "__gmpz_mul");
    clear = (clear_fn)GetProcAddress(lib, "__gmpz_clear");
    if (!init_ui || !init || !shift || !mul || !clear) {
        fprintf(stderr, "required GMP export missing\n");
        FreeLibrary(lib);
        return 2;
    }
    init_ui(x, 1UL);
    init(y);
    shift(x, x, bits - 1UL);
    printf("before_mul bits=%lu operand_limbs=%d\n", bits, x[0].size);
    fflush(stdout);
    mul(y, x, x);
    printf("after_mul result_limbs=%d expected_result_bits=%llu\n",
           y[0].size, (unsigned long long)(2ULL * bits - 1ULL));
    fflush(stdout);
    clear(y);
    clear(x);
    FreeLibrary(lib);
    return 0;
}
