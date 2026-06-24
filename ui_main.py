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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("ESRI Wayback 历史影像获取")
        self.root.geometry("700x540")
        self.root.minsize(620, 460)
        self.process = None
        self.log_queue = queue.Queue()

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
    def start(self):
        try:
            lat, lon = float(self.lat.get()), float(self.lon.get())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的经纬度")
            return

        zoom = self.zoom.get()
        buffer_val = self.buffer_size.get()
        output_dir = self.output.get()
        ds = self.date_start.get().strip()
        de = self.date_end.get().strip()

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log.delete(1.0, tk.END)
        self.status_var.set("运行中...")

        def done():
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
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

            try:
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=BASE_DIR)
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
        if self.process:
            self.process.terminate()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("已停止")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
