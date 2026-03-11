#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
点数据到TIFF影像处理工具 - UI界面
基于TKinter实现的用户友好界面，用于配置和运行点数据处理流程
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import yaml
import subprocess
import threading
from io import StringIO

# 尝试导入ttkbootstrap，如果没有安装则使用默认主题
try:
    import ttkbootstrap
    from ttkbootstrap import Style
    TTKBOOTSTRAP_AVAILABLE = True
except ImportError:
    TTKBOOTSTRAP_AVAILABLE = False
    print("提示: 安装 ttkbootstrap 库可以获得更现代的界面主题")
    print("安装命令: pip install ttkbootstrap")

class ConfigUI:
    """主配置界面"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("点数据到TIFF影像处理工具")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)
        
        # 配置文件路径
        self.config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        
        # 加载当前配置
        self.config = self.load_config()
        
        # 程序进程
        self.process = None
        
        # 初始化UI
        self.setup_ui()
        
        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def setup_ui(self):
        """设置UI布局"""
        # 确保配置已加载
        if not self.config:
            self.config = self.load_config()
        
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建配置面板容器
        config_frame = ttk.Frame(main_frame)
        config_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=(0, 10))
        
        # 创建选项卡控件
        notebook = ttk.Notebook(config_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # 创建路径配置面板
        self.path_panel = PathConfigPanel(notebook, self.config)
        notebook.add(self.path_panel, text="路径配置")
        
        # 创建处理配置面板
        self.processing_panel = ProcessingConfigPanel(notebook, self.config)
        notebook.add(self.processing_panel, text="处理配置")
        
        # 添加数据源配置面板
        self.data_source_panel = DataSourceConfigPanel(notebook, self.config)
        notebook.add(self.data_source_panel, text="数据源配置")
        
        # 创建运行控制区
        run_frame = ttk.LabelFrame(main_frame, text="运行控制", padding="10")
        run_frame.pack(fill=tk.X, expand=False, side=tk.BOTTOM)
        
        # 按钮框架
        button_frame = ttk.Frame(run_frame)
        button_frame.pack(fill=tk.X, side=tk.TOP, pady=(0, 5))
        
        # 运行按钮
        self.run_button = ttk.Button(button_frame, text="运行", command=self.run_program)
        self.run_button.pack(side=tk.LEFT, padx=5)
        
        # 停止按钮
        self.stop_button = ttk.Button(button_frame, text="停止", command=self.stop_program, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # 保存配置按钮
        save_button = ttk.Button(button_frame, text="保存配置", command=self.save_config)
        save_button.pack(side=tk.LEFT, padx=5)
        
        # 加载配置按钮
        load_button = ttk.Button(button_frame, text="加载配置", command=self.load_config_ui)
        load_button.pack(side=tk.LEFT, padx=5)
        
        # 主题切换按钮（如果ttkbootstrap可用）
        if TTKBOOTSTRAP_AVAILABLE:
            theme_button = ttk.Button(button_frame, text="切换主题", command=self.toggle_theme)
            theme_button.pack(side=tk.RIGHT, padx=5)
        
        # 进度条
        progress_frame = ttk.Frame(run_frame, padding="5")
        progress_frame.pack(fill=tk.X, side=tk.TOP, pady=5)
        
        ttk.Label(progress_frame, text="处理进度:").pack(side=tk.LEFT, padx=5)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.progress_label = ttk.Label(progress_frame, text="0%")
        self.progress_label.pack(side=tk.LEFT, padx=5)
        
        # 日志输出窗口
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, side=tk.BOTTOM, pady=10)
        
        # 日志文本框
        self.log_text = tk.Text(log_frame, height=15, wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # 状态标签
        self.status_label = ttk.Label(main_frame, text="就绪", anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
    
    def load_config(self, config_path=None):
        """加载配置文件"""
        if config_path is None:
            config_path = self.config_path
        
        default_config = {
            'paths': {
                'input_file': 'test_shp_point_data/tw.shp',
                'output_prefix': 'square_buffers',
                'tiff_output_dir': 'tiff_output',
                'temp_tiles_dir': 'temp_tiles',
                'shp_output_subdir': 'shp',
                'kml_output_subdir': 'kml'
            },
            'processing': {
                'buffer_sizes': [1000, 2000],
                'thread_pool_size': 50,
                'request_timeout': 30,
                'retry_count': 3,
                'tile_size': 512,
                'min_zoom': 1,
                'max_zoom': 19,
                'default_zoom': 15,
                'download_mode': 'current'
            },
            'satellite_services': [
                {
                    'name': 'ESRI World Imagery',
                    'url_template': 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                    'max_zoom': 18,
                    'headers': {
                        'Referer': 'https://www.arcgis.com/',
                        'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
                    }
                }
            ],
            'user_agents': [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            ],
            'coordinate_systems': {
                'wgs84': {
                    'epsg': 4326,
                    'wkt': "GEOGCS['WGS 84',DATUM['WGS_1984',SPHEROID['WGS 84',6378137,298.257223563,AUTHORITY['EPSG','7030']],AUTHORITY['EPSG','6326']],PRIMEM['Greenwich',0,AUTHORITY['EPSG','8901']],UNIT['degree',0.0174532925199433,AUTHORITY['EPSG','9122']],AUTHORITY['EPSG','4326']]"
                }
            }
        }
        
        # 如果配置文件存在，加载并合并
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = yaml.safe_load(f)
                
                # 合并配置
                self.merge_configs(default_config, loaded_config)
            except Exception as e:
                messagebox.showerror("错误", f"加载配置文件失败: {e}")
        
        return default_config
    
    def merge_configs(self, default, loaded):
        """合并配置"""
        for key, value in loaded.items():
            if key in default and isinstance(default[key], dict) and isinstance(value, dict):
                self.merge_configs(default[key], value)
            else:
                default[key] = value
    
    def save_config(self):
        """保存配置到文件"""
        try:
            # 获取当前配置
            current_config = {
                'paths': self.path_panel.get_config(),
                'processing': self.processing_panel.get_config()
            }
            
            # 合并到现有配置
            full_config = self.load_config()
            full_config.update(current_config)
            
            # 保存到文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(full_config, f, default_flow_style=False, allow_unicode=True)
            
            messagebox.showinfo("成功", "配置已保存到config.yaml")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")
    
    def load_config_ui(self):
        """从UI加载配置"""
        try:
            self.config = self.load_config()
            self.path_panel.set_config(self.config)
            self.processing_panel.set_config(self.config)
            messagebox.showinfo("成功", "配置已从config.yaml加载")
        except Exception as e:
            messagebox.showerror("错误", f"加载配置失败: {e}")
    
    def run_program(self):
        """运行主程序"""
        try:
            # 先保存配置
            self.save_config()

            # 获取下载模式
            download_mode = self.processing_panel.get_config().get('download_mode', 'current')

            # 禁用运行按钮，启用停止按钮
            self.run_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)

            # 清空日志
            self.log_text.delete(1.0, tk.END)

            # 运行主程序
            def run():
                # 设置运行目录
                run_dir = os.path.dirname(__file__)
                # 构建命令 - 确保使用最新的配置文件
                cmd = [sys.executable, os.path.join(run_dir, 'point_kml2tif.py'), '--mode', download_mode]

                # 启动进程，禁用输出缓冲
                self.process = subprocess.Popen(
                    cmd,
                    cwd=run_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=0,
                    universal_newlines=True
                )
                
                # 初始化进度
                buffer_sizes = self.processing_panel.get_config()['buffer_sizes']
                total_buffers = len(buffer_sizes)
                processed = 0
                total = total_buffers
                
                # 设置初始进度
                self.progress_var.set(0)
                self.progress_label.config(text=f"0/{total}")
                self.root.update()
                
                # 读取输出并更新进度
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    
                    self.log_text.insert(tk.END, line)
                    self.log_text.see(tk.END)
                    self.root.update()  # 强制UI更新
                    
                    # 分析输出，更新进度
                    import re
                    
                    # 检测缓冲区处理进度格式："处理缓冲区 8/93: buffers.8"
                    progress_match = re.search(r'处理缓冲区\s+(\d+)/(\d+):', line)
                    if progress_match:
                        processed = int(progress_match.group(1))
                        total = int(progress_match.group(2))
                        # 更新进度
                        progress_percent = (processed / total) * 100 if total > 0 else 0
                        self.progress_var.set(progress_percent)
                        self.progress_label.config(text=f"{processed}/{total}")
                        self.root.update()
                    elif "所有处理完成" in line:
                        # 所有处理完成，更新为最终进度
                        processed = total
                        progress_percent = 100
                        self.progress_var.set(progress_percent)
                        self.progress_label.config(text=f"{processed}/{total}")
                        self.root.update()
                    
                    # 更新进度条
                    self.root.update()  # 强制UI更新
                
                # 进程结束
                self.process.wait()
                self.process = None
                
                # 最终检查：确保显示正确的完成状态
                processed = total
                progress = 100
                self.progress_var.set(progress)
                self.progress_label.config(text=f"{processed}/{total}")
                self.root.update()
                
                # 恢复按钮状态
                self.run_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                
                # 显示完成信息
                self.log_text.insert(tk.END, "\n=== 程序运行完成 ===\n")
                self.log_text.see(tk.END)
                self.root.update()
            
            # 在新线程中运行
            threading.Thread(target=run, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("错误", f"运行程序失败: {e}")
            self.run_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
    
    def stop_program(self):
        """停止程序"""
        if self.process:
            try:
                self.process.terminate()
                self.log_text.insert(tk.END, "\n=== 程序已停止 ===\n")
                self.log_text.see(tk.END)
            except Exception as e:
                messagebox.showerror("错误", f"停止程序失败: {e}")
        
        # 恢复按钮状态
        self.run_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
    
    def on_closing(self):
        """窗口关闭事件处理"""
        if self.process:
            if messagebox.askokcancel("退出", "程序正在运行，确定要退出吗？"):
                self.stop_program()
                self.root.destroy()
        else:
            self.root.destroy()
    
    def toggle_theme(self):
        """切换主题"""
        if TTKBOOTSTRAP_AVAILABLE:
            themes = ['cosmo', 'flatly', 'journal', 'darkly', 'superhero', 'united']
            current_theme = ttkbootstrap.Style().theme_use()
            next_theme = themes[(themes.index(current_theme) + 1) % len(themes)]
            ttkbootstrap.Style(theme=next_theme)
            self.status_label.config(text=f"主题已切换为: {next_theme}")
            self.log_text.insert(tk.END, f"\n=== 主题已切换为: {next_theme} ===\n")
            self.log_text.see(tk.END)


class PathConfigPanel(ttk.Frame):
    """路径配置面板"""
    
    def __init__(self, parent, config):
        super().__init__(parent, padding="10")
        self.config = config
        self.setup_ui()
    
    def setup_ui(self):
        """设置路径配置UI"""
        # 创建路径配置标签框
        path_frame = ttk.LabelFrame(self, text="路径配置", padding="10")
        path_frame.pack(fill=tk.BOTH, expand=True)
        
        # 输入文件路径
        ttk.Label(path_frame, text="输入点文件:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.input_file_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.input_file_var, width=60).grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Button(path_frame, text="浏览", command=self.browse_input_file).grid(row=0, column=2, padx=5, pady=5)
        
        # 输出前缀
        ttk.Label(path_frame, text="输出前缀:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.output_prefix_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.output_prefix_var, width=60).grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        # TIFF输出目录
        ttk.Label(path_frame, text="TIFF输出目录:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.tiff_output_dir_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.tiff_output_dir_var, width=60).grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Button(path_frame, text="浏览", command=self.browse_tiff_output_dir).grid(row=2, column=2, padx=5, pady=5)
        
        # 临时瓦片目录
        ttk.Label(path_frame, text="临时瓦片目录:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.temp_tiles_dir_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.temp_tiles_dir_var, width=60).grid(row=3, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Button(path_frame, text="浏览", command=self.browse_temp_tiles_dir).grid(row=3, column=2, padx=5, pady=5)
        
        # Shapefile输出子目录
        ttk.Label(path_frame, text="Shapefile输出子目录:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.shp_output_subdir_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.shp_output_subdir_var, width=60).grid(row=4, column=1, padx=5, pady=5, sticky=tk.W)
        
        # KML输出子目录
        ttk.Label(path_frame, text="KML输出子目录:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.kml_output_subdir_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.kml_output_subdir_var, width=60).grid(row=5, column=1, padx=5, pady=5, sticky=tk.W)
        
        # 设置初始值
        self.set_config(self.config)
    
    def browse_input_file(self):
        """浏览输入文件"""
        file_path = filedialog.askopenfilename(
            title="选择输入点文件",
            filetypes=[("Shapefile", "*.shp"), ("KML文件", "*.kml"), ("所有文件", "*.*")]
        )
        if file_path:
            self.input_file_var.set(file_path)
    
    def browse_tiff_output_dir(self):
        """浏览TIFF输出目录"""
        dir_path = filedialog.askdirectory(title="选择TIFF输出目录")
        if dir_path:
            self.tiff_output_dir_var.set(dir_path)
    
    def browse_temp_tiles_dir(self):
        """浏览临时瓦片目录"""
        dir_path = filedialog.askdirectory(title="选择临时瓦片目录")
        if dir_path:
            self.temp_tiles_dir_var.set(dir_path)
    
    def set_config(self, config):
        """设置配置"""
        paths = config.get('paths', {})
        self.input_file_var.set(paths.get('input_file', ''))
        self.output_prefix_var.set(paths.get('output_prefix', ''))
        self.tiff_output_dir_var.set(paths.get('tiff_output_dir', ''))
        self.temp_tiles_dir_var.set(paths.get('temp_tiles_dir', ''))
        self.shp_output_subdir_var.set(paths.get('shp_output_subdir', ''))
        self.kml_output_subdir_var.set(paths.get('kml_output_subdir', ''))
    
    def get_config(self):
        """获取配置"""
        return {
            'input_file': self.input_file_var.get(),
            'output_prefix': self.output_prefix_var.get(),
            'tiff_output_dir': self.tiff_output_dir_var.get(),
            'temp_tiles_dir': self.temp_tiles_dir_var.get(),
            'shp_output_subdir': self.shp_output_subdir_var.get(),
            'kml_output_subdir': self.kml_output_subdir_var.get()
        }


class ProcessingConfigPanel(ttk.Frame):
    """处理配置面板"""
    
    def __init__(self, parent, config):
        super().__init__(parent, padding="10")
        self.config = config
        self.setup_ui()
    
    def setup_ui(self):
        """设置处理配置UI"""
        # 创建处理配置标签框
        process_frame = ttk.LabelFrame(self, text="处理配置", padding="10")
        process_frame.pack(fill=tk.BOTH, expand=True)
        
        # 缓冲区尺寸
        ttk.Label(process_frame, text="缓冲区尺寸(米):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.buffer_sizes_var = tk.StringVar()
        ttk.Entry(process_frame, textvariable=self.buffer_sizes_var, width=60).grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Label(process_frame, text="(示例: 1000,2000 多个值用逗号分隔)").grid(row=0, column=2, sticky=tk.W, pady=5)
        
        # 线程池大小
        ttk.Label(process_frame, text="线程池大小:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.thread_pool_size_var = tk.IntVar()
        thread_scale = ttk.Scale(process_frame, from_=1, to=100, variable=self.thread_pool_size_var, orient=tk.HORIZONTAL)
        thread_scale.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        self.thread_pool_size_label = ttk.Label(process_frame, text="")
        self.thread_pool_size_label.grid(row=1, column=2, sticky=tk.W, padx=5, pady=5)
        
        # 请求超时时间
        ttk.Label(process_frame, text="请求超时(秒):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.request_timeout_var = tk.IntVar()
        timeout_scale = ttk.Scale(process_frame, from_=10, to=60, variable=self.request_timeout_var, orient=tk.HORIZONTAL)
        timeout_scale.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        self.request_timeout_label = ttk.Label(process_frame, text="")
        self.request_timeout_label.grid(row=2, column=2, sticky=tk.W, padx=5, pady=5)
        
        # 请求重试次数
        ttk.Label(process_frame, text="请求重试次数:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.retry_count_var = tk.IntVar()
        retry_scale = ttk.Scale(process_frame, from_=1, to=10, variable=self.retry_count_var, orient=tk.HORIZONTAL)
        retry_scale.grid(row=3, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        self.retry_count_label = ttk.Label(process_frame, text="")
        self.retry_count_label.grid(row=3, column=2, sticky=tk.W, padx=5, pady=5)
        
        # 瓦片大小
        ttk.Label(process_frame, text="瓦片大小(像素):").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.tile_size_var = tk.IntVar()
        tile_size_combo = ttk.Combobox(process_frame, textvariable=self.tile_size_var, values=[256, 512, 1024], width=10)
        tile_size_combo.grid(row=4, column=1, padx=5, pady=5, sticky=tk.W)
        
        # 最小缩放级别
        ttk.Label(process_frame, text="最小缩放级别:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.min_zoom_var = tk.IntVar()
        min_zoom_scale = ttk.Scale(process_frame, from_=1, to=10, variable=self.min_zoom_var, orient=tk.HORIZONTAL)
        min_zoom_scale.grid(row=5, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        self.min_zoom_label = ttk.Label(process_frame, text="")
        self.min_zoom_label.grid(row=5, column=2, sticky=tk.W, padx=5, pady=5)
        
        # 最大缩放级别
        ttk.Label(process_frame, text="最大缩放级别:").grid(row=6, column=0, sticky=tk.W, pady=5)
        self.max_zoom_var = tk.IntVar()
        max_zoom_scale = ttk.Scale(process_frame, from_=10, to=20, variable=self.max_zoom_var, orient=tk.HORIZONTAL)
        max_zoom_scale.grid(row=6, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        self.max_zoom_label = ttk.Label(process_frame, text="")
        self.max_zoom_label.grid(row=6, column=2, sticky=tk.W, padx=5, pady=5)
        
        # 默认缩放级别
        ttk.Label(process_frame, text="默认缩放级别:").grid(row=7, column=0, sticky=tk.W, pady=5)
        self.default_zoom_var = tk.IntVar()
        default_zoom_scale = ttk.Scale(process_frame, from_=1, to=20, variable=self.default_zoom_var, orient=tk.HORIZONTAL)
        default_zoom_scale.grid(row=7, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        self.default_zoom_label = ttk.Label(process_frame, text="")
        self.default_zoom_label.grid(row=7, column=2, sticky=tk.W, padx=5, pady=5)

        # 影像下载模式选择
        ttk.Label(process_frame, text="影像下载模式:").grid(row=8, column=0, sticky=tk.W, pady=5)
        self.download_mode_var = tk.StringVar(value='current')
        download_mode_frame = ttk.Frame(process_frame)
        download_mode_frame.grid(row=8, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Radiobutton(download_mode_frame, text="当前影像", variable=self.download_mode_var,
                        value='current').pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(download_mode_frame, text="历史影像", variable=self.download_mode_var,
                        value='previous').pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(download_mode_frame, text="两者都下载", variable=self.download_mode_var,
                        value='both').pack(side=tk.LEFT, padx=5)

        # 绑定缩放事件
        thread_scale.bind("<Motion>", lambda e: self.update_label(self.thread_pool_size_label, self.thread_pool_size_var.get()))
        timeout_scale.bind("<Motion>", lambda e: self.update_label(self.request_timeout_label, self.request_timeout_var.get()))
        retry_scale.bind("<Motion>", lambda e: self.update_label(self.retry_count_label, self.retry_count_var.get()))
        min_zoom_scale.bind("<Motion>", lambda e: self.update_label(self.min_zoom_label, self.min_zoom_var.get()))
        max_zoom_scale.bind("<Motion>", lambda e: self.update_label(self.max_zoom_label, self.max_zoom_var.get()))
        default_zoom_scale.bind("<Motion>", lambda e: self.update_label(self.default_zoom_label, self.default_zoom_var.get()))

        # 设置初始值
        self.set_config(self.config)
    
    def update_label(self, label, value):
        """更新标签显示"""
        label.config(text=str(value))
    
    def set_config(self, config):
        """设置配置"""
        processing = config.get('processing', {})
        buffer_sizes = processing.get('buffer_sizes', [])
        self.buffer_sizes_var.set(','.join(map(str, buffer_sizes)))

        self.thread_pool_size_var.set(processing.get('thread_pool_size', 50))
        self.update_label(self.thread_pool_size_label, processing.get('thread_pool_size', 50))

        self.request_timeout_var.set(processing.get('request_timeout', 30))
        self.update_label(self.request_timeout_label, processing.get('request_timeout', 30))

        self.retry_count_var.set(processing.get('retry_count', 3))
        self.update_label(self.retry_count_label, processing.get('retry_count', 3))

        self.tile_size_var.set(processing.get('tile_size', 512))

        self.min_zoom_var.set(processing.get('min_zoom', 1))
        self.update_label(self.min_zoom_label, processing.get('min_zoom', 1))

        self.max_zoom_var.set(processing.get('max_zoom', 19))
        self.update_label(self.max_zoom_label, processing.get('max_zoom', 19))

        self.default_zoom_var.set(processing.get('default_zoom', 15))
        self.update_label(self.default_zoom_label, processing.get('default_zoom', 15))

        # 设置下载模式
        self.download_mode_var.set(processing.get('download_mode', 'current'))
    
    def get_config(self):
        """获取配置"""
        # 处理缓冲区尺寸
        buffer_sizes_str = self.buffer_sizes_var.get()
        buffer_sizes = []
        if buffer_sizes_str:
            try:
                buffer_sizes = [int(x.strip()) for x in buffer_sizes_str.split(',')]
            except ValueError:
                buffer_sizes = [1000, 2000]

        return {
            'buffer_sizes': buffer_sizes,
            'thread_pool_size': self.thread_pool_size_var.get(),
            'request_timeout': self.request_timeout_var.get(),
            'retry_count': self.retry_count_var.get(),
            'tile_size': self.tile_size_var.get(),
            'min_zoom': self.min_zoom_var.get(),
            'max_zoom': self.max_zoom_var.get(),
            'default_zoom': self.default_zoom_var.get(),
            'download_mode': self.download_mode_var.get()
        }


class DataSourceConfigPanel(ttk.Frame):
    """数据源配置面板"""
    
    def __init__(self, parent, config):
        super().__init__(parent, padding="10")
        self.config = config
        self.setup_ui()
    
    def setup_ui(self):
        """设置数据源配置UI"""
        # 创建数据源配置标签框
        data_source_frame = ttk.LabelFrame(self, text="卫星数据源配置", padding="10")
        data_source_frame.pack(fill=tk.BOTH, expand=True)
        
        # 数据源选择
        ttk.Label(data_source_frame, text="默认数据源:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.default_data_source_var = tk.StringVar()
        data_sources = ['ESRI World Imagery', 'Google Earth', 'Bing Maps', 'OpenStreetMap']
        data_source_combo = ttk.Combobox(data_source_frame, textvariable=self.default_data_source_var, values=data_sources, width=30)
        data_source_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        # 自定义WMS/WMTS服务
        ttk.Label(data_source_frame, text="自定义WMS/WMTS服务:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.custom_service_var = tk.StringVar()
        ttk.Entry(data_source_frame, textvariable=self.custom_service_var, width=60).grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Label(data_source_frame, text="(URL模板，使用{z}/{y}/{x}占位符)").grid(row=1, column=2, sticky=tk.W, pady=5)
        
        # 启用历史影像
        ttk.Label(data_source_frame, text="历史影像服务:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.wayback_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(data_source_frame, text="启用ESRI Wayback历史影像服务", variable=self.wayback_enabled_var).grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)
        
        # 设置初始值
        self.set_config(self.config)
    
    def set_config(self, config):
        """设置配置"""
        # 设置默认数据源
        satellite_services = config.get('satellite_services', [])
        if satellite_services:
            self.default_data_source_var.set(satellite_services[0].get('name', 'ESRI World Imagery'))
        else:
            self.default_data_source_var.set('ESRI World Imagery')
        
        # 设置历史影像服务
        wayback_services = config.get('wayback_services', {})
        self.wayback_enabled_var.set(wayback_services.get('enabled', False))
    
    def get_config(self):
        """获取配置"""
        return {
            'default_data_source': self.default_data_source_var.get(),
            'custom_service': self.custom_service_var.get(),
            'wayback_enabled': self.wayback_enabled_var.get()
        }


def main():
    """主函数"""
    # 使用现代主题
    if TTKBOOTSTRAP_AVAILABLE:
        style = Style(theme='cosmo')
        root = style.master
    else:
        root = tk.Tk()
    
    app = ConfigUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()