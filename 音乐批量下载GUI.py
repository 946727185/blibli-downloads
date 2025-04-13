import sys
import os
import re
import requests
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLineEdit, QProgressBar, QMessageBox, QFileDialog
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import time

class DownloadWorker(QThread):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    download_completed = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.is_running = True

    def run(self):
        try:
            # 验证URL格式
            if not self.url.startswith('http'):
                self.error_occurred.emit('请输入有效的URL地址')
                return

            # 创建保存目录
            if not os.path.exists(self.save_path):
                os.makedirs(self.save_path)

            # 获取视频信息
            self.status_updated.emit('正在获取视频信息...')
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(self.url, headers=headers)
            
            # 这里需要根据实际的视频网站API来解析视频信息
            # 示例代码，实际使用时需要替换为真实的解析逻辑
            video_info = {
                'title': 'test_video',
                'url': 'http://example.com/video.mp4'
            }

            # 下载视频
            self.status_updated.emit(f'开始下载: {video_info["title"]}')
            response = requests.get(video_info['url'], headers=headers, stream=True)
            total_size = int(response.headers.get('content-length', 0))
            
            if total_size == 0:
                self.error_occurred.emit('无法获取文件大小')
                return

            block_size = 1024
            downloaded_size = 0
            
            file_path = os.path.join(self.save_path, f"{video_info['title']}.mp4")
            with open(file_path, 'wb') as f:
                for data in response.iter_content(block_size):
                    if not self.is_running:
                        f.close()
                        os.remove(file_path)
                        return
                    
                    downloaded_size += len(data)
                    f.write(data)
                    progress = int((downloaded_size / total_size) * 100)
                    self.progress_updated.emit(progress)

            self.status_updated.emit('下载完成！')
            self.download_completed.emit()

        except Exception as e:
            self.error_occurred.emit(f'下载出错: {str(e)}')

    def stop(self):
        self.is_running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('视频下载器')
        self.setFixedSize(600, 400)
        
        # 创建主窗口部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 创建URL输入框
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('请输入视频URL')
        self.url_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 2px solid #ccc;
                border-radius: 4px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #0078D4;
            }
        """)
        
        # 创建保存路径选择按钮
        self.path_button = QPushButton('选择保存路径')
        self.path_button.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #005A9E;
            }
        """)
        self.path_button.clicked.connect(self.select_save_path)
        
        # 创建下载按钮
        self.download_button = QPushButton('开始下载')
        self.download_button.setStyleSheet("""
            QPushButton {
                background-color: #107C10;
                color: white;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #0B5C0B;
            }
        """)
        self.download_button.clicked.connect(self.start_download)
        
        # 创建进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #ccc;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0078D4;
            }
        """)
        
        # 添加部件到布局
        layout.addWidget(self.url_input)
        layout.addWidget(self.path_button)
        layout.addWidget(self.download_button)
        layout.addWidget(self.progress_bar)
        
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 初始化变量
        self.save_path = os.path.join(os.path.expanduser('~'), 'Downloads')
        self.download_worker = None

    def select_save_path(self):
        path = QFileDialog.getExistingDirectory(self, '选择保存路径', self.save_path)
        if path:
            self.save_path = path

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, '警告', '请输入视频URL')
            return

        self.download_button.setEnabled(False)
        self.progress_bar.setValue(0)
        
        # 创建并启动下载线程
        self.download_worker = DownloadWorker(url, self.save_path)
        self.download_worker.progress_updated.connect(self.update_progress)
        self.download_worker.status_updated.connect(self.update_status)
        self.download_worker.download_completed.connect(self.download_finished)
        self.download_worker.error_occurred.connect(self.handle_error)
        self.download_worker.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.setWindowTitle(f'视频下载器 - {message}')

    def download_finished(self):
        self.download_button.setEnabled(True)
        QMessageBox.information(self, '完成', '下载完成！')

    def handle_error(self, error_message):
        self.download_button.setEnabled(True)
        QMessageBox.critical(self, '错误', error_message)

    def closeEvent(self, event):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.stop()
            self.download_worker.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_()) 