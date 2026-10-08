# -*- coding: utf-8 -*-
"""斐波那契计算器 4.3

v4.3 针对 80 亿级任务 worker 以 0xC0000409（FailFast）退出进行诊断与修正：
1. 保留独立 worker：底层 GMP 即使硬退出，GUI 主进程仍保持运行。
2. 三种算法后端：自动 / 两平方 / Lucas。自动模式仍为范围内 gmpy2.fib，超限两平方。
3. 增加“仅计算诊断”模式：只计算 F(n)，完全跳过十进制转换和写盘，隔离计算阶段问题。
4. 两平方和 Lucas 后端逐层记录大乘法/平方：层号、阶段、操作数 bit 数、worker 私有提交、
   工作集、系统可用物理内存和可用 Commit；诊断日志逐条 flush + fsync，硬崩溃后仍可定位最后一步。
5. 0xC0000409 / 0xC0000017 / 0xC0000005 等 Windows 退出码转为十六进制并给出诊断提示。
6. 十进制输出沿用 v4.2：400 万位叶块、10 的幂局部缓存、分治流式写盘和主动释放父节点。

开发者：陆旭东（在 v4.2 基础上改进）
"""

import ctypes
import json
import math
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.filedialog
from tkinter import messagebox, ttk

import gmpy2


GMPY_FIB_LIMIT = 4_294_967_294  # Win64 下 gmpy2.fib 实测接口上限
DECIMAL_LEAF = 4_000_000        # 分治叶块宽度（十进制位）

BACKEND_AUTO = "auto"
BACKEND_TWO_SQUARES = "two_squares"
BACKEND_LUCAS = "lucas"

BACKEND_LABELS = {
    "自动（GMP范围内原生，超限两平方）": BACKEND_AUTO,
    "两平方（2S/层，速度优先）": BACKEND_TWO_SQUARES,
    "Lucas（M+S/层，备选/诊断）": BACKEND_LUCAS,
}
BACKEND_NAMES = {
    BACKEND_AUTO: "自动",
    BACKEND_TWO_SQUARES: "两平方",
    BACKEND_LUCAS: "Lucas",
    "gmpy2_fib": "gmpy2.fib",
}


# ------------------------- Windows / 进程资源 -------------------------

def windows_memory_info():
    """返回 (可用物理内存 GiB, 可用提交内存 GiB)。非 Windows 返回 (None, None)。"""
    if os.name != "nt":
        return None, None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    s = MEMORYSTATUSEX()
    s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
        return None, None
    gib = float(1 << 30)
    return s.ullAvailPhys / gib, s.ullAvailPageFile / gib


def process_memory_info():
    """返回当前 worker 的 (Working Set GiB, Private Commit GiB)。失败则返回 (None, None)。"""
    if os.name != "nt":
        return None, None

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), ctypes.sizeof(counters)
    )
    if not ok:
        return None, None
    gib = float(1 << 30)
    return counters.WorkingSetSize / gib, counters.PrivateUsage / gib


def _resource_text():
    avail_phys, avail_commit = windows_memory_info()
    workset, private_commit = process_memory_info()

    parts = []
    if private_commit is not None:
        parts.append(f"worker私有={private_commit:.2f}GiB")
    if workset is not None:
        parts.append(f"工作集={workset:.2f}GiB")
    if avail_phys is not None:
        parts.append(f"可用物理={avail_phys:.2f}GiB")
    if avail_commit is not None:
        parts.append(f"可用Commit={avail_commit:.2f}GiB")
    return " | ".join(parts) if parts else "资源信息不可用"


# ------------------------- Worker 日志 -------------------------

def _emit(kind, payload):
    print(json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False), flush=True)


def _hard_log(log_file, text, emit=True):
    """逐条落盘；80 亿只有几十层，fsync 开销相对大整数平方可忽略。"""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {text}"
    log_file.write(line + "\n")
    log_file.flush()
    try:
        os.fsync(log_file.fileno())
    except OSError:
        pass
    if emit:
        _emit("diag", line)


def _make_diag_callback(log_file):
    def diag(step, total, phase, operand_bits, extra=""):
        bits_text = f"operand={operand_bits:,} bits" if operand_bits is not None else "operand=?"
        extra_text = f" | {extra}" if extra else ""
        _hard_log(
            log_file,
            f"layer {step}/{total} | {phase} | {bits_text} | {_resource_text()}{extra_text}",
        )
    return diag


# ------------------------- Fibonacci 核心 -------------------------

def fib_two_squares(n, diag=None):
    """低峰值两平方算法，返回 F(n)。每层 2 次 square。"""
    if n <= 0:
        return gmpy2.mpz(0)

    a = gmpy2.mpz(1)       # F(1)
    am1 = gmpy2.mpz(0)     # F(0)
    k_odd = True
    total = max(0, n.bit_length() - 1)
    step = 0

    for i in range(n.bit_length() - 2, -1, -1):
        step += 1
        bit = (n >> i) & 1

        if diag:
            diag(step, total, "two-square #1 START", a.bit_length(), f"next_bit={bit}")
        t1 = gmpy2.square(a)
        if diag:
            diag(step, total, "two-square #1 DONE", t1.bit_length())
        del a

        if diag:
            diag(step, total, "two-square #2 START", am1.bit_length())
        t2 = gmpy2.square(am1)
        if diag:
            diag(step, total, "two-square #2 DONE", t2.bit_length())
        del am1

        # x = F(2k+1), z = F(2k-1), y = F(2k)
        x = (t1 << 2) - t2
        x = x - 2 if k_odd else x + 2
        z = t1 + t2
        del t1, t2
        y = x - z

        if bit:
            a, am1 = x, y
            k_odd = True
        else:
            a, am1 = y, z
            k_odd = False
        del x, y, z

        if diag:
            diag(step, total, "layer DONE", a.bit_length(), f"state_prev_bits={am1.bit_length():,}")

    return a


def fib_lucas(n, diag=None):
    """Lucas 链低峰值版本，返回 F(n)。每层 1 次 mul + 1 次 square。"""
    if n <= 0:
        return gmpy2.mpz(0)

    a = gmpy2.mpz(1)  # F(1)
    b = gmpy2.mpz(1)  # L(1)
    k_odd = True
    total = max(0, n.bit_length() - 1)
    step = 0

    for i in range(n.bit_length() - 2, -1, -1):
        step += 1
        bit = (n >> i) & 1

        if diag:
            diag(step, total, "Lucas MUL START", max(a.bit_length(), b.bit_length()), f"next_bit={bit}")
        c = a * b                     # F(2k)
        if diag:
            diag(step, total, "Lucas MUL DONE", c.bit_length())
        del a

        if diag:
            diag(step, total, "Lucas SQUARE START", b.bit_length())
        t = gmpy2.square(b)
        if diag:
            diag(step, total, "Lucas SQUARE DONE", t.bit_length())
        del b

        d = t + 2 if k_odd else t - 2  # L(2k)
        del t

        if bit:
            # F(m+1)=(F(m)+L(m))/2；L(m+1)=(5F(m)+L(m))/2，m=2k
            a1 = (c + d) >> 1
            b1 = (5 * c + d) >> 1
            del c, d
            a, b = a1, b1
            k_odd = True
        else:
            a, b = c, d
            k_odd = False

        if diag:
            diag(step, total, "layer DONE", a.bit_length(), f"lucas_bits={b.bit_length():,}")

    return a


def fibonacci(n, backend=BACKEND_AUTO, diag=None):
    """返回 (F(n), 实际使用后端名)。"""
    if backend == BACKEND_AUTO:
        if n <= GMPY_FIB_LIMIT:
            if diag:
                diag(0, 0, "gmpy2.fib START", None, "GMP内部算法不可逐层观测")
            value = gmpy2.fib(n)
            if diag:
                diag(0, 0, "gmpy2.fib DONE", value.bit_length())
            return value, "gmpy2_fib"
        backend = BACKEND_TWO_SQUARES

    if backend == BACKEND_TWO_SQUARES:
        return fib_two_squares(n, diag), BACKEND_TWO_SQUARES
    if backend == BACKEND_LUCAS:
        return fib_lucas(n, diag), BACKEND_LUCAS
    raise ValueError(f"未知算法后端：{backend}")


# ------------------------- 位数与十进制输出 -------------------------

_LOG10_PHI = None
_LOG10_SQRT5 = None


def fib_digits(n):
    """F(n) 的十进制位数；MPFR 256 bit，不构造同级大整数。"""
    global _LOG10_PHI, _LOG10_SQRT5
    if n <= 1:
        return 1
    if _LOG10_PHI is None:
        with gmpy2.context(precision=256):
            sqrt5 = gmpy2.sqrt(gmpy2.mpfr(5))
            _LOG10_PHI = gmpy2.log10((1 + sqrt5) / 2)
            _LOG10_SQRT5 = gmpy2.log10(sqrt5)
    with gmpy2.context(precision=256):
        approx = gmpy2.mpfr(n) * _LOG10_PHI - _LOG10_SQRT5
    return int(gmpy2.floor(approx)) + 1


def _get_pow10(k, cache):
    p = cache.get(k)
    if p is None:
        p = gmpy2.mpz(10) ** k
        cache[k] = p
    return p


def _write_dec(f, val, width, cache):
    """分治十进制转换并流式写盘。"""
    if width <= DECIMAL_LEAF:
        s = gmpy2.digits(val, 10)
        pad = width - len(s)
        if pad > 0:
            f.write("0" * pad)
        f.write(s)
        return

    half = width // 2
    p = _get_pow10(half, cache)
    hi, lo = gmpy2.f_divmod(val, p)
    del val, p

    _write_dec(f, hi, width - half, cache)
    del hi
    _write_dec(f, lo, half, cache)
    del lo


# ------------------------- 资源估算 -------------------------

def estimate_burden(n, backend=BACKEND_AUTO):
    digits = fib_digits(n)
    result_gib = digits * math.log2(10) / 8 / (1 << 30)
    output_gib = digits / (1 << 30)

    # 只作为保守预留提示。不同 GMP 乘法阈值/页面文件设置会改变真实峰值。
    factor = 12.0 if backend != BACKEND_LUCAS else 10.0
    recommended_commit_gib = max(4.0, result_gib * factor)
    return digits, result_gib, output_gib, recommended_commit_gib


# ------------------------- Worker 子进程 -------------------------

def worker_main(n, mode, backend, outfile, logfile):
    """mode=full 或 compute_only。硬崩溃由 GUI 根据 worker 退出码诊断。"""
    log_file = None
    try:
        log_file = open(logfile, "w", encoding="utf-8", buffering=1)
        _hard_log(log_file, f"v4.3 worker start | n={n:,} | mode={mode} | backend={backend}")
        _hard_log(log_file, f"Python={sys.version.split()[0]} | pointer={struct.calcsize('P') * 8}bit | gmpy2={gmpy2.version()}")
        _hard_log(log_file, f"启动资源 | {_resource_text()}")

        diag = _make_diag_callback(log_file)
        t0 = time.perf_counter()
        _emit("stage", f"独立进程：Fibonacci 运算中（后端={BACKEND_NAMES.get(backend, backend)}）…")
        fib_n, actual_backend = fibonacci(n, backend, diag)
        t1 = time.perf_counter()

        ndigits = fib_digits(n)
        bit_count = fib_n.bit_length()
        tail100 = str(fib_n % (gmpy2.mpz(10) ** 100)).zfill(min(100, ndigits))
        _hard_log(
            log_file,
            f"Fibonacci完成 | actual_backend={BACKEND_NAMES.get(actual_backend, actual_backend)} | "
            f"time={t1 - t0:.3f}s | bits={bit_count:,} | digits={ndigits:,} | {_resource_text()}",
        )

        if mode == "compute_only":
            _emit("final", format_duration(t1 - t0))
            _emit(
                "done",
                f"仅计算诊断完成！F({n}) 已成功生成。\n"
                f"实际后端：{BACKEND_NAMES.get(actual_backend, actual_backend)}\n"
                f"Fibonacci 运算时间：{t1 - t0:.1f}s\n"
                f"二进制位数：{bit_count:,}\n"
                f"十进制位数：{ndigits:,}\n"
                f"后 100 位：...{tail100}\n"
                f"未进行十进制全文转换/写盘。\n"
                f"诊断日志：{logfile}\n",
            )
            del fib_n
            _hard_log(log_file, "compute_only 正常结束", emit=False)
            return 0

        _emit("stage", f"Fibonacci 完成（{t1 - t0:.1f}s），开始分治十进制转换+写盘（{ndigits:,} 位）…")
        _hard_log(log_file, f"decimal START | leaf={DECIMAL_LEAF:,} | {_resource_text()}")

        cache = {}
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(f"输入数字: {n}\n斐波那契值共 {ndigits} 位。\n\n")
            _write_dec(f, fib_n, ndigits, cache)
            f.write("\n")

        del fib_n
        cache.clear()
        del cache
        t2 = time.perf_counter()
        _hard_log(log_file, f"decimal DONE | time={t2 - t1:.3f}s | {_resource_text()}")

        with open(outfile, "r", encoding="utf-8") as f:
            head = f.read(300)
        head100 = head.split("\n\n", 1)[1][:100]

        _emit("final", format_duration(t2 - t0))
        _emit(
            "done",
            f"计算完成！F({n}) 共 {ndigits:,} 位。\n"
            f"实际后端：{BACKEND_NAMES.get(actual_backend, actual_backend)}\n"
            f"【分项计时】Fibonacci {t1 - t0:.1f}s ｜ 十进制转换+写盘 {t2 - t1:.1f}s ｜ 总计 {t2 - t0:.1f}s\n"
            f"前 100 位：{head100}...\n"
            f"后 100 位：...{tail100}\n"
            f"完整结果：{outfile}\n"
            f"诊断日志：{logfile}\n",
        )
        _hard_log(log_file, "full 正常结束", emit=False)
        return 0
    except BaseException as exc:
        if log_file is not None:
            try:
                _hard_log(log_file, f"Python异常：{type(exc).__name__}: {exc}", emit=False)
            except Exception:
                pass
        _emit("error", f"{type(exc).__name__}: {exc}\n诊断日志：{logfile}")
        return 1
    finally:
        if log_file is not None:
            try:
                log_file.close()
            except Exception:
                pass


def explain_exit_code(rc):
    code = rc & 0xFFFFFFFF
    hexcode = f"0x{code:08X}"
    notes = {
        0xC0000409: "Windows FailFast。常见于底层运行库主动终止/abort；单凭该码不能断定是栈溢出。结合本程序应优先检查最后一条 GMP 大乘法/平方日志和 Commit 余量。",
        0xC0000017: "STATUS_NO_MEMORY：系统无法满足内存/提交请求。",
        0xC0000005: "STATUS_ACCESS_VIOLATION：底层原生代码发生访问冲突。",
    }
    return hexcode, notes.get(code, "非零原生退出码；请结合诊断日志最后一条记录定位。")


def run_worker_subprocess(n, mode, backend, outfile, logfile, q, stop_event):
    """GUI 中启动独立 worker。"""
    cmd = [
        sys.executable,
        os.path.abspath(__file__),
        "--worker",
        str(n),
        mode,
        backend,
        outfile if outfile else "-",
        logfile,
        "v43",
    ]

    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    plain_lines = []
    got_terminal_message = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if not line:
                continue
            try:
                msg = json.loads(line)
                kind = msg.get("kind")
                payload = msg.get("payload", "")
                if kind in {"stage", "diag", "final", "done", "error"}:
                    q.put((kind, payload))
                    if kind in {"done", "error"}:
                        got_terminal_message = True
                    continue
            except json.JSONDecodeError:
                pass

            plain_lines.append(line)
            plain_lines = plain_lines[-12:]

        rc = proc.wait()
        if rc != 0 and not got_terminal_message:
            report = build_crash_report(n, mode, rc, plain_lines, logfile)
            q.put(("error", report))
        elif rc == 0 and not got_terminal_message:
            q.put(("error", f"计算子进程已结束，但没有返回完成消息。\n诊断日志：{logfile}"))
    except Exception as exc:
        q.put(("error", f"启动计算子进程失败：{type(exc).__name__}: {exc}"))
    finally:
        stop_event.set()


# ------------------------- 崩溃诊断报告 -------------------------

def parse_diag_log(logfile):
    """解析逐层诊断日志，提取崩溃时的关键事实。
    返回 dict：last_layer_done / pending(START 后无 DONE 的运算) /
    last_mem_phys / last_mem_commit / gmp_size。
    """
    state = {
        "last_layer_done": None,
        "pending": None,
        "last_mem_phys": None,
        "last_mem_commit": None,
        "gmp_size": None,
    }
    try:
        with open(logfile, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.search(r"layer (\d+)/(\d+) \| (.+?) \| operand=([\d,]+) bits", line)
                if m:
                    step, total = int(m.group(1)), int(m.group(2))
                    phase = m.group(3).strip()
                    operand = int(m.group(4).replace(",", ""))
                    if phase == "layer DONE":
                        state["last_layer_done"] = (step, total, operand)
                        state["pending"] = None
                    elif phase.endswith("START"):
                        state["pending"] = (step, total, phase[:-6].strip(), operand)
                    else:
                        state["pending"] = None
                m = re.search(r"可用物理=([\d.]+)GiB \| 可用Commit=([\d.]+)GiB", line)
                if m:
                    state["last_mem_phys"] = float(m.group(1))
                    state["last_mem_commit"] = float(m.group(2))
                m = re.search(r"GNU MP: Cannot allocate memory \(size=(\d+)\)", line)
                if m:
                    state["gmp_size"] = int(m.group(1))
    except OSError:
        pass
    return state


def build_crash_report(n, mode, rc, plain_lines, logfile):
    """worker 硬退出时，自动解析诊断日志，生成一份直接可读的结论报告。"""
    facts = parse_diag_log(logfile)
    # GNU MP 的 stderr 报错不在诊断日志里（走子进程 stdout 管道），从 plain_lines 补齐
    for line in plain_lines:
        m = re.search(r"GNU MP: Cannot allocate memory \(size=(\d+)\)", line)
        if m and facts["gmp_size"] is None:
            facts["gmp_size"] = int(m.group(1))
    try:
        _, _, _, recommended_gib = estimate_burden(n)
    except Exception:
        recommended_gib = None
    hexcode = f"0x{rc & 0xFFFFFFFF:08X}"
    _, explanation = explain_exit_code(rc)

    parts = [f"【计算中断诊断报告】F({n:,}) — {mode} 模式", ""]

    parts.append("■ 中断位置")
    if facts["pending"]:
        step, total, phase, operand = facts["pending"]
        parts.append(f"  第 {step}/{total} 层的「{phase}」")
        parts.append(f"  操作数 {operand:,} bit（约 {operand / 8 / 2 ** 20:.0f} MiB）")
        parts.append("  该运算 START 后未返回 DONE——进程死于此步。")
    elif facts["last_layer_done"]:
        s, t, o = facts["last_layer_done"]
        parts.append(f"  第 {s}/{t} 层已完成（operand={o:,} bits），之后在后续阶段中断。")
    else:
        parts.append("  诊断日志为空或未记录到任何完成的层。")
    parts.append("")

    parts.append("■ 底层报错与退出码")
    if facts["gmp_size"]:
        gib = facts["gmp_size"] / 2 ** 30
        parts.append(f"  GNU MP: Cannot allocate memory (size={facts['gmp_size']:,} ≈ {gib:.2f} GiB)")
    parts.append(f"  退出码 {rc}（{hexcode}）— {explanation}")
    if facts["gmp_size"]:
        parts.append("  （注意：Windows LLP64 下此 size 可能是 32 位截断值，")
        parts.append("    真实申请量可能是它的 2~3 倍。）")
    parts.append("")

    parts.append("■ 失败时刻资源")
    if facts["last_mem_phys"] is not None:
        parts.append(
            f"  可用物理内存 {facts['last_mem_phys']:.2f} GiB ｜ "
            f"可用提交内存 {facts['last_mem_commit']:.2f} GiB"
        )
        if facts["gmp_size"] and facts["last_mem_commit"] > facts["gmp_size"] / 2 ** 30:
            parts.append("  可用提交内存明显高于 GMP 请求值——不是资源耗尽。")
    else:
        parts.append("  日志未记录到内存信息。")
    if recommended_gib:
        parts.append(f"  本任务建议预留提交内存约 {recommended_gib:.1f} GiB。")
    parts.append("")

    parts.append("■ 判定")
    if facts["gmp_size"] and facts["last_mem_commit"] and facts["last_mem_commit"] > facts["gmp_size"] / 2 ** 30:
        parts.append("  Windows LLP64 构建下 GMP 的已知边界：缓冲大小以 32 位")
        parts.append("  long 计算，超大 FFT 需求溢出后分配失败并直接终止进程。")
        parts.append("  实测 gmpy2 2.2.1 与 2.3.1 行为一字不差；")
        parts.append("  WSL2 Ubuntu（LP64）同一计算可完整通过。")
    else:
        parts.append("  结合上方资源数据判断：若可用内存确实不足，")
        parts.append("  请关闭占用提交内存的程序或增大页面文件后重试。")
    parts.append("")

    parts.append("■ 可行方案")
    parts.append("  1. WSL2 运行（已实测通过 80 亿、100 亿）——复制本命令替换 n：")
    parts.append(
        '     wsl -d Ubuntu --cd ~ -- python3 "/mnt/d/SoftWare/00陆旭东自编程序/'
        '斐波那契计算器/斐波那契计算器v4.3.py" --worker '
        f"{n} {mode} auto \"<输出文件>\" \"<诊断日志>\" v1"
    )
    parts.append("  2. 关闭占用提交内存的大程序后重试")
    parts.append("  3. 增大 Windows 页面文件（此路径未验证有效，优先用方案 1）")
    parts.append("")
    parts.append(f"■ 诊断日志：{logfile}")

    report = "\n".join(parts)
    try:
        with open(logfile + ".crash_report.txt", "w", encoding="utf-8") as f:
            f.write(report + "\n\n--- 子进程最后输出 ---\n")
            f.write("\n".join(plain_lines) + "\n")
    except OSError:
        pass
    return report


# ------------------------- GUI -------------------------

def format_duration(seconds):
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{days}天{hours}小时{minutes}分{secs}秒"


def update_elapsed_time(start_time, q, stop_event):
    while not stop_event.is_set():
        q.put(("time", format_duration(time.time() - start_time)))
        time.sleep(1)


def check_queue(q, time_label, stage_label):
    try:
        while True:
            kind, payload = q.get_nowait()
            if kind == "time":
                time_label.config(text=payload)
            elif kind == "stage":
                stage_label.config(text=payload)
            elif kind == "diag":
                # 只显示最新诊断行；完整历史保存在日志，避免 Text 越来越大。
                stage_label.config(text=f"阶段：{payload[-180:]}")
            elif kind == "final":
                final_time_label.config(text=f"最终用掉的时间：{payload}")
            elif kind == "done":
                result_text.insert(tk.END, payload)
                calculate_button.config(state=tk.NORMAL)
                stage_label.config(text="阶段：完成")
                return
            elif kind == "error":
                messagebox.showerror("计算中止", payload)
                result_text.insert(tk.END, payload + "\n")
                calculate_button.config(state=tk.NORMAL)
                stage_label.config(text="阶段：已中止")
                return
    except queue.Empty:
        pass
    root.after(200, check_queue, q, time_label, stage_label)


def calculate(event=None):
    stop_event = threading.Event()
    try:
        n = int(number_entry.get())
    except ValueError:
        messagebox.showerror("错误", "请输入一个整数")
        return

    if n < 0:
        messagebox.showerror("错误", "请输入非负整数")
        return

    pointer_bits = struct.calcsize("P") * 8
    if pointer_bits < 64 and n > 1_000_000_000:
        messagebox.showerror(
            "需要 64 位 Python",
            f"当前 Python 为 {pointer_bits} 位。几十亿级大整数任务必须使用 64 位 Python/gmpy2。",
        )
        return

    backend = BACKEND_LABELS.get(backend_var.get(), BACKEND_AUTO)
    mode = "compute_only" if compute_only_var.get() else "full"

    if n > 100_000_000:
        digits, result_gib, output_gib, recommended_commit = estimate_burden(n, backend)
        avail_phys, avail_commit = windows_memory_info()

        mem_line = (
            f"F({n}) 约 {digits:,} 位。\n"
            f"最终 mpz 数据本体约 {result_gib:.2f} GiB；"
            f"完整十进制文本约 {output_gib:.2f} GiB。\n"
            f"选择后端：{BACKEND_NAMES.get(backend, backend)}；"
            f"运行模式：{'仅计算诊断' if mode == 'compute_only' else '完整计算+写盘'}。\n"
            f"建议至少留出约 {recommended_commit:.1f} GiB 可用 Commit（保守值，不是精确峰值）。"
        )
        if avail_phys is not None and avail_commit is not None:
            mem_line += (
                f"\n当前可用物理内存约 {avail_phys:.1f} GiB；"
                f"可用 Commit 约 {avail_commit:.1f} GiB。"
            )
            if avail_commit < recommended_commit:
                mem_line += "\n\n警告：当前可用 Commit 低于建议值，GMP 可能再次 FailFast。"

        mem_line += (
            "\n\nv4.3 会逐层记录大乘法/平方和内存状态；即使 worker 硬退出，GUI 与诊断日志仍保留。"
            "\n确定继续吗？"
        )
        if not messagebox.askyesno("大任务确认", mem_line):
            return

    if mode == "full":
        outfile = tk.filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"F_{n}.txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not outfile:
            return
        logfile = outfile + ".diagnostic.log"
    else:
        outfile = ""
        logfile = tk.filedialog.asksaveasfilename(
            defaultextension=".log",
            initialfile=f"F_{n}_{backend}_diagnostic.log",
            filetypes=[("Log Files", "*.log"), ("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not logfile:
            return

    result_text.delete("1.0", tk.END)
    calculate_button.config(state=tk.DISABLED)
    final_time_label.config(text="最终用掉的时间：计算中")
    stage_label.config(text="阶段：启动独立计算进程…")
    start_time = time.time()

    result_text.insert(
        tk.END,
        f"任务：F({n})\n后端：{BACKEND_NAMES.get(backend, backend)}\n"
        f"模式：{'仅计算诊断' if mode == 'compute_only' else '完整计算+写盘'}\n"
        f"诊断日志：{logfile}\n\n",
    )

    event_queue = queue.Queue()
    timer_thread = threading.Thread(
        target=update_elapsed_time,
        args=(start_time, event_queue, stop_event),
        daemon=True,
    )
    timer_thread.start()

    monitor_thread = threading.Thread(
        target=run_worker_subprocess,
        args=(n, mode, backend, outfile, logfile, event_queue, stop_event),
        daemon=True,
    )
    monitor_thread.start()

    root.after(200, check_queue, event_queue, time_label, stage_label)


def refresh_results():
    result_text.delete("1.0", tk.END)


def show_instructions():
    messagebox.showinfo(
        "使用说明",
        """
4.3 版升级说明（针对 80 亿 worker 退出码 0xC0000409）：

1. 后端可选：
   · 自动：n ≤ 4,294,967,294 用 gmpy2.fib；更大 n 用两平方。
   · 两平方：强制使用 2S/层算法，用于速度基准和超限计算。
   · Lucas：强制使用 M+S/层算法，用于与两平方比较及超大规模诊断。

2. “仅计算诊断”模式：
   只生成 F(n)，不做十进制全文转换、不写巨大结果文件。
   用它先测试 50、60、70、75、80 亿，可把计算阶段与输出阶段完全分离。

3. 逐层诊断：
   两平方会分别记录 square #1/#2 的 START/DONE；Lucas 会记录 MUL/SQUARE 的 START/DONE。
   每条同时记录 operand bit 数、worker 私有 Commit、工作集、可用物理内存、可用 Commit。
   日志逐条 flush + fsync；即使 worker FailFast，最后一条记录通常仍能保留。

4. 如果日志最后停在：
   “... START” 且没有对应 “... DONE”，说明硬退出发生在该次 GMP 大乘法/平方内部。
   对照当时“可用Commit”即可判断是否接近内存/提交阈值。

5. 完整模式仍使用 400 万位叶块的分治十进制转换和流式写盘。

建议诊断顺序：
先选择“两平方 + 仅计算诊断”跑 80 亿；若仍 0xC0000409，再选择“Lucas + 仅计算诊断”跑同一 n。
比较两个日志最后成功层和峰值 Commit，即可判断 Lucas 是否能以较低峰值跨过 80 亿。
""",
    )


def main():
    global root, result_text, number_entry, calculate_button
    global final_time_label, mainframe, time_label, stage_label
    global backend_var, compute_only_var

    root = tk.Tk()
    root.title("斐波那契计算器4.3 双后端+FailFast逐层诊断。 开发者：陆旭东 版权所有@2026")

    mainframe = ttk.Frame(root, padding="10")
    mainframe.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    ttk.Label(mainframe, text="输入整数：").grid(column=0, row=0, sticky=tk.W)
    number_entry = ttk.Entry(mainframe)
    number_entry.grid(column=1, row=0, sticky=(tk.W, tk.E))
    number_entry.bind("<Return>", calculate)

    backend_var = tk.StringVar(value="自动（GMP范围内原生，超限两平方）")
    ttk.Label(mainframe, text="算法后端：").grid(column=0, row=1, sticky=tk.W)
    backend_box = ttk.Combobox(
        mainframe,
        textvariable=backend_var,
        values=list(BACKEND_LABELS.keys()),
        state="readonly",
        width=36,
    )
    backend_box.grid(column=1, row=1, columnspan=2, sticky=(tk.W, tk.E))

    compute_only_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        mainframe,
        text="仅计算诊断（不进行十进制全文转换/写盘）",
        variable=compute_only_var,
    ).grid(column=3, row=1, columnspan=3, sticky=tk.W)

    calculate_button = ttk.Button(mainframe, text="开始计算", command=calculate)
    calculate_button.grid(column=2, row=0, sticky=tk.W)
    ttk.Button(mainframe, text="使用说明", command=show_instructions).grid(column=3, row=0, sticky=tk.W)
    ttk.Button(mainframe, text="刷新结果", command=refresh_results).grid(column=4, row=0, sticky=tk.W)

    result_frame = ttk.Frame(mainframe)
    result_frame.grid(column=0, row=2, columnspan=6, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(8, 0))
    result_text = tk.Text(result_frame)
    result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar = ttk.Scrollbar(result_frame, command=result_text.yview)
    result_text.config(yscrollcommand=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    stage_label = ttk.Label(mainframe, text="阶段：待机")
    stage_label.grid(column=0, row=3, columnspan=6, sticky=(tk.W, tk.E))
    time_label = ttk.Label(mainframe, text="已用时间：0天0小时0分钟0秒")
    time_label.grid(column=0, row=4, columnspan=6, sticky=(tk.W, tk.E))
    final_time_label = ttk.Label(mainframe, text="最终用掉的时间：0天0小时0分0秒")
    final_time_label.grid(column=0, row=5, columnspan=6, sticky=(tk.W, tk.E))

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    mainframe.columnconfigure(1, weight=1)
    mainframe.rowconfigure(2, weight=1)
    root.mainloop()


def direct_cli(n, outfile, backend=BACKEND_AUTO):
    """兼容普通 CLI：python v4.3.py n outfile [auto|two_squares|lucas]。"""
    if n < 0:
        raise ValueError("n 必须为非负整数")
    t0 = time.perf_counter()
    fib_n, actual = fibonacci(n, backend)
    t1 = time.perf_counter()
    nd = fib_digits(n)
    cache = {}
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(f"输入数字: {n}\n斐波那契值共 {nd} 位。\n\n")
        _write_dec(f, fib_n, nd, cache)
        f.write("\n")
    t2 = time.perf_counter()
    print(
        f"F({n}) {nd} digits | backend={BACKEND_NAMES.get(actual, actual)} | "
        f"fib {t1 - t0:.1f}s | dec+write {t2 - t1:.1f}s -> {outfile}"
    )


if __name__ == "__main__":
    if len(sys.argv) == 8 and sys.argv[1] == "--worker":
        try:
            _n = int(sys.argv[2])
            _mode = sys.argv[3]
            _backend = sys.argv[4]
            _outfile = "" if sys.argv[5] == "-" else sys.argv[5]
            _logfile = sys.argv[6]
            # sys.argv[7] 保留位，当前用于协议版本，便于后续扩展。
            _protocol = sys.argv[7]
            if _n < 0:
                raise ValueError("n 必须为非负整数")
            if _mode not in {"full", "compute_only"}:
                raise ValueError(f"未知 mode: {_mode}")
            if _backend not in {BACKEND_AUTO, BACKEND_TWO_SQUARES, BACKEND_LUCAS}:
                raise ValueError(f"未知 backend: {_backend}")
        except Exception as _exc:
            _emit("error", f"{type(_exc).__name__}: {_exc}")
            sys.exit(1)
        _rc = worker_main(_n, _mode, _backend, _outfile, _logfile)
        sys.exit(_rc)
    elif len(sys.argv) in {3, 4}:
        _backend = sys.argv[3] if len(sys.argv) == 4 else BACKEND_AUTO
        direct_cli(int(sys.argv[1]), sys.argv[2], _backend)
    else:
        main()
