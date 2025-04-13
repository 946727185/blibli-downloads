import os
import sys
import json
import threading
import customtkinter as ctk
from pathlib import Path
from typing import Optional, List, Dict, Any
from tkinter import filedialog, messagebox
from enum import Enum

# 导入核心下载器
from 音乐批量下载 import BiliDownloader, DownloadQuality, DownloadContent, VideoType

class BiliDownloaderGUI:
    def __init__(self):
        # 初始化窗口
        self.window = ctk.CTk()
        self.window.title("Bilibili 批量下载助手-by 永哥-v1.0.1")
        self.window.geometry("1500x1000")
        
        # 设置主题
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # 创建下载器实例
        self.downloader = BiliDownloader(
            status_callback=self._status_callback,
            progress_callback=self._progress_callback,
            error_callback=self._error_callback
        )
        
        # 创建主框架
        self.main_frame = ctk.CTkFrame(self.window)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 创建选项卡
        self.tabview = ctk.CTkTabview(self.main_frame)
        self.tabview.pack(fill="both", expand=True, padx=5, pady=5)
        
        # 添加选项卡
        self.single_tab = self.tabview.add("单视频/合集")
        self.batch_tab = self.tabview.add("批量下载")
        self.settings_tab = self.tabview.add("设置")
        
        # 初始化各个选项卡
        self._init_single_tab()
        self._init_batch_tab()
        self._init_settings_tab()
        
        # 状态栏
        self.status_bar = ctk.CTkLabel(
            self.window,
            text="就绪",
            anchor="w"
        )
        self.status_bar.pack(fill="x", padx=10, pady=(0, 10))
        
        # 当前视频信息
        self.current_info: Optional[Dict] = None
        
    def _status_callback(self, message: str):
        """处理状态消息的回调函数"""
        def update_status():
            self.status_bar.configure(text=message)
        self.window.after(0, update_status)
        
    def _progress_callback(self, task_id: str, downloaded: int, total: int, speed: float):
        """处理进度更新的回调函数"""
        def update_progress():
            # 更新进度条
            if hasattr(self, 'progress_bar'):
                if total > 0:
                    progress = (downloaded / total) * 100
                    self.progress_bar.set(progress / 100)  # customtkinter的进度条范围是0-1
                    self.progress_label.configure(
                        text=f"进度: {progress:.1f}% | 速度: {speed:.1f}MB/s"
                    )
                elif downloaded > 0:
                    self.progress_label.configure(
                        text=f"已下载: {downloaded/1024/1024:.1f}MB | 速度: {speed:.1f}MB/s"
                    )
        self.window.after(0, update_progress)
        
    def _error_callback(self, task_id: str, error: str):
        """处理错误的回调函数"""
        def show_error():
            messagebox.showerror("错误", f"任务 {task_id} 发生错误:\n{error}")
        self.window.after(0, show_error)
        
    def _init_single_tab(self):
        """初始化单视频/合集下载选项卡"""
        # URL 输入区域
        url_frame = ctk.CTkFrame(self.single_tab)
        url_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(url_frame, text="B站链接:").pack(side="left", padx=5)
        self.url_entry = ctk.CTkEntry(url_frame, width=400)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        self.parse_button = ctk.CTkButton(
            url_frame,
            text="解析",
            command=self._parse_url
        )
        self.parse_button.pack(side="right", padx=5)
        
        # 视频信息区域
        self.info_frame = ctk.CTkFrame(self.single_tab)
        self.info_frame.pack(fill="x", padx=10, pady=5)
        
        # 分P列表区域
        self.pages_frame = ctk.CTkFrame(self.single_tab)
        self.pages_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 下载选项区域
        options_frame = ctk.CTkFrame(self.single_tab)
        options_frame.pack(fill="x", padx=10, pady=5)
        
        # 质量选择
        ctk.CTkLabel(options_frame, text="质量:").pack(side="left", padx=5)
        self.quality_var = ctk.StringVar(value=self.downloader.config.get("quality", DownloadQuality.HIGH_1080.name))
        quality_menu = ctk.CTkOptionMenu(
            options_frame,
            values=[q.name for q in DownloadQuality],
            variable=self.quality_var
        )
        quality_menu.pack(side="left", padx=5)
        
        # 内容选择
        ctk.CTkLabel(options_frame, text="内容:").pack(side="left", padx=5)
        self.content_vars = {}
        default_content = self.downloader.config.get("download_content", [DownloadContent.VIDEO.name])
        for content in DownloadContent:
            var = ctk.BooleanVar(value=content.name in default_content)
            self.content_vars[content] = var
            ctk.CTkCheckBox(
                options_frame,
                text=content.value,
                variable=var
            ).pack(side="left", padx=5)
        
        # 线程数选择
        ctk.CTkLabel(options_frame, text="线程数:").pack(side="left", padx=5)
        self.threads_var = ctk.StringVar(value=str(self.downloader.config.get("max_workers", 4)))
        threads_entry = ctk.CTkEntry(
            options_frame,
            width=50,
            textvariable=self.threads_var
        )
        threads_entry.pack(side="left", padx=5)
        
        # 进度条
        self.progress_frame = ctk.CTkFrame(self.single_tab)
        self.progress_frame.pack(fill="x", padx=10, pady=5)
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", padx=5, pady=5)
        self.progress_bar.set(0)
        
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="进度: 0% | 速度: 0.0MB/s"
        )
        self.progress_label.pack(padx=5, pady=5)
        
        # 下载按钮
        self.download_button = ctk.CTkButton(
            self.single_tab,
            text="开始下载",
            command=self._start_download
        )
        self.download_button.pack(padx=10, pady=5)
        
    def _init_batch_tab(self):
        """初始化批量下载选项卡"""
        # 文件选择区域
        file_frame = ctk.CTkFrame(self.batch_tab)
        file_frame.pack(fill="x", padx=10, pady=5)
        
        self.file_path_var = ctk.StringVar()
        ctk.CTkLabel(file_frame, text="URL文件:").pack(side="left", padx=5)
        self.file_path_entry = ctk.CTkEntry(
            file_frame,
            textvariable=self.file_path_var,
            width=400
        )
        self.file_path_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        ctk.CTkButton(
            file_frame,
            text="选择文件",
            command=self._select_batch_file
        ).pack(side="right", padx=5)
        
        # 下载选项区域（与单视频选项卡类似）
        options_frame = ctk.CTkFrame(self.batch_tab)
        options_frame.pack(fill="x", padx=10, pady=5)
        
        # 质量选择
        ctk.CTkLabel(options_frame, text="质量:").pack(side="left", padx=5)
        self.batch_quality_var = ctk.StringVar(value=self.downloader.config.get("quality", DownloadQuality.HIGH_1080.name))
        quality_menu = ctk.CTkOptionMenu(
            options_frame,
            values=[q.name for q in DownloadQuality],
            variable=self.batch_quality_var
        )
        quality_menu.pack(side="left", padx=5)
        
        # 内容选择
        ctk.CTkLabel(options_frame, text="内容:").pack(side="left", padx=5)
        self.batch_content_vars = {}
        default_content = self.downloader.config.get("download_content", [DownloadContent.VIDEO.name])
        
        # 添加全选/取消全选按钮
        select_frame = ctk.CTkFrame(options_frame)
        select_frame.pack(side="left", padx=5)
        
        # 创建内容选择框
        content_frame = ctk.CTkFrame(options_frame)
        content_frame.pack(side="left", padx=5)
        
        for content in DownloadContent:
            var = ctk.BooleanVar(value=content.name in default_content)
            self.batch_content_vars[content] = var
            ctk.CTkCheckBox(
                content_frame,
                text=content.value,
                variable=var
            ).pack(side="left", padx=5)
            
        # 定义全选/取消全选函数
        def select_all_batch():
            for var in self.batch_content_vars.values():
                var.set(True)
        
        def deselect_all_batch():
            for var in self.batch_content_vars.values():
                var.set(False)
        
        # 添加全选/取消全选按钮
        ctk.CTkButton(
            select_frame,
            text="全选",
            command=select_all_batch,
            width=50
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            select_frame,
            text="取消全选",
            command=deselect_all_batch,
            width=50
        ).pack(side="left", padx=2)
        
        # 线程数选择
        ctk.CTkLabel(options_frame, text="线程数:").pack(side="left", padx=5)
        self.batch_threads_var = ctk.StringVar(value=str(self.downloader.config.get("max_workers", 4)))
        threads_entry = ctk.CTkEntry(
            options_frame,
            width=50,
            textvariable=self.batch_threads_var
        )
        threads_entry.pack(side="left", padx=5)
        
        # 进度条
        self.batch_progress_frame = ctk.CTkFrame(self.batch_tab)
        self.batch_progress_frame.pack(fill="x", padx=10, pady=5)
        
        self.batch_progress_bar = ctk.CTkProgressBar(self.batch_progress_frame)
        self.batch_progress_bar.pack(fill="x", padx=5, pady=5)
        self.batch_progress_bar.set(0)
        
        self.batch_progress_label = ctk.CTkLabel(
            self.batch_progress_frame,
            text="进度: 0% | 速度: 0.0MB/s"
        )
        self.batch_progress_label.pack(padx=5, pady=5)
        
        # 下载按钮
        self.batch_download_button = ctk.CTkButton(
            self.batch_tab,
            text="开始批量下载",
            command=self._start_batch_download
        )
        self.batch_download_button.pack(padx=10, pady=5)
        
    def _init_settings_tab(self):
        """初始化设置选项卡"""
        # 下载目录设置
        dir_frame = ctk.CTkFrame(self.settings_tab)
        dir_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(dir_frame, text="下载目录:").pack(side="left", padx=5)
        self.download_dir_var = ctk.StringVar(
            value=str(self.downloader.download_root)
        )
        self.download_dir_entry = ctk.CTkEntry(
            dir_frame,
            textvariable=self.download_dir_var,
            width=400
        )
        self.download_dir_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        ctk.CTkButton(
            dir_frame,
            text="选择目录",
            command=self._select_download_dir
        ).pack(side="right", padx=5)
        
        # 默认质量设置
        quality_frame = ctk.CTkFrame(self.settings_tab)
        quality_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(quality_frame, text="默认质量:").pack(side="left", padx=5)
        self.default_quality_var = ctk.StringVar(
            value=self.downloader.config.get("quality", DownloadQuality.HIGH_1080.name)
        )
        quality_menu = ctk.CTkOptionMenu(
            quality_frame,
            values=[q.name for q in DownloadQuality],
            variable=self.default_quality_var
        )
        quality_menu.pack(side="left", padx=5)
        
        # 默认内容设置
        content_frame = ctk.CTkFrame(self.settings_tab)
        content_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(content_frame, text="默认内容:").pack(side="left", padx=5)
        self.default_content_vars = {}
        default_content = self.downloader.config.get("download_content", [DownloadContent.VIDEO.name])
        for content in DownloadContent:
            var = ctk.BooleanVar(value=content.name in default_content)
            self.default_content_vars[content] = var
            ctk.CTkCheckBox(
                content_frame,
                text=content.value,
                variable=var
            ).pack(side="left", padx=5)
        
        # 默认线程数设置
        threads_frame = ctk.CTkFrame(self.settings_tab)
        threads_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(threads_frame, text="默认线程数:").pack(side="left", padx=5)
        self.default_threads_var = ctk.StringVar(
            value=str(self.downloader.config.get("max_workers", 4))
        )
        threads_entry = ctk.CTkEntry(
            threads_frame,
            width=50,
            textvariable=self.default_threads_var
        )
        threads_entry.pack(side="left", padx=5)
        
        # 代理设置
        proxy_frame = ctk.CTkFrame(self.settings_tab)
        proxy_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(proxy_frame, text="代理服务器:").pack(side="left", padx=5)
        proxies = self.downloader.config.get("proxies", {})
        if not isinstance(proxies, dict):
            proxies = {}
        self.proxy_var = ctk.StringVar(value=proxies.get("http", ""))
        proxy_entry = ctk.CTkEntry(
            proxy_frame,
            textvariable=self.proxy_var,
            width=300,
            placeholder_text="例如: http://127.0.0.1:7890"
        )
        proxy_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # 保存设置按钮
        ctk.CTkButton(
            self.settings_tab,
            text="保存设置",
            command=self._save_settings
        ).pack(padx=10, pady=5)
        
    def _parse_url(self):
        """解析URL并显示视频信息"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("警告", "请输入B站链接")
            return
            
        def parse_thread():
            try:
                # 解析URL
                parsed = self.downloader.parse_url(url)
                
                # 根据类型获取信息
                if parsed["type"] == VideoType.COLLECTION:
                    collection_type = "bvid" if "bvid" in parsed else ("ssid" if "ssid" in parsed else "mlid")
                    info = self.downloader.get_collection_info(parsed[collection_type], collection_type)
                else:
                    info = self.downloader.get_video_info(parsed["bvid"])
                
                if info:
                    self.current_info = info
                    self._update_info_display(info)
                else:
                    messagebox.showerror("错误", "无法解析该链接")
            except Exception as e:
                messagebox.showerror("错误", f"解析失败: {str(e)}")
                
        # 显示解析中的状态
        self.status_bar.configure(text="正在解析链接...")
        threading.Thread(target=parse_thread, daemon=True).start()
        
    def _update_info_display(self, info: Dict):
        """更新视频信息显示"""
        def update():
            # 清除旧的信息
            for widget in self.info_frame.winfo_children():
                widget.destroy()
                
            # 显示新信息
            info_text = f"""
标题: {info['title']}
UP主: {info['author']}
类型: {info['type'].value}
分P数: {len(info['pages'])}
"""
            ctk.CTkLabel(
                self.info_frame,
                text=info_text,
                justify="left"
            ).pack(anchor="w", padx=5, pady=5)
            
            # 更新分P列表
            for widget in self.pages_frame.winfo_children():
                widget.destroy()
            
            # 添加全选/取消全选按钮
            select_frame = ctk.CTkFrame(self.pages_frame)
            select_frame.pack(fill="x", padx=5, pady=2)
            
            # 创建分P选择列表和复选框
            self.page_vars = []
            self.page_checkboxes = []
            
            # 创建滚动框架
            scroll_frame = ctk.CTkScrollableFrame(self.pages_frame)
            scroll_frame.pack(fill="both", expand=True, padx=5, pady=5)
            
            # 先创建所有复选框和变量
            for page in info['pages']:
                var = ctk.BooleanVar(value=True)
                self.page_vars.append(var)
                checkbox = ctk.CTkCheckBox(
                    scroll_frame,
                    text=f"P{page['p']}: {page['title']}",
                    variable=var
                )
                checkbox.pack(fill="x", padx=5, pady=2)
                self.page_checkboxes.append(checkbox)
            
            # 定义全选/取消全选函数
            def select_all():
                for var in self.page_vars:
                    var.set(True)
                
            def deselect_all():
                for var in self.page_vars:
                    var.set(False)
            
            # 添加全选/取消全选按钮
            ctk.CTkButton(
                select_frame,
                text="全选",
                command=select_all,
                width=80
            ).pack(side="left", padx=5)
            
            ctk.CTkButton(
                select_frame,
                text="取消全选",
                command=deselect_all,
                width=80
            ).pack(side="left", padx=5)
                
        self.window.after(0, update)
        
    def _start_download(self):
        """开始下载当前视频/合集"""
        if not self.current_info:
            messagebox.showwarning("警告", "请先解析视频链接")
            return
            
        # 获取选中的分P
        selected_pages = []
        for i, var in enumerate(self.page_vars):
            if var.get():
                selected_pages.append(self.current_info['pages'][i]['p'])
                
        if not selected_pages:
            messagebox.showwarning("警告", "请选择要下载的分P")
            return
            
        # 获取下载设置
        quality = getattr(DownloadQuality, self.quality_var.get())
        content = [
            content for content, var in self.content_vars.items()
            if var.get()
        ]
        try:
            threads = int(self.threads_var.get())
            if not (1 <= threads <= 32):
                messagebox.showerror("错误", "线程数必须在1-32之间")
                return
        except ValueError:
            messagebox.showerror("错误", "线程数必须是有效的数字")
            return
        
        # 开始下载
        def download_thread():
            try:
                # 更新状态
                self.status_bar.configure(text="正在下载...")
                self.download_button.configure(state="disabled")
                self.progress_bar.set(0)
                self.progress_label.configure(text="准备下载...")
                
                # 开始下载
                url = self.url_entry.get().strip()
                self.downloader.download_video(
                    url=url,
                    quality=quality,
                    content=content,
                    custom_max_workers=threads,
                    selected_pages=selected_pages
                )
                
                # 下载完成
                self.window.after(0, lambda: self.status_bar.configure(text="下载完成"))
                self.window.after(0, lambda: self.download_button.configure(state="normal"))
                self.window.after(0, lambda: self.progress_bar.set(1))
                self.window.after(0, lambda: self.progress_label.configure(text="下载完成"))
                self.window.after(0, lambda: messagebox.showinfo("成功", "下载完成！"))
                
            except Exception as e:
                self.window.after(0, lambda: messagebox.showerror("错误", f"下载失败: {str(e)}"))
                self.window.after(0, lambda: self.status_bar.configure(text="下载失败"))
                self.window.after(0, lambda: self.download_button.configure(state="normal"))
                self.window.after(0, lambda: self.progress_label.configure(text="下载失败"))
            
        threading.Thread(target=download_thread, daemon=True).start()
        
    def _select_batch_file(self):
        """选择批量下载文件"""
        file_path = filedialog.askopenfilename(
            title="选择URL文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            self.file_path_var.set(file_path)
            
    def _start_batch_download(self):
        """开始批量下载"""
        file_path = self.file_path_var.get()
        if not file_path:
            messagebox.showwarning("警告", "请选择URL文件")
            return
            
        # 获取下载设置
        quality = getattr(DownloadQuality, self.batch_quality_var.get())
        content = [
            content for content, var in self.batch_content_vars.items()
            if var.get()
        ]
        try:
            threads = int(self.batch_threads_var.get())
            if not (1 <= threads <= 32):
                messagebox.showerror("错误", "线程数必须在1-32之间")
                return
        except ValueError:
            messagebox.showerror("错误", "线程数必须是有效的数字")
            return
        
        # 开始下载
        def download_thread():
            try:
                # 更新状态
                self.status_bar.configure(text="正在下载...")
                self.batch_download_button.configure(state="disabled")
                self.batch_progress_bar.set(0)
                self.batch_progress_label.configure(text="准备下载...")
                
                # 开始下载
                self.downloader.batch_download_from_file(
                    file_path=Path(file_path),
                    quality_name=quality.name,
                    content_names=[c.name for c in content],
                    custom_max_workers=threads
                )
                
                # 下载完成
                self.window.after(0, lambda: self.status_bar.configure(text="下载完成"))
                self.window.after(0, lambda: self.batch_download_button.configure(state="normal"))
                self.window.after(0, lambda: self.batch_progress_bar.set(1))
                self.window.after(0, lambda: self.batch_progress_label.configure(text="下载完成"))
                self.window.after(0, lambda: messagebox.showinfo("成功", "批量下载完成！"))
                
            except Exception as e:
                self.window.after(0, lambda: messagebox.showerror("错误", f"下载失败: {str(e)}"))
                self.window.after(0, lambda: self.status_bar.configure(text="下载失败"))
                self.window.after(0, lambda: self.batch_download_button.configure(state="normal"))
                self.window.after(0, lambda: self.batch_progress_label.configure(text="下载失败"))
            
        threading.Thread(target=download_thread, daemon=True).start()
        
    def _select_download_dir(self):
        """选择下载目录"""
        dir_path = filedialog.askdirectory(
            title="选择下载目录"
        )
        if dir_path:
            self.download_dir_var.set(dir_path)
            
    def _save_settings(self):
        """保存设置"""
        try:
            # 验证线程数
            max_workers = int(self.default_threads_var.get())
            if not (1 <= max_workers <= 32):
                messagebox.showerror("错误", "线程数必须在1-32之间")
                return
                
            # 验证下载路径
            download_path = self.download_dir_var.get()
            if not download_path:
                messagebox.showerror("错误", "请设置下载目录")
                return
                
            # 构建设置
            settings = {
                "download_path": download_path,
                "quality": self.default_quality_var.get(),
                "download_content": [
                    content.name for content, var in self.default_content_vars.items()
                    if var.get()
                ],
                "max_workers": max_workers,
                "proxies": {
                    "http": self.proxy_var.get(),
                    "https": self.proxy_var.get()
                } if self.proxy_var.get() else None
            }
            
            # 保存设置
            if self.downloader.update_settings(settings):
                messagebox.showinfo("成功", "设置已保存")
                self.status_bar.configure(text="设置已保存")
            else:
                messagebox.showerror("错误", "保存设置失败")
                
        except ValueError:
            messagebox.showerror("错误", "线程数必须是有效的数字")
        except Exception as e:
            messagebox.showerror("错误", f"保存设置失败: {str(e)}")
        
    def run(self):
        """运行GUI程序"""
        self.window.mainloop()

if __name__ == "__main__":
    app = BiliDownloaderGUI()
    app.run() 