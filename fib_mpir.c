/*
 * Fibonacci MPIR calculator, version 1.1.0.
 * Windows x64 / MSVC; uses MPIR's GMP-compatible mpz API.
 *
 * Build:
 *   cl /O2 /W4 /I"<MPIR include dir>" /Fofib_mpir_v1.1.0.obj ^
 *      fib_mpir.c /link /OUT:fib_mpir_v1.1.0.exe ^
 *      /LIBPATH:"<MPIR library dir>" mpir.lib
 *
 * Usage:
 *   fib_mpir_v1.1.0.exe 10000000000 F_10000000000.txt
 */

#define _CRT_SECURE_NO_WARNINGS
#include <mpir.h>
#include <windows.h>
#include <process.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define APP_VERSION "1.1.0"
#define DECIMAL_LEAF 4000000U
#define HEARTBEAT_MS 10000UL

enum {
    PHASE_STARTING = 0,
    PHASE_FIBONACCI = 1,
    PHASE_DIGIT_COUNT = 2,
    PHASE_DECIMAL_OUTPUT = 3,
    PHASE_FINISHED = 4
};

typedef struct Pow10Entry {
    size_t exponent;
    mpz_t value;
    struct Pow10Entry *next;
} Pow10Entry;

static Pow10Entry *pow10_cache = NULL;
static volatile LONG g_phase = PHASE_STARTING;
static volatile LONG g_layer = 0;
static volatile LONG g_total_layers = 0;
static volatile LONG64 g_digits_written = 0;
static volatile LONG64 g_total_digits = 0;
static ULONGLONG g_started_ms = 0;
static HANDLE g_stop_event = NULL;

static void elapsed_text(char *buffer, size_t capacity) {
    const ULONGLONG seconds = (GetTickCount64() - g_started_ms) / 1000ULL;
    const unsigned long long hours = (unsigned long long)(seconds / 3600ULL);
    const unsigned long long minutes = (unsigned long long)((seconds / 60ULL) % 60ULL);
    const unsigned long long remainder = (unsigned long long)(seconds % 60ULL);
    _snprintf_s(buffer, capacity, _TRUNCATE, "%02llu:%02llu:%02llu",
                hours, minutes, remainder);
}

static unsigned __stdcall progress_worker(void *unused) {
    (void)unused;
    for (;;) {
        char elapsed[32];
        DWORD wait_result = WaitForSingleObject(g_stop_event, HEARTBEAT_MS);
        LONG phase;

        if (wait_result == WAIT_OBJECT_0) {
            break;
        }
        if (wait_result != WAIT_TIMEOUT) {
            break;
        }

        elapsed_text(elapsed, sizeof(elapsed));
        phase = InterlockedCompareExchange(&g_phase, 0, 0);
        if (phase == PHASE_FIBONACCI) {
            LONG layer = InterlockedCompareExchange(&g_layer, 0, 0);
            LONG total = InterlockedCompareExchange(&g_total_layers, 0, 0);
            printf("[运行中] Fibonacci 大整数运算：第 %ld/%ld 层；已用时 %s。层数不代表耗时比例。\n",
                   layer, total, elapsed);
        } else if (phase == PHASE_DIGIT_COUNT) {
            printf("[运行中] 正在校正十进制位数；已用时 %s。\n", elapsed);
        } else if (phase == PHASE_DECIMAL_OUTPUT) {
            LONG64 written = InterlockedCompareExchange64(&g_digits_written, 0, 0);
            LONG64 total = InterlockedCompareExchange64(&g_total_digits, 0, 0);
            double percent = total > 0 ? (100.0 * (double)written / (double)total) : 0.0;
            printf("[运行中] 十进制转换与写盘：%.1f%%（%lld / %lld 位）；已用时 %s。\n",
                   percent, (long long)written, (long long)total, elapsed);
        }
        fflush(stdout);
    }
    return 0;
}

static HANDLE start_progress_worker(void) {
    uintptr_t thread_handle;
    unsigned int thread_id = 0;

    g_stop_event = CreateEventA(NULL, TRUE, FALSE, NULL);
    if (g_stop_event == NULL) {
        return NULL;
    }
    thread_handle = _beginthreadex(NULL, 0, progress_worker, NULL, 0, &thread_id);
    if (thread_handle == 0) {
        CloseHandle(g_stop_event);
        g_stop_event = NULL;
        return NULL;
    }
    return (HANDLE)thread_handle;
}

static void stop_progress_worker(HANDLE thread_handle) {
    if (g_stop_event != NULL) {
        SetEvent(g_stop_event);
    }
    if (thread_handle != NULL) {
        WaitForSingleObject(thread_handle, INFINITE);
        CloseHandle(thread_handle);
    }
    if (g_stop_event != NULL) {
        CloseHandle(g_stop_event);
        g_stop_event = NULL;
    }
}

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

/* Fast two-square recurrence; the Fibonacci index is 64-bit on Win64. */
static void fibonacci_two_squares(uint64_t n, mpz_t result) {
    mpz_t a, am1, t1, t2, x, y, z;
    int top = 63;
    int k_is_odd = 1;

    if (n == 0) {
        InterlockedExchange(&g_total_layers, 0);
        InterlockedExchange(&g_layer, 0);
        mpz_set_ui(result, 0UL);
        return;
    }

    while (top > 0 && ((n >> top) & 1U) == 0U) {
        --top;
    }
    InterlockedExchange(&g_total_layers, top);
    InterlockedExchange(&g_layer, 0);

    mpz_inits(a, am1, t1, t2, x, y, z, NULL);
    mpz_set_ui(a, 1UL);      /* F(1) */
    mpz_set_ui(am1, 0UL);    /* F(0) */

    for (int i = top - 1; i >= 0; --i) {
        const unsigned int next_bit = (unsigned int)((n >> i) & 1U);
        LONG current = top - i;
        InterlockedExchange(&g_layer, current);

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
        InterlockedExchangeAdd64(&g_digits_written, (LONG64)width);
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
    size_t digits = 0;
    FILE *out = NULL;
    const char *output_path;
    HANDLE progress_thread = NULL;
    int result_initialized = 0;
    int threshold_initialized = 0;
    int exit_code = 1;
    char elapsed[32];

    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        printf("Fibonacci MPIR calculator v%s (Windows x64)\n", APP_VERSION);
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--help") == 0) {
        printf("Fibonacci MPIR calculator v%s\n用法: %s n [输出文件]\n",
               APP_VERSION, argv[0]);
        return 0;
    }
    if (argc < 2 || argc > 3 || !parse_index(argv[1], &n)) {
        fprintf(stderr, "用法: %s n [输出文件]；查看版本请用 --version\n", argv[0]);
        return 2;
    }
    output_path = argc == 3 ? argv[2] : "fibonacci.txt";

    g_started_ms = GetTickCount64();
    InterlockedExchange(&g_phase, PHASE_FIBONACCI);
    progress_thread = start_progress_worker();

    printf("Fibonacci MPIR calculator v%s（Windows x64）\n", APP_VERSION);
    printf("[1/3] 开始计算 F(%" PRIu64 ")。长运算期间每 10 秒显示一次状态。\n", n);
    printf("结果文件：%s\n", output_path);
    if (progress_thread == NULL) {
        printf("提示：状态刷新线程未能启动，将继续计算；完成后仍会显示结果。\n");
    }

    mpz_init(result);
    result_initialized = 1;
    fibonacci_two_squares(n, result);

    elapsed_text(elapsed, sizeof(elapsed));
    InterlockedExchange(&g_phase, PHASE_DIGIT_COUNT);
    printf("[1/3 完成] Fibonacci 整数运算完成，用时 %s。开始统计十进制位数。\n", elapsed);

    /* mpz_sizeinbase may overestimate a non-power-of-10 by one digit.
       Correct it by comparing against 10^(digits-1). */
    digits = mpz_sizeinbase(result, 10);
    if (digits > 1U) {
        mpz_init(threshold);
        threshold_initialized = 1;
        {
            mpz_srcptr p = get_pow10(digits - 1U);
            if (p == NULL) {
                fprintf(stderr, "无法完成位数校正。\n");
                goto cleanup;
            }
            mpz_set(threshold, p);
        }
        if (mpz_cmp(result, threshold) < 0) {
            --digits;
        }
        mpz_clear(threshold);
        threshold_initialized = 0;
    }
    clear_pow10_cache();

    InterlockedExchange64(&g_digits_written, 0);
    InterlockedExchange64(&g_total_digits, (LONG64)digits);
    InterlockedExchange(&g_phase, PHASE_DECIMAL_OUTPUT);
    printf("[2/3 完成] 结果共 %zu 位，预计输出约 %.2f GB。\n",
           digits, (double)digits / 1000000000.0);
    printf("[3/3] 开始分治十进制转换与写盘；每 10 秒显示已处理位数。\n");

    out = fopen(output_path, "wb");
    if (out == NULL) {
        perror("无法创建输出文件");
        goto cleanup;
    }
    if (fprintf(out, "F(%" PRIu64 ") = ", n) < 0 ||
        !write_decimal(out, result, digits) || fputc('\n', out) == EOF ||
        fflush(out) != 0) {
        fprintf(stderr, "写入失败；请检查磁盘空间和目标文件权限。\n");
        goto cleanup;
    }
    if (fclose(out) != 0) {
        out = NULL;
        perror("关闭输出文件失败");
        goto cleanup;
    }
    out = NULL;

    InterlockedExchange(&g_phase, PHASE_FINISHED);
    stop_progress_worker(progress_thread);
    progress_thread = NULL;
    elapsed_text(elapsed, sizeof(elapsed));
    printf("[完成] F(%" PRIu64 ") 已写入 %s，共 %zu 位；总用时 %s。\n",
           n, output_path, digits, elapsed);
    exit_code = 0;

cleanup:
    if (out != NULL) {
        fclose(out);
    }
    if (threshold_initialized) {
        mpz_clear(threshold);
    }
    if (progress_thread != NULL) {
        InterlockedExchange(&g_phase, PHASE_FINISHED);
        stop_progress_worker(progress_thread);
    }
    if (result_initialized) {
        mpz_clear(result);
    }
    clear_pow10_cache();
    return exit_code;
}
