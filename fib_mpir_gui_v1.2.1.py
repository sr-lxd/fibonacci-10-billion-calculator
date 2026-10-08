"""Simple Windows GUI for the MPIR Fibonacci calculator, version 1.2.1."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_VERSION = "1.2.1"
ENGINE_NAME = "fib_mpir_v1.1.0.exe"
DEFAULT_N = "10000000000"


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def engine_path() -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", app_directory())) / ENGINE_NAME
        if bundled.exists():
            return bundled
    return app_directory() / ENGINE_NAME


def icon_path() -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", app_directory())) / "s2.ico"
        if bundled.exists():
            return bundled
    return app_directory() / "s2.ico"


class FibonacciGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"斐波那契计算器 v{APP_VERSION}（MPIR）")
        self.geometry("760x540")
        self.minsize(660, 480)
        icon = icon_path()
        if icon.is_file():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.output_path = tk.StringVar(value=str(app_directory() / f"F_{DEFAULT_N}.txt"))
        self.index = tk.StringVar(value=DEFAULT_N)
        self.index.trace_add("write", self._sync_output_filename)
        self.status = tk.StringVar(value="就绪。选择下标和结果文件后开始计算。")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None
        self.started_at = 0.0
        self._make_widgets()
        self.after(150, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _make_widgets(self) -> None:
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="斐波那契数列计算器", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        ttk.Label(frame, text=f"Windows x64 · MPIR 引擎 · GUI v{APP_VERSION}", foreground="#555").pack(anchor="w", pady=(2, 16))

        form = ttk.Frame(frame)
        form.pack(fill="x")
        ttk.Label(form, text="计算下标 n").grid(row=0, column=0, sticky="w", pady=5)
        self.index_entry = ttk.Entry(form, textvariable=self.index, width=30)
        self.index_entry.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=5)
        ttk.Label(form, text="结果文件").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.output_path, state="readonly").grid(row=1, column=1, sticky="ew", padx=(12, 8), pady=5)
        self.browse_button = ttk.Button(form, text="选择目录…", command=self._browse)
        self.browse_button.grid(row=1, column=2, pady=5)
        form.columnconfigure(1, weight=1)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 10))
        self.start_button = ttk.Button(buttons, text="开始计算", command=self._start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="停止", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.open_button = ttk.Button(buttons, text="打开结果所在文件夹", command=self._open_folder, state="disabled")
        self.open_button.pack(side="left")

        ttk.Label(frame, textvariable=self.status, wraplength=710).pack(fill="x", pady=(3, 7))
        self.progress = ttk.Progressbar(frame, mode="indeterminate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 12))
        ttk.Label(frame, text="运行记录").pack(anchor="w")
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True, pady=(5, 0))
        self.log = tk.Text(log_frame, height=13, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._append_log("提示：计算 100 亿项会生成约 2.09 GB 文件，请确认磁盘空间充足。")

    def _sync_output_filename(self, *_args: object) -> None:
        value = self.index.get().strip()
        if not re.fullmatch(r"[0-9]+", value):
            return
        current = self.output_path.get().strip()
        directory = Path(current).parent if current else app_directory()
        self.output_path.set(str(directory / f"F_{int(value)}.txt"))

    def _browse(self) -> None:
        folder = filedialog.askdirectory(
            title="选择结果文件夹", initialdir=str(Path(self.output_path.get()).parent),
            mustexist=True,
        )
        if folder:
            self.output_path.set(str(Path(folder) / Path(self.output_path.get()).name))

    def _start(self) -> None:
        try:
            n = int(self.index.get().strip())
            if n < 0 or n > 18446744073709551615:
                raise ValueError
        except ValueError:
            messagebox.showerror("输入有误", "请输入 0 到 18446744073709551615 之间的整数下标。")
            return
        engine = engine_path()
        if not engine.is_file():
            messagebox.showerror("找不到计算引擎", f"未找到：\n{engine}\n\n请将 {ENGINE_NAME} 放在 GUI 同一文件夹，或使用打包版。")
            return
        output_text = self.output_path.get().strip()
        if not output_text:
            messagebox.showerror("缺少文件路径", "请选择结果文件的保存位置。")
            return
        output = Path(output_text).expanduser().resolve()
        if output.exists() and not messagebox.askyesno("覆盖文件", f"文件已存在，计算结果会覆盖它：\n{output}\n\n继续吗？"):
            return
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            self.process = subprocess.Popen(
                [str(engine), str(n), str(output)], cwd=str(output.parent),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="mbcs", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法启动", str(exc))
            self.process = None
            return

        self.started_at = time.monotonic()
        self._set_running(True)
        self.status.set(f"正在计算 F({n})。计算阶段会显示当前层数；这不代表时间百分比。")
        self._append_log(f"开始：F({n}) → {output}")
        self.reader = threading.Thread(target=self._read_output, args=(self.process,), daemon=True)
        self.reader.start()
        self.progress.start(12)

    def _read_output(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self.events.put(("line", line.rstrip()))
        code = proc.wait()
        self.events.put(("exit", code))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "line":
                    line = str(value)
                    self._append_log(line)
                    match = re.search(r"十进制转换与写盘：([\d.]+)%", line)
                    if match:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=100, value=float(match.group(1)))
                        self.status.set(line)
                    elif "Fibonacci 大整数运算" in line or "校正十进制位数" in line:
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                        self.status.set(line)
                    elif "开始分治十进制转换" in line:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=100, value=0)
                        self.status.set("开始十进制转换和写盘，稍后显示已处理比例。")
                    elif "[完成]" in line:
                        self.status.set(line)
                elif kind == "exit":
                    code = int(value)
                    self.progress.stop()
                    self._set_running(False)
                    elapsed = time.monotonic() - self.started_at
                    if code == 0:
                        self.progress.configure(mode="determinate", value=100)
                        self.status.set(f"计算完成，用时 {elapsed / 60:.1f} 分钟。结果已保存到：{self.output_path.get()}")
                        self.open_button.configure(state="normal")
                    else:
                        self.status.set(f"计算引擎已退出，代码 {code}。请查看运行记录和磁盘空间。")
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _cancel(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        if messagebox.askyesno("停止计算", "停止会中断计算，并可能留下不完整的结果文件。确定停止吗？"):
            self.process.terminate()
            self.status.set("正在停止计算…不完整的结果文件需要手动删除。")

    def _open_folder(self) -> None:
        path = Path(self.output_path.get()).expanduser().resolve()
        if path.parent.exists():
            os.startfile(str(path.parent))

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.browse_button.configure(state="disabled" if running else "normal")
        self.index_entry.configure(state="disabled" if running else "normal")

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno("计算仍在运行", "关闭窗口会停止计算，并可能留下不完整结果。仍要关闭吗？"):
                return
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    FibonacciGui().mainloop()
