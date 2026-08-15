#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESRI Wayback 历史影像获取工具 - GUI"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import subprocess
import threading
import queue
import signal
import re
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("ESRI Wayback 历史影像获取")
        self.root.geometry("700x540")
        self.root.minsize(620, 460)
        self.process = None
        self.log_queue = queue.Queue()
        self._stopping = False

        # 样式
        style = ttk.Style()
        if 'vista' in style.theme_names():
            style.theme_use('vista')

        main_frame = ttk.Frame(root, padding="12")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== 标题 =====
        header = ttk.Frame(main_frame)
        header.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(header, text="ESRI Wayback 历史影像获取",
                  font=('Segoe UI', 15, 'bold')).pack(side=tk.LEFT)

        # ===== 坐标 =====
        grp_coord = ttk.LabelFrame(main_frame, text="坐标", padding="10")
        grp_coord.pack(fill=tk.X, pady=(0, 6))
        grp_coord.columnconfigure(1, weight=1)
        grp_coord.columnconfigure(3, weight=1)

        ttk.Label(grp_coord, text="纬度:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.lat = tk.StringVar(value="35.6586")
        ttk.Entry(grp_coord, textvariable=self.lat, width=22).grid(row=0, column=1, padx=(0, 16), pady=2, sticky=tk.EW)

        ttk.Label(grp_coord, text="经度:").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.lon = tk.StringVar(value="139.7454")
        ttk.Entry(grp_coord, textvariable=self.lon, width=22).grid(row=0, column=3, pady=2, sticky=tk.EW)

        # ===== 参数 =====
        grp_params = ttk.LabelFrame(main_frame, text="参数设置", padding="10")
        grp_params.pack(fill=tk.X, pady=(0, 6))
        grp_params.columnconfigure(1, weight=1)
        grp_params.columnconfigure(3, weight=1)

        ttk.Label(grp_params, text="缩放级别:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.zoom = tk.IntVar(value=18)
        ttk.Spinbox(grp_params, from_=1, to=20, textvariable=self.zoom, width=18).grid(row=0, column=1, padx=(0, 16), pady=2, sticky=tk.W)

        ttk.Label(grp_params, text="缓冲区 (米):").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.buffer_size = tk.IntVar(value=500)
        ttk.Spinbox(grp_params, from_=50, to=5000, increment=50, textvariable=self.buffer_size, width=18).grid(row=0, column=3, pady=2, sticky=tk.W)

        # ===== 日期范围 =====
        grp_date = ttk.LabelFrame(main_frame, text="日期范围 (可选，留空获取全部)", padding="10")
        grp_date.pack(fill=tk.X, pady=(0, 6))
        grp_date.columnconfigure(1, weight=1)
        grp_date.columnconfigure(3, weight=1)

        ttk.Label(grp_date, text="起始:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.date_start = tk.StringVar(value="")
        ttk.Entry(grp_date, textvariable=self.date_start, width=22).grid(row=0, column=1, padx=(0, 16), pady=2, sticky=tk.EW)

        ttk.Label(grp_date, text="截止:").grid(row=0, column=2, padx=(0, 4), pady=2, sticky=tk.W)
        self.date_end = tk.StringVar(value="")
        ttk.Entry(grp_date, textvariable=self.date_end, width=22).grid(row=0, column=3, pady=2, sticky=tk.EW)

        # ===== 输出 =====
        grp_out = ttk.LabelFrame(main_frame, text="输出设置", padding="10")
        grp_out.pack(fill=tk.X, pady=(0, 6))
        grp_out.columnconfigure(1, weight=1)

        ttk.Label(grp_out, text="输出目录:").grid(row=0, column=0, padx=(0, 4), pady=2, sticky=tk.W)
        self.output = tk.StringVar(value="data/output/historical")
        ttk.Entry(grp_out, textvariable=self.output, width=50).grid(row=0, column=1, padx=(0, 4), pady=2, sticky=tk.EW)
        ttk.Button(grp_out, text="浏览", command=lambda: self.output.set(filedialog.askdirectory() or self.output.get())).grid(row=0, column=2, pady=2)

        # ===== 按钮 =====
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 6))
        self.start_btn = ttk.Button(btn_frame, text="开始获取", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        # ===== 日志 =====
        grp_log = ttk.LabelFrame(main_frame, text="日志", padding="5")
        grp_log.pack(fill=tk.BOTH, expand=True)

        self.log = tk.Text(grp_log, height=10, font=('Consolas', 9), wrap=tk.WORD,
                           bg='#1e1e1e', fg='#d4d4d4', insertbackground='white',
                           relief=tk.FLAT, borderwidth=4)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(grp_log, command=self.log.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.config(yscrollcommand=scrollbar.set)

        # ===== 状态栏 =====
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var,
                               relief=tk.SUNKEN, anchor=tk.W, padding=(6, 3))
        status_bar.pack(fill=tk.X, pady=(4, 0))

        self.poll_log_queue()

    # ------------------------------------------------------------------
    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log.insert(tk.END, msg + '\n')
                self.log.see(tk.END)
        except queue.Empty:
            pass
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self.root.after(50, self.poll_log_queue)

    def log_msg(self, msg):
        self.log_queue.put(msg)

    # ------------------------------------------------------------------
    def _validate_inputs(self):
        """入参校验，失败抛 ValueError。"""
        try:
            lat = float(self.lat.get())
        except ValueError:
            raise ValueError("纬度必须是数字")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"纬度越界 {lat}，需 ∈ [-90, 90]")

        try:
            lon = float(self.lon.get())
        except ValueError:
            raise ValueError("经度必须是数字")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"经度越界 {lon}，需 ∈ [-180, 180]")

        zoom = self.zoom.get()
        if not (1 <= zoom <= 20):
            raise ValueError(f"缩放级别越界 {zoom}，需 ∈ [1, 20]")

        buffer_val = self.buffer_size.get()
        if not (50 <= buffer_val <= 5000):
            raise ValueError(f"缓冲区越界 {buffer_val}，需 ∈ [50, 5000]")

        output_dir = self.output.get().strip()
        if not output_dir:
            raise ValueError("输出目录不能为空")
        # 校验输出目录可创建
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            raise ValueError(f"输出目录无法创建：{e}")

        ds = self.date_start.get().strip()
        de = self.date_end.get().strip()
        if ds and de:
            for d in (ds, de):
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                    raise ValueError(f"日期格式错误 '{d}'，应为 YYYY-MM-DD")
            if ds > de:
                raise ValueError("起始日期不能晚于截止日期")
        elif ds or de:
            raise ValueError("起始和截止日期必须同时填写或同时留空")

        return lat, lon

    # ------------------------------------------------------------------
    def start(self):
        try:
            lat, lon = self._validate_inputs()
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
            return

        zoom = self.zoom.get()
        buffer_val = self.buffer_size.get()
        output_dir = self.output.get().strip()
        ds = self.date_start.get().strip()
        de = self.date_end.get().strip()

        self._stopping = False
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log.delete(1.0, tk.END)
        self.status_var.set("运行中...")

        def done():
            # 由后台线程在子进程退出后接管按钮状态
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            if self._stopping:
                self.status_var.set("已停止")
            else:
                self.status_var.set("完成")

        def run():
            main_py = os.path.join(BASE_DIR, "main.py")
            cmd = [sys.executable, main_py,
                   "--lat", str(lat), "--lon", str(lon),
                   "--zoom", str(zoom),
                   "--buffer", str(buffer_val),
                   "--output", output_dir]
            if ds and de:
                cmd.extend(["--date-range", ds, de])

            # Windows 下用 CREATE_NEW_PROCESS_GROUP 才能发 CTRL_BREAK_EVENT
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            try:
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=BASE_DIR,
                    creationflags=creationflags
                )
                for line in self.process.stdout:
                    self.log_msg(line.rstrip())
                self.process.wait()
            except Exception as e:
                self.log_msg(f"启动子进程失败: {e}")
            finally:
                self.process = None
                self.root.after(0, done)

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        """发送停止信号，中间态显示'正在停止…'，按钮状态由 done() 接管。"""
        if self.process and self.process.poll() is None:
            self._stopping = True
            self.status_var.set("正在停止…")
            self.stop_btn.config(state=tk.DISABLED)
            try:
                if os.name == 'nt':
                    # Windows：发送 CTRL_BREAK_EVENT（需要 CREATE_NEW_PROCESS_GROUP）
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.process.terminate()
            except Exception as e:
                self.log_msg(f"停止信号发送失败: {e}")
                # 退路：terminate
                try:
                    self.process.terminate()
                except Exception:
                    pass
        else:
            # 进程已结束，直接复位
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.status_var.set("已停止")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
