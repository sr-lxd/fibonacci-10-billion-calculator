/*
 * F(n) calculator using MPIR's GMP-compatible mpz API.
 *
 * Build with MSVC after building/installing MPIR x64:
 *   cl /O2 /W4 /I"%MPIR_ROOT%\include" fib_mpir.c ^
 *      /link /LIBPATH:"%MPIR_LIB%" mpir.lib
 *
 * Usage:
 *   fib_mpir.exe 10000000000 F_10000000000.txt
 *
 * This source intentionally uses fast doubling and recursive decimal output.
 * It does not call mpz_fib_ui because unsigned long is only 32 bits on Win64.
 */

#define _CRT_SECURE_NO_WARNINGS
#include <mpir.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DECIMAL_LEAF 4000000U

typedef struct Pow10Entry {
    size_t exponent;
    mpz_t value;
    struct Pow10Entry *next;
} Pow10Entry;

static Pow10Entry *pow10_cache = NULL;

static void clear_pow10_cache(void) {
    Pow10Entry *entry = pow10_cache;
    while (entry != NULL) {
        Pow10Entry *next = entry->next;
        mpz_clear(entry->value);
        free(entry);
        entry = next;
    }
    pow10_cache = NULL;
}

static mpz_srcptr get_pow10(size_t exponent) {
    Pow10Entry *entry;
    for (entry = pow10_cache; entry != NULL; entry = entry->next) {
        if (entry->exponent == exponent) {
            return entry->value;
        }
    }

    /* mpz_ui_pow_ui takes an unsigned long exponent. The target's decimal
       widths stay below ULONG_MAX, including on Win64. */
    if (exponent > (size_t)ULONG_MAX) {
        fprintf(stderr, "10 的幂指数超出 MPIR unsigned long 范围\n");
        return NULL;
    }

    entry = (Pow10Entry *)malloc(sizeof(*entry));
    if (entry == NULL) {
        fprintf(stderr, "无法分配 10 的幂缓存节点\n");
        return NULL;
    }
    entry->exponent = exponent;
    mpz_init(entry->value);
    mpz_ui_pow_ui(entry->value, 10UL, (unsigned long)exponent);
    entry->next = pow10_cache;
    pow10_cache = entry;
    return entry->value;
}

/* Return F(n) using the same low-live-state two-square recurrence as the
   Python program. The index itself is 64-bit, independent of Win64 long. */
static void fibonacci_two_squares(uint64_t n, mpz_t result) {
    mpz_t a, am1, t1, t2, x, y, z;
    int top = 63;
    int k_is_odd = 1;

    if (n == 0) {
        mpz_set_ui(result, 0UL);
        return;
    }

    while (top > 0 && ((n >> top) & 1U) == 0U) {
        --top;
    }

    mpz_inits(a, am1, t1, t2, x, y, z, NULL);
    mpz_set_ui(a, 1UL);      /* F(1) */
    mpz_set_ui(am1, 0UL);    /* F(0) */

    for (int i = top - 1; i >= 0; --i) {
        const unsigned int next_bit = (unsigned int)((n >> i) & 1U);

        mpz_mul(t1, a, a);
        mpz_mul(t2, am1, am1);

        /* x=F(2k+1), z=F(2k-1), y=F(2k). */
        mpz_mul_2exp(x, t1, 2);
        mpz_sub(x, x, t2);
        if (k_is_odd) {
            mpz_sub_ui(x, x, 2UL);
        } else {
            mpz_add_ui(x, x, 2UL);
        }
        mpz_add(z, t1, t2);
        mpz_sub(y, x, z);

        if (next_bit != 0U) {
            mpz_set(a, x);
            mpz_set(am1, y);
            k_is_odd = 1;
        } else {
            mpz_set(a, y);
            mpz_set(am1, z);
            k_is_odd = 0;
        }
    }

    mpz_set(result, a);
    mpz_clears(a, am1, t1, t2, x, y, z, NULL);
}

static int write_decimal(FILE *out, mpz_srcptr value, size_t width) {
    if (width <= DECIMAL_LEAF) {
        char *buffer = (char *)malloc(width + 1U);
        size_t digits;
        if (buffer == NULL) {
            fprintf(stderr, "无法分配十进制叶块缓冲区\n");
            return 0;
        }
        mpz_get_str(buffer, 10, value);
        digits = strlen(buffer);
        if (digits > width) {
            free(buffer);
            fprintf(stderr, "内部错误：十进制块超过预期宽度\n");
            return 0;
        }
        for (size_t i = digits; i < width; ++i) {
            if (fputc('0', out) == EOF) {
                free(buffer);
                return 0;
            }
        }
        if (fwrite(buffer, 1, digits, out) != digits) {
            free(buffer);
            return 0;
        }
        free(buffer);
        return 1;
    }

    {
        const size_t low_width = width / 2U;
        const size_t high_width = width - low_width;
        mpz_srcptr divisor = get_pow10(low_width);
        mpz_t high, low;
        int ok;
        if (divisor == NULL) {
            return 0;
        }
        mpz_inits(high, low, NULL);
        mpz_tdiv_qr(high, low, value, divisor);
        ok = write_decimal(out, high, high_width) &&
             write_decimal(out, low, low_width);
        mpz_clears(high, low, NULL);
        return ok;
    }
}

static int parse_index(const char *text, uint64_t *value) {
    char *end = NULL;
    unsigned long long parsed;
    if (text == NULL || *text == '\0' || *text == '-') {
        return 0;
    }
    errno = 0;
    parsed = strtoull(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0') {
        return 0;
    }
    *value = (uint64_t)parsed;
    return 1;
}

int main(int argc, char **argv) {
    uint64_t n;
    mpz_t result, threshold;
    size_t digits;
    FILE *out;
    const char *output_path;

    if (argc < 2 || argc > 3 || !parse_index(argv[1], &n)) {
        fprintf(stderr, "用法: %s n [输出文件]\n", argv[0]);
        return 2;
    }
    output_path = argc == 3 ? argv[2] : "fibonacci.txt";

    mpz_init(result);
    fibonacci_two_squares(n, result);

    /* mpz_sizeinbase may overestimate a non-power-of-10 by one digit.
       Correct it by comparing against 10^(digits-1). */
    digits = mpz_sizeinbase(result, 10);
    if (digits > 1U) {
        mpz_init(threshold);
        {
            mpz_srcptr p = get_pow10(digits - 1U);
            if (p == NULL) {
                mpz_clear(threshold);
                mpz_clear(result);
                clear_pow10_cache();
                return 1;
            }
            mpz_set(threshold, p);
        }
        if (mpz_cmp(result, threshold) < 0) {
            --digits;
        }
        mpz_clear(threshold);
    }
    /* Release the large digit-count correction power before output splitting. */
    clear_pow10_cache();

    out = fopen(output_path, "wb");
    if (out == NULL) {
        perror("无法创建输出文件");
        mpz_clear(result);
        clear_pow10_cache();
        return 1;
    }

    if (fprintf(out, "F(%" PRIu64 ") = ", n) < 0 ||
        !write_decimal(out, result, digits) || fputc('\n', out) == EOF ||
        fflush(out) != 0) {
        fprintf(stderr, "写入失败；请检查磁盘空间和目标文件权限\n");
        fclose(out);
        mpz_clear(result);
        clear_pow10_cache();
        return 1;
    }
    if (fclose(out) != 0) {
        perror("关闭输出文件失败");
        mpz_clear(result);
        clear_pow10_cache();
        return 1;
    }

    printf("F(%" PRIu64 ") 已写入 %s，共 %zu 位。\n", n, output_path, digits);
    mpz_clear(result);
    clear_pow10_cache();
    return 0;
}
