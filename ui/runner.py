# -*- coding: utf-8 -*-
"""子进程运行控制：启动、日志队列、进度、结果解析、停止。"""
import os
import sys
import subprocess
import threading
import queue
import signal
import re
from typing import List

import tkinter as tk

from ui import BASE_DIR
from ui.theme import HAS_TTKBOOTSTRAP, SUCCESS


def _build_cli_cmd(extra_args: List[str]) -> List[str]:
    """构造 CLI 子进程命令（下载逻辑跑在子进程，stdout 回传日志面板）。

    开发态: python main.py <args>
    打包态: TiffGetter.exe <args>（app_entry 自动按参数路由到 CLI；
            sys.executable 即 exe 自身，不再拼接脚本路径）
    """
    if getattr(sys, 'frozen', False):
        return [sys.executable] + list(extra_args)
    return [sys.executable, os.path.join(BASE_DIR, 'main.py')] + list(extra_args)


def _cli_workdir() -> str:
    """CLI 子进程的工作目录。

    打包态下 BASE_DIR 是 PyInstaller 临时解压目录（退出即删除），
    相对输出路径会写进临时目录导致数据丢失；改为 exe 所在目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return BASE_DIR


class RunnerMixin:
    """运行控制相关方法集合；需与 App 的其他 mixin 组合使用。"""

    # ------------------------------------------------------------------
    # 日志泵
    # ------------------------------------------------------------------
    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log.insert(tk.END, msg + '\n')
                self._colorize_last_log_line(msg)
                if self.auto_scroll_var.get():
                    self.log.see(tk.END)
                # 解析 [i/N] 粗粒度进度
                m = re.search(r'\[(\d+)/(\d+)\]', msg)
                if m:
                    i, n = int(m.group(1)), int(m.group(2))
                    if n > 0:
                        self.progress['value'] = i / n * 100
                # 提取「找到 K 个版本」估计总日期数
                est = re.search(r'找到\s+(\d+)\s+个版本', msg)
                if est:
                    try:
                        self._estimated_total_dates = int(est.group(1))
                    except Exception:
                        pass
                # 解析成功/失败/重复行追加到结果表 + 精细进度
                self._parse_result_line(msg)
        except queue.Empty:
            pass
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self.root.after(50, self.poll_log_queue)

    def log_msg(self, msg: str):
        self.log_queue.put(msg)

    def _clear_log(self):
        try:
            self.log.delete(1.0, tk.END)
        except Exception:
            pass

    def _copy_log_selection(self):
        try:
            sel = self.log.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(sel)
        except Exception:
            pass

    def _colorize_last_log_line(self, msg: str):
        """对最后一行日志按级别着色。"""
        try:
            last_idx = self.log.index("end-1c linestart")
            end_idx = self.log.index("end-1c")
            if last_idx == end_idx:
                return
            has_ok_tag = False
            if re.search(r'\[OK\]|\[PART\]\s*ok', msg):
                self.log.tag_add("lvl_ok", last_idx, end_idx)
                has_ok_tag = True
            if "[FAIL]" in msg:
                self.log.tag_remove("lvl_ok", last_idx, end_idx)
                self.log.tag_add("lvl_err", last_idx, end_idx)
                return
            if has_ok_tag:
                return
            m = re.match(
                r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (INFO|WARNING|ERROR) - (.*)',
                msg,
            )
            if m:
                lvl = m.group(2)
                tag = {"INFO": "lvl_info", "WARNING": "lvl_warn", "ERROR": "lvl_err"}.get(lvl)
                if tag:
                    self.log.tag_add(tag, last_idx, end_idx)
        except Exception:
            pass

    def _update_progress_fine(self):
        """从 result_tree 已插入的 [OK]/[FAIL] 计数估算总进度。"""
        try:
            rows = self.result_tree.get_children()
            done = 0
            for r in rows:
                vals = self.result_tree.item(r, 'values')
                if len(vals) > 1 and vals[1] in ("✅ success", "⚠️ partial", "❌ failed"):
                    done += 1
            if done > 0 and self._estimated_total_dates and self._estimated_total_dates > 0:
                est = min(done / self._estimated_total_dates, 0.99)
                if self.progress['value'] < est * 100:
                    self.progress['value'] = est * 100
        except Exception:
            pass

    def _parse_result_line(self, msg: str):
        """解析单点/批量结果日志，填充结果 Treeview。"""
        # 单点模式：[OK] 2024-08-15
        m1 = re.search(r'\[OK\]\s+(\S+)', msg)
        if m1:
            self.result_tree.insert('', tk.END,
                values=(m1.group(1), '✅ success', ''),
                tags=('row_success',))
            self._update_progress_fine()
            return
        m2 = re.search(r'\[FAIL\]\s+(\S+)', msg)
        if m2:
            self.result_tree.insert('', tk.END,
                values=(m2.group(1), '❌ failed', ''),
                tags=('row_failed',))
            self._update_progress_fine()
            return
        # 批量模式：[OK] name (lat, lon) 成功 X/Y
        m3 = re.search(r'\[(OK|PART|FAIL)\]\s+(\S+)\s+\(([0-9.\-]+),\s*([0-9.\-]+)\)\s+成功\s+(\d+)/(\d+)', msg)
        if m3:
            tag, name, lat, lon, succ, total = m3.groups()
            status_map = {
                'OK':   ('✅ success', 'row_success'),
                'PART': ('⚠️ partial', 'row_partial'),
                'FAIL': ('❌ failed',  'row_failed'),
            }
            status_txt, row_tag = status_map.get(tag, (tag, ''))
            self.result_tree.insert('', tk.END, values=(
                name, status_txt, f"{lat},{lon} 成功 {succ}/{total}"
            ), tags=(row_tag,))
            self._update_progress_fine()

    # ------------------------------------------------------------------
    # 子进程控制
    # ------------------------------------------------------------------
    def _set_running(self, running: bool):
        if running:
            self.start_single_btn.config(state=tk.DISABLED)
            self.start_batch_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.start_single_btn.config(state=tk.NORMAL)
            self.start_batch_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _launch_subprocess(self, cmd: list):
        def run():
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=_cli_workdir(),
                    creationflags=creationflags,
                )
                for line in self.process.stdout:
                    self.log_msg(line.rstrip())
                self.process.wait()
            except Exception as e:
                self.log_msg(f"启动子进程失败: {e}")
            finally:
                self.process = None
                self.root.after(0, self._on_done)

        threading.Thread(target=run, daemon=True).start()

    def _stop(self):
        if self.process and self.process.poll() is None:
            self._stopping = True
            self.status_var.set("正在停止...")
            self.stop_btn.config(state=tk.DISABLED)
            try:
                if os.name == 'nt':
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.process.terminate()
            except Exception as e:
                self.log_msg(f"停止信号发送失败: {e}")
                try:
                    self.process.terminate()
                except Exception:
                    pass
        else:
            self._set_running(False)
            self.status_var.set("已停止")

    def _on_close(self):
        """关闭主窗口：终止仍在运行的下载子进程后销毁窗口。"""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        self.root.destroy()

    def _on_done(self):
        self._set_running(False)
        if self._stopping:
            self.status_var.set("已停止")
        else:
            self.status_var.set("完成")
            try:
                self.progress['value'] = 100
            except Exception:
                pass
            # 进度条 bootstyle 切回 SUCCESS
            if HAS_TTKBOOTSTRAP:
                try:
                    self.progress.configure(bootstyle=f"{SUCCESS}-striped")
                except Exception:
                    pass

    def _open_selected_path(self, _event):
        iid = self.result_tree.focus()
        if not iid:
            return
        vals = self.result_tree.item(iid, 'values')
        path = vals[2] if len(vals) > 2 else ''
        # 路径可能只是 "lat,lon 成功 X/Y"，无目录则忽略
        if path and os.path.exists(path):
            self._open_in_file_manager(os.path.dirname(path))
