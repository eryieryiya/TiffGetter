#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESRI Wayback 历史影像获取工具 - GUI"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import subprocess
import threading


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("ESRI Wayback 历史影像获取")
        self.root.geometry("600x400")
        self.process = None

        frame = ttk.Frame(root, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="ESRI Wayback 历史影像获取", font=('Arial', 14, 'bold')).pack(pady=(0, 15))

        # 坐标输入
        coord = ttk.LabelFrame(frame, text="坐标", padding="10")
        coord.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(coord, text="纬度:").grid(row=0, column=0, sticky=tk.W)
        self.lat = tk.StringVar(value="35.6586")
        ttk.Entry(coord, textvariable=self.lat, width=20).grid(row=0, column=1, padx=5)

        ttk.Label(coord, text="经度:").grid(row=1, column=0, sticky=tk.W)
        self.lon = tk.StringVar(value="139.7454")
        ttk.Entry(coord, textvariable=self.lon, width=20).grid(row=1, column=1, padx=5)

        ttk.Label(coord, text="缩放级别:").grid(row=2, column=0, sticky=tk.W)
        self.zoom = tk.IntVar(value=18)
        ttk.Spinbox(coord, from_=1, to=20, textvariable=self.zoom, width=18).grid(row=2, column=1, padx=5, sticky=tk.W)

        # 输出
        out = ttk.Frame(frame)
        out.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(out, text="输出:").pack(side=tk.LEFT)
        self.output = tk.StringVar(value="data/output/historical")
        ttk.Entry(out, textvariable=self.output, width=40).pack(side=tk.LEFT, padx=5)
        ttk.Button(out, text="浏览", command=lambda: self.output.set(filedialog.askdirectory() or self.output.get())).pack(side=tk.LEFT)

        # 按钮
        btn = ttk.Frame(frame)
        btn.pack(fill=tk.X, pady=(0, 10))
        self.start_btn = ttk.Button(btn, text="开始获取", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(btn, text="停止", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # 日志
        log = ttk.LabelFrame(frame, text="日志", padding="5")
        log.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(log, height=10, font=('Consolas', 9))
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Scrollbar(log, command=self.log.yview).pack(side=tk.RIGHT, fill=tk.Y)
        self.log.config(yscrollcommand=lambda f, l: None)

    def log_msg(self, msg):
        self.log.insert(tk.END, msg + '\n')
        self.log.see(tk.END)
        self.root.update()

    def start(self):
        try:
            lat, lon = float(self.lat.get()), float(self.lon.get())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的经纬度")
            return

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log.delete(1.0, tk.END)

        def run():
            cmd = [sys.executable, "main.py",
                   "--lat", str(lat), "--lon", str(lon),
                   "--zoom", str(self.zoom.get()),
                   "--output", self.output.get()]

            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
            for line in self.process.stdout:
                self.log_msg(line.rstrip())
            self.process.wait()
            self.process = None
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        if self.process:
            self.process.terminate()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()