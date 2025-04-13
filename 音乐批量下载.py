import re
import json
import random
import time
import os
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yt_dlp
from rich.console import Console
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    DownloadColumn,
    TransferSpeedColumn
)
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.box import SIMPLE, MINIMAL_DOUBLE_HEAD
import requests
from enum import Enum
import threading

console = Console()

# 反爬配置
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
]

class DownloadQuality(Enum):
    BEST = "bestvideo+bestaudio/best"
    HIGH_1080 = "bestvideo[height>=1080]+bestaudio/best[height>=1080]"
    HIGH_720 = "bestvideo[height>=720]+bestaudio/best[height>=720]"
    MEDIUM_480 = "bestvideo[height>=480]+bestaudio/best[height>=480]"
    LOW_360 = "bestvideo[height>=360]+bestaudio/best[height>=360]"
    AUDIO_ONLY = "bestaudio/best"

class DownloadContent(Enum):
    VIDEO = "视频"
    AUDIO = "音频"
    DANMAKU = "弹幕"
    SUBTITLE = "字幕"
    ALL = "全部"

class VideoType(Enum):
    SINGLE = "单视频"
    COLLECTION = "合集"
    MULTI_PART = "多P视频"
    UP_SERIES = "UP主系列"

class BiliDownloader:
    def __init__(self, status_callback=None, progress_callback=None, error_callback=None):
        self.session = requests.Session()
        self._init_anti_spider()
        self.download_root = Path("./downloads")
        self.download_root.mkdir(exist_ok=True)
        self.config_path = Path("./config.json")
        self.api_cache = {}
        self.page_workers = min(os.cpu_count() * 2, 16)
        self.item_workers = min(os.cpu_count() * 4, 32)
        self.lock = threading.Lock()
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.error_callback = error_callback
        self.load_config()

    def _init_anti_spider(self):
        """初始化反爬设置"""
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://www.bilibili.com/",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        })
        self.proxies = None
        self.min_delay = 1.0
        self.max_delay = 3.0

    def _random_delay(self):
        """随机延迟"""
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _safe_request(self, method, url, **kwargs):
        """安全请求方法，增强版
        
        Args:
            method: 请求方法（GET, POST等）
            url: 请求URL
            **kwargs: 其他请求参数
            
        Returns:
            请求响应
        """
        retry = 0
        max_retries = 5  # 增加重试次数
        
        while retry < max_retries:
            try:
                # 随机延迟
                if retry > 0:
                    delay = random.uniform(1, 3) * retry
                    time.sleep(delay)
                    
                # 设置默认参数    
                kwargs["timeout"] = kwargs.get("timeout", 30)  # 增加超时时间
                
                # 每次请求都更新随机UA
                headers = kwargs.get("headers", {})
                headers["User-Agent"] = random.choice(USER_AGENTS)
                kwargs["headers"] = headers
                
                # 添加重要的请求头
                if "Referer" not in headers:
                    headers["Referer"] = "https://www.bilibili.com/"
                if "Accept" not in headers:
                    headers["Accept"] = "application/json, text/plain, */*"
                if "Accept-Encoding" not in headers:
                    headers["Accept-Encoding"] = "gzip, deflate"
                if "Accept-Language" not in headers:
                    headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
                
                # 添加代理
                if self.proxies:
                    kwargs["proxies"] = self.proxies
                
                # 发起请求
                response = self.session.request(method, url, **kwargs)
                
                # 处理特殊状态码
                if response.status_code == 412:
                    if self.status_callback:
                        self.status_callback(f"触发反爬机制，正在尝试绕过... (尝试 {retry+1}/{max_retries})")
                    retry += 1
                    time.sleep(5 + 5 * retry)  # 逐渐增加等待时间
                    continue
                elif response.status_code == 403:
                    if self.status_callback:
                        self.status_callback(f"访问被拒绝，可能需要登录... (尝试 {retry+1}/{max_retries})")
                    retry += 1
                    time.sleep(3 + 3 * retry)
                    continue
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.HTTPError as e:
                # 处理HTTP错误
                if hasattr(e, 'response') and e.response is not None:
                    if e.response.status_code == 429:  # 请求过多
                        retry += 1
                        wait_time = min(2 ** retry, 60)  # 指数退避，最多等60秒
                        if self.status_callback:
                            self.status_callback(f"请求频繁，等待{wait_time}秒 (尝试 {retry}/{max_retries})")
                        time.sleep(wait_time)
                    elif e.response.status_code in [503, 502, 500]:  # 服务器错误
                        retry += 1
                        wait_time = min(2 ** retry, 30)
                        if self.status_callback:
                            self.status_callback(f"服务器错误，等待{wait_time}秒 (尝试 {retry}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        # 其他HTTP错误
                        if retry < max_retries - 1:
                            retry += 1
                            if self.status_callback:
                                self.status_callback(f"HTTP错误 {e.response.status_code}，重试中 ({retry}/{max_retries})")
                            time.sleep(2 * retry)
                        else:
                            if self.error_callback:
                                self.error_callback("request", str(e))
                            raise
                else:
                    # 没有响应的HTTP错误
                    retry += 1
                    if retry >= max_retries:
                        if self.error_callback:
                            self.error_callback("request", str(e))
                        raise
                    time.sleep(2)
                    
            except (requests.exceptions.ConnectionError, 
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                # 网络连接错误
                retry += 1
                if self.status_callback:
                    self.status_callback(f"网络错误: {str(e)} 重试({retry}/{max_retries})")
                time.sleep(min(4 * retry, 20))  # 最多等20秒
                
            except Exception as e:
                # 未知错误
                retry += 1
                if retry >= max_retries:
                    if self.error_callback:
                        self.error_callback("request", f"请求异常: {str(e)}")
                    raise
                if self.status_callback:
                    self.status_callback(f"请求异常: {str(e)} 重试({retry}/{max_retries})")
                time.sleep(2 * retry)
        
        # 达到最大重试次数
        if self.error_callback:
            self.error_callback("request", f"请求失败: {url}")
        raise Exception(f"请求失败，已达到最大重试次数: {url}")

    def load_config(self):
        """加载配置文件"""
        self.config = {
            "quality": "HIGH_1080",
            "max_workers": 4,
            "download_path": "./downloads",
            "download_content": ["video"],
            "theme": "default",
            "proxies": None
        }
        
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
                if 'proxies' in self.config:
                    self.proxies = self.config['proxies']
            except Exception as e:
                if self.error_callback:
                    self.error_callback("config", f"加载配置文件失败: {str(e)}")

    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            if self.error_callback:
                self.error_callback("config", f"保存配置文件失败: {str(e)}")

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "_", filename).strip()[:100]

    def parse_url(self, url: str) -> Dict:
        parsed = urlparse(url)
        path = parsed.path
        query = parse_qs(parsed.query)

        if "/cheese/play/" in path:
            return {
                "type": VideoType.COLLECTION,
                "ssid": path.split("/cheese/play/")[-1]
            }
        elif "/medialist/play/" in path:
            return {
                "type": VideoType.COLLECTION,
                "mlid": path.split("/medialist/play/")[-1]
            }
        elif "/space.bilibili.com/" in path:
            return {
                "type": VideoType.UP_SERIES,
                "mid": path.split("/")[-1]
            }

        if match := re.search(r"video/(BV\w+)", path):
            bvid = match.group(1)
            if bvid not in self.api_cache:
                api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                response = self._safe_request('GET', api_url)
                self.api_cache[bvid] = response.json().get("data", {})
            
            data = self.api_cache[bvid]
            if "ugc_season" in data:
                return {
                    "type": VideoType.COLLECTION,
                    "bvid": bvid
                }
            else:
                return {
                    "type": VideoType.MULTI_PART if data.get("videos", 1) > 1 else VideoType.SINGLE,
                    "bvid": bvid,
                    "p": int(query.get("p", [1])[0])
                }

        raise ValueError("无法识别的B站URL类型")

    def get_video_info(self, bvid: str) -> Dict:
        """获取视频信息
        
        Args:
            bvid: 视频BV号
            
        Returns:
            视频信息字典
        """
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                if bvid in self.api_cache:
                    data = self.api_cache[bvid]
                else:
                    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                    response = self._safe_request('GET', api_url)
                    response_json = response.json()
                    
                    if response_json.get('code') != 0:
                        raise ValueError(f"获取视频信息失败: {response_json.get('message', '未知错误')}")
                    
                    data = response_json.get('data')
                    if not data:
                        raise ValueError("无法获取视频信息")
                    
                    self.api_cache[bvid] = data
                
                return {
                    "bvid": bvid,
                    "title": self.sanitize_filename(data.get("title", "无标题")),
                    "author": data.get("owner", {}).get("name", "未知UP主"),
                    "author_mid": str(data.get("owner", {}).get("mid", "")),
                    "pages": [
                        {
                            "p": page.get("page", 1),
                            "title": f'P{page.get("page", 1)}_{self.sanitize_filename(page.get("part", "无标题"))}',
                            "duration": page.get("duration", 0),
                            "cid": page.get("cid", 0)
                        } for page in data.get("pages", [])
                    ],
                    "type": VideoType.MULTI_PART if data.get("videos", 1) > 1 else VideoType.SINGLE,
                    "subtitle": data.get("subtitle", "")
                }
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    if self.status_callback:
                        self.status_callback(f"获取视频信息失败，正在重试({retry_count}/{max_retries})...")
                    time.sleep(2)  # 等待2秒后重试
                else:
                    if self.error_callback:
                        self.error_callback(bvid, f"获取视频信息失败: {str(e)}")
                    raise ValueError(f"无法获取视频信息: {str(e)}")
        
        raise ValueError("获取视频信息失败，已达到最大重试次数")

    def get_collection_info(self, collection_id: str, collection_type: str) -> Dict:
        info = {"pages": []}
        
        if collection_type == "bvid":
            data = self.api_cache.get(collection_id, {})
            if not data:
                api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={collection_id}"
                response = self._safe_request('GET', api_url)
                data = response.json().get("data", {})
            
            season_data = data.get("ugc_season", {})
            info.update({
                "bvid": collection_id,
                "title": self.sanitize_filename(data.get("title", "无标题")),
                "author": data.get("owner", {}).get("name", "未知UP主"),
                "author_mid": str(data.get("owner", {}).get("mid", "")),
                "type": VideoType.COLLECTION
            })
            
            for section in season_data.get("sections", []):
                for idx, ep in enumerate(section.get("episodes", []), start=len(info["pages"])+1):
                    info["pages"].append({
                        "p": idx,
                        "title": self.sanitize_filename(ep.get("title", "无标题")),
                        "duration": ep.get("duration", ep.get("arc", {}).get("duration", 0)),
                        "cid": ep.get("cid", 0)
                    })
        else:
            total_pages = self.precheck_collection_size(collection_id, collection_type)
            console.print(f"[yellow]检测到合集包含约{total_pages*100}个视频，开始并行获取...[/yellow]")
            
            with ThreadPoolExecutor(max_workers=self.page_workers) as executor:
                futures = []
                for pn in range(1, total_pages+1):
                    futures.append(executor.submit(
                        self.fetch_collection_page,
                        collection_id, 
                        collection_type,
                        pn
                    ))
                
                episodes = []
                for future in as_completed(futures):
                    try:
                        page_data = future.result()
                        episodes.extend(page_data)
                    except Exception as e:
                        console.print(f"[red]分页获取失败: {str(e)}[/red]")

            with ThreadPoolExecutor(max_workers=self.item_workers) as executor:
                futures = []
                batch_size = 50
                
                for i in range(0, len(episodes), batch_size):
                    batch = episodes[i:i+batch_size]
                    futures.append(executor.submit(
                        self.process_episode_batch,
                        batch,
                        info["pages"],
                        i+1
                    ))
                
                for future in as_completed(futures):
                    future.result()

        return info

    def precheck_collection_size(self, collection_id: str, collection_type: str) -> int:
        try:
            if collection_type == "ssid":
                api_url = f"https://api.bilibili.com/pugv/view/web/season?season_id={collection_id}"
            else:
                api_url = f"https://api.bilibili.com/x/v1/medialist/info?type=8&biz_id={collection_id}"
            
            response = self._safe_request('GET', api_url)
            data = response.json().get("data", {})
            return data.get("page", {}).get("total", 1) if collection_type == "ssid" else data.get("total", 1)
        except:
            return 1

    def fetch_collection_page(self, collection_id: str, collection_type: str, pn: int) -> list:
        retry = 0
        while retry < 3:
            try:
                if collection_type == "ssid":
                    api_url = f"https://api.bilibili.com/pugv/view/web/season?season_id={collection_id}&pn={pn}"
                else:
                    api_url = f"https://api.bilibili.com/x/v1/medialist/info?type=8&biz_id={collection_id}&pn={pn}&ps=100"
                
                response = self._safe_request('GET', api_url)
                data = response.json().get("data", {})
                return data.get("episodes" if collection_type == "ssid" else "medias", [])
            except Exception as e:
                retry += 1
                time.sleep(retry * 1.5)
        raise Exception(f"分页{pn}获取失败")

    def process_episode_batch(self, batch: list, pages: list, start_idx: int):
        temp = []
        for idx, ep in enumerate(batch, start=start_idx):
            duration = ep.get("duration") or \
                      ep.get("timelength", 0) // 1000 or \
                      ep.get("archive", {}).get("duration", 0)
            
            temp.append({
                "p": idx,
                "title": self.sanitize_filename(ep.get("title", "无标题")),
                "duration": duration,
                "cid": ep.get("cid", 0)
            })
        
        with self.lock:
            pages.extend(temp)

    def show_video_info(self, info: Dict):
        info_panel = Panel(
            Text.from_markup(f"""
[bold cyan]╭────────────── 视频信息 ──────────────╮[/bold cyan]
│                                              │
│  [bold]📺 标题:[/bold] {info['title']}
│  [bold]👤 UP主:[/bold] {info['author']}
│  [bold]📁 类型:[/bold] {info['type'].value}
│  [bold]📑 分集数:[/bold] {len(info['pages'])}
│                                              │
[bold cyan]╰──────────────────────────────────────╯[/bold cyan]
            """),
            border_style="cyan",
            title="[bold blue]🎯 视频详情[/bold blue]",
            padding=(1, 2)
        )
        console.print(info_panel)

    def create_pages_table(self, pages: List[Dict], expanded: bool) -> Table:
        table = Table(
            title="[bold blue]📑 分集列表[/bold blue]" + (" [已展开]" if expanded else " [已折叠]"),
            box=MINIMAL_DOUBLE_HEAD,
            border_style="cyan",
            expand=True,
            padding=(0, 2),
            title_style="bold blue",
            header_style="bold cyan"
        )
        
        table.add_column("序号", style="cyan", justify="center", width=6)
        table.add_column("标题", style="green")
        table.add_column("时长", style="yellow", width=10, justify="right")
        
        display_pages = pages if expanded else pages[:5]
        
        for p in display_pages:
            duration = p["duration"]
            duration_str = f"{duration//60:02d}:{duration%60:02d}"
            table.add_row(
                f"P{p['p']}", 
                p["title"],
                duration_str
            )
        
        if not expanded and len(pages) > 5:
            table.add_row(
                "...", 
                f"[dim]还有{len(pages)-5}个分集未显示[/dim]", 
                "..."
            )
        
        return table

    def select_pages_interactive(self, pages: List[Dict]) -> List[int]:
        expanded = False
        while True:
            table = self.create_pages_table(pages, expanded)
            console.print("\n")  
            console.print(table)
            
            console.print("\n[dim]操作说明:[/dim]")
            console.print("[dim]• e: 展开/折叠分集列表[/dim]")
            console.print("[dim]• s: 进入选择模式[/dim]")
            console.print("[dim]• b: 返回上级菜单[/dim]")
            
            action = Prompt.ask(
                "\n[bold cyan]➜[/bold cyan] 操作选择 (e/s/b)",
                choices=["e", "s", "b"],
                show_choices=False,
                default="s"
            )
            
            if action == "e":
                expanded = not expanded
                continue
            elif action == "s":
                break
            elif action == "b":
                return []

        while True:
            selected = Prompt.ask("\n[bold cyan]➜[/bold cyan] 选择分集 (逗号分隔/all)", default="all")
            try:
                if selected.lower() == "all":
                    return [p["p"] for p in pages]
                return sorted({int(x) for x in selected.split(",")})
            except:
                console.print("[red]输入格式错误，请重新输入[/red]")

    def download_task(self, url: str, output_dir: Path, filename: str, 
                     progress, main_task, quality: DownloadQuality, 
                     content: List[DownloadContent], cid: Optional[int] = None,
                     video_type: VideoType = VideoType.SINGLE):
        """下载单个任务"""
        # 定义进度钩子类
        class ProgressHook:
            def __init__(self, progress_bar, task_id, progress_callback=None):
                self.progress_bar = progress_bar
                self.task_id = task_id
                self.progress_callback = progress_callback
                self.last_update = 0
                
            def __call__(self, d):
                if d['status'] == 'downloading':
                    try:
                        downloaded = d.get('downloaded_bytes', 0)
                        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                        speed = d.get('speed', 0)
                        
                        # 更新进度条
                        if total > 0:
                            self.progress_bar.update(
                                self.task_id,
                                completed=downloaded,
                                total=total,
                                description=f"[cyan]下载 {filename[:20]}... {downloaded/total*100:.1f}%"
                            )
                        
                        # 通过回调更新GUI
                        if self.progress_callback:
                            current_time = time.time()
                            if current_time - self.last_update >= 0.1:  # 限制更新频率
                                self.progress_callback(str(self.task_id), downloaded, total, speed/1024/1024)
                                self.last_update = current_time
                                
                    except Exception as e:
                        if self.progress_callback:
                            self.progress_callback(str(self.task_id), 0, 0, 0)
                
                elif d['status'] == 'finished':
                    self.progress_bar.update(self.task_id, description=f"[green]处理 {filename[:20]}...")
                    
                elif d['status'] == 'error':
                    self.progress_bar.update(self.task_id, description=f"[red]失败 {filename[:20]}")

        # 确保文件名不包含扩展名
        filename = os.path.splitext(filename)[0]
        
        # 如果是单个视频，直接使用视频标题作为文件名
        if video_type == VideoType.SINGLE:
            try:
                parsed = self.parse_url(url)
                if "bvid" in parsed:
                    info = self.get_video_info(parsed["bvid"])
                    if info and info.get("title"):
                        filename = self.sanitize_filename(info["title"])
            except:
                pass

        # 分别处理视频和音频下载
        if DownloadContent.VIDEO in content and DownloadContent.AUDIO in content:
            # 下载视频（包含音频）
            video_opts = {
                'outtmpl': {
                    'default': str(output_dir / f'{filename}_video.%(ext)s'),
                },
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'ignoreerrors': True,
                'progress_hooks': [],
                'noprogress': True,
                'writethumbnail': False,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'no_playlist': True,
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }]
            }

            # 下载音频
            audio_opts = {
                'outtmpl': {
                    'default': str(output_dir / f'{filename}_audio.%(ext)s'),
                },
                'format': 'bestaudio/best',
                'merge_output_format': 'mp3',
                'ignoreerrors': True,
                'progress_hooks': [],
                'noprogress': True,
                'writethumbnail': False,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'no_playlist': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }]
            }

            task_id = progress.add_task(f"[cyan]下载 {filename[:20]}...", start=False)
            progress_hook = ProgressHook(progress, task_id, self.progress_callback)
            video_opts['progress_hooks'].append(progress_hook)
            audio_opts['progress_hooks'].append(progress_hook)

            try:
                # 先下载并合并视频
                with yt_dlp.YoutubeDL(video_opts) as ydl:
                    progress.start_task(task_id)
                    ydl.download([url])

                # 再下载音频
                with yt_dlp.YoutubeDL(audio_opts) as ydl:
                    ydl.download([url])

                if cid and DownloadContent.DANMAKU in content:
                    self.download_danmaku(cid, output_dir / filename)

                progress.update(task_id, visible=False)
                progress.advance(main_task)
                return True

            except Exception as e:
                progress.update(task_id, description=f"[red]失败 {filename[:20]}")
                if self.error_callback:
                    self.error_callback(filename, str(e))
                return False

        else:
            # 原有的单一下载逻辑
            is_audio_only = quality == DownloadQuality.AUDIO_ONLY or all(c in [DownloadContent.AUDIO, DownloadContent.DANMAKU, DownloadContent.SUBTITLE] for c in content)
            
            ydl_opts = {
                'outtmpl': {
                    'default': str(output_dir / f'{filename}.%(ext)s'),
                },
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if DownloadContent.VIDEO in content else 'bestaudio/best',
                'merge_output_format': 'mp4' if not is_audio_only else None,
                'writesubtitles': DownloadContent.SUBTITLE in content,
                'ignoreerrors': True,
                'progress_hooks': [],
                'noprogress': True,
                'writethumbnail': False,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'no_playlist': True,
                'postprocessors': []
            }

            if is_audio_only or DownloadContent.AUDIO in content:
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '320',
                    }],
                    'extractaudio': True,
                    'audioformat': 'mp3',
                })
            elif DownloadContent.VIDEO in content:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }]

            task_id = progress.add_task(f"[cyan]下载 {filename[:20]}...", start=False)
            ydl_opts['progress_hooks'].append(ProgressHook(progress, task_id, self.progress_callback))

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    progress.start_task(task_id)
                    ydl.download([url])
                    
                    if cid and DownloadContent.DANMAKU in content:
                        self.download_danmaku(cid, output_dir / filename)
                    
                    progress.update(task_id, visible=False)
                    progress.advance(main_task)
                    return True
                    
            except Exception as e:
                progress.update(task_id, description=f"[red]失败 {filename[:20]}")
                if self.error_callback:
                    self.error_callback(filename, str(e))
                return False

    def _ensure_correct_filename(self, output_dir: Path, desired_filename: str, is_audio_only: bool):
        """确保文件使用正确的文件名"""
        ext = '.mp3' if is_audio_only else '.mp4'
        desired_file = output_dir / f"{desired_filename}{ext}"
        
        # 查找可能的临时文件或其他格式文件
        for file in output_dir.glob(f"{desired_filename}.*"):
            if file.suffix.lower() in ['.mp3', '.mp4', '.m4a', '.webm']:
                try:
                    # 如果文件名不正确，进行重命名
                    if file != desired_file:
                        if desired_file.exists():
                            desired_file.unlink()  # 如果目标文件已存在，先删除
                        file.rename(desired_file)
                except Exception as e:
                    if self.error_callback:
                        self.error_callback("rename", f"重命名文件失败: {str(e)}")

    def download_danmaku(self, cid: int, output_path: Path):
        try:
            url = f"https://comment.bilibili.com/{cid}.xml"
            response = self._safe_request('GET', url)
            with open(output_path.with_suffix(".xml"), 'wb') as f:
                f.write(response.content)
            return True
        except Exception as e:
            console.print(f"[red]弹幕下载失败: {str(e)}[/red]")
            return False

    def download_video(self, url: str, quality: DownloadQuality = None, content: List[DownloadContent] = None,
                    custom_max_workers: int = None, selected_pages: List[int] = None):
        """下载单个视频或合集
        
        Args:
            url: 视频链接
            quality: 下载质量
            content: 下载内容列表
            custom_max_workers: 自定义线程数
            selected_pages: 选中的分P列表，如果为None则下载全部分P
        """
        try:
            if self.status_callback:
                self.status_callback("正在解析视频信息...")
            
            # 解析URL
            parsed = self.parse_url(url)
            
            # 获取视频信息
            if parsed["type"] == VideoType.COLLECTION:
                collection_type = "bvid" if "bvid" in parsed else ("ssid" if "ssid" in parsed else "mlid")
                info = self.get_collection_info(parsed[collection_type], collection_type)
            else:
                info = self.get_video_info(parsed["bvid"])
                
            if not info:
                raise Exception("无法获取视频信息")
                
            # 过滤选中的分P
            if selected_pages:
                info['pages'] = [page for page in info['pages'] if page['p'] in selected_pages]
                if not info['pages']:
                    raise Exception("未选择任何分P")
                
            # 设置下载参数
            if not quality:
                quality = getattr(DownloadQuality, self.config.get("quality", "HIGH_1080"))
            if not content:
                content_names = self.config.get("download_content", ["VIDEO"])
                content = [getattr(DownloadContent, name) for name in content_names]
            
            # 设置输出目录
            output_dir = self.download_root / info['type'].value / self.sanitize_filename(info["author"]) / self.sanitize_filename(info["title"])
            output_dir.mkdir(parents=True, exist_ok=True)
            
            if self.status_callback:
                self.status_callback(f"准备下载到: {output_dir}")
                
            # 本次直接使用单线程下载，确保稳定性
            max_workers = 1
            
            # 创建任务列表
            download_tasks = []
            for page in info['pages']:
                # 记录需要下载的内容，支持视频和音频
                for content_type in content:
                    if content_type in [DownloadContent.VIDEO, DownloadContent.AUDIO]:
                        download_tasks.append({
                            "page": page,
                            "content_type": content_type
                        })
            
            # 开始下载
            total_tasks = len(download_tasks)
            current_task = 0
            success_count = 0
            
            if self.status_callback:
                self.status_callback(f"开始下载 {total_tasks} 个文件...")
            
            for task in download_tasks:
                current_task += 1
                page = task["page"]
                content_type = task["content_type"]
                
                # 更新状态
                if self.status_callback:
                    self.status_callback(f"下载中 ({current_task}/{total_tasks}): P{page['p']} - {content_type.value}")
                
                # 调用直接下载方法
                success = self._direct_download(info, page, quality, content_type, output_dir)
                if success:
                    success_count += 1
                
                # 更新进度
                if self.progress_callback:
                    self.progress_callback("main", current_task, total_tasks, 0)
            
            # 检查是否所有文件都下载成功
            if success_count == 0:
                raise Exception("所有下载任务均失败")
            
            if success_count < total_tasks:
                if self.status_callback:
                    self.status_callback(f"部分下载完成 ({success_count}/{total_tasks})")
            else:
                if self.status_callback:
                    self.status_callback(f"全部下载完成 ({success_count}/{total_tasks})")
            
            return True
            
        except Exception as e:
            if self.error_callback:
                self.error_callback("download", str(e))
            return False
            
    def _direct_download(self, info: Dict, page: Dict, quality: DownloadQuality, 
                         content_type: DownloadContent, download_dir: Path) -> bool:
        """直接使用纯API下载视频和音频，完全不依赖yt-dlp
        
        Args:
            info: 视频信息
            page: 分P信息
            quality: 下载质量
            content_type: 下载内容类型
            download_dir: 下载目录
            
        Returns:
            是否下载成功
        """
        try:
            # 构建输出文件名
            output_filename = f"P{page['p']}_{self._sanitize_filename(page['title'])}"
            
            # 根据内容类型选择下载方式
            if content_type == DownloadContent.VIDEO:
                output_path = download_dir / f"{output_filename}.mp4"
                file_type = "视频"
            elif content_type == DownloadContent.AUDIO:
                output_path = download_dir / f"{output_filename}.mp3"
                file_type = "音频"
            else:
                return False
                
            # 如果文件已存在且大小不为0，跳过下载
            if output_path.exists() and output_path.stat().st_size > 0:
                if self.status_callback:
                    self.status_callback(f"文件已存在: {output_path.name}")
                return True
            
            # 获取视频下载地址
            # 尝试所有可能的API接口
            api_urls = [
                f"https://api.bilibili.com/x/player/playurl?bvid={info['bvid']}&cid={page['cid']}&qn=112&fnval=16&fourk=1",
                f"https://api.bilibili.com/x/player/wbi/playurl?bvid={info['bvid']}&cid={page['cid']}&qn=112&fnval=4048&fourk=1",
                f"https://api.bilibili.com/pgc/player/web/playurl?bvid={info['bvid']}&cid={page['cid']}&qn=112",
                f"https://api.bilibili.com/x/player/playurl?bvid={info['bvid']}&cid={page['cid']}&qn=80"
            ]
            
            if self.status_callback:
                self.status_callback(f"获取{file_type}下载地址...")
            
            # 对于视频下载，我们需要同时获取视频和音频流
            video_url = None
            audio_url = None
            error_msgs = []
            api_data = None
            
            # 尝试所有可能的API
            for api_url in api_urls:
                try:
                    response = self._safe_request("GET", api_url)
                    data = response.json()
                    
                    # 检查API响应
                    if data.get('code') != 0:
                        error_msgs.append(f"API错误: {data.get('message', '未知错误')}")
                        continue
                        
                    data = data.get('data', {})
                    if not data:
                        error_msgs.append("API返回数据为空")
                        continue
                    
                    # 保存API数据
                    api_data = data
                    
                    # 提取下载URL
                    if content_type == DownloadContent.AUDIO:
                        # 音频下载 - 从dash或durl获取音频URL
                        if 'dash' in data and 'audio' in data['dash'] and len(data['dash']['audio']) > 0:
                            audios = sorted(data['dash']['audio'], key=lambda x: x.get('bandwidth', 0), reverse=True)
                            if audios:
                                audio_url = audios[0]['baseUrl']
                                break
                        elif 'durl' in data and len(data['durl']) > 0:
                            audio_url = data['durl'][0]['url']
                            break
                    else:
                        # 视频下载 - 检查是否有dash格式（分离的视频和音频）
                        if 'dash' in data:
                            dash = data['dash']
                            # 获取视频流
                            if 'video' in dash and len(dash['video']) > 0:
                                videos = sorted(dash['video'], key=lambda x: x.get('bandwidth', 0), reverse=True)
                                if videos:
                                    video_url = videos[0]['baseUrl']
                            
                            # 获取音频流
                            if 'audio' in dash and len(dash['audio']) > 0:
                                audios = sorted(dash['audio'], key=lambda x: x.get('bandwidth', 0), reverse=True)
                                if audios:
                                    audio_url = audios[0]['baseUrl']
                            
                            # 如果都获取到了，就可以跳出循环
                            if video_url and audio_url:
                                break
                        # 如果没有dash格式，尝试获取普通URL
                        elif 'durl' in data and len(data['durl']) > 0:
                            video_url = data['durl'][0]['url']
                            # 这里没有单独的音频流，可能是已经合并好的
                            break
                except Exception as e:
                    error_msgs.append(f"API调用异常: {str(e)}")
                    continue
            
            # 如果是视频下载，但未获取到必要的URL
            if content_type == DownloadContent.VIDEO:
                if not video_url:
                    error_msg = "无法获取视频下载地址: " + "; ".join(error_msgs)
                    raise Exception(error_msg)
            # 如果是音频下载，但未获取到音频URL
            elif content_type == DownloadContent.AUDIO:
                if not audio_url:
                    error_msg = "无法获取音频下载地址: " + "; ".join(error_msgs)
                    raise Exception(error_msg)
            
            # 添加必要的请求头
            headers = {
                'Referer': 'https://www.bilibili.com',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Range': 'bytes=0-'  # 支持断点续传
            }
            
            # 根据内容类型和获取到的URL进行下载
            if content_type == DownloadContent.AUDIO:
                # 音频下载
                if self.status_callback:
                    self.status_callback(f"开始下载音频: {output_path.name}")
                
                # 下载音频文件
                self._download_file(audio_url, output_path, headers, f"download_{page['p']}_audio")
                
                # 如果需要转换音频格式
                if output_path.suffix != '.mp3':
                    try:
                        self._convert_to_mp3(output_path, download_dir / f"{output_filename}_temp.mp3")
                    except Exception as e:
                        if self.status_callback:
                            self.status_callback(f"音频转换失败: {str(e)}")
                
            else:
                # 视频下载
                if self.status_callback:
                    self.status_callback(f"开始下载视频: {output_path.name}")
                
                # 如果有分离的视频和音频流，需要下载后合并
                if video_url and audio_url:
                    # 分别下载视频和音频
                    video_temp = download_dir / f"{output_filename}_video_temp.mp4"
                    audio_temp = download_dir / f"{output_filename}_audio_temp.m4a"
                    
                    if self.status_callback:
                        self.status_callback("下载视频流...")
                    self._download_file(video_url, video_temp, headers, f"download_{page['p']}_video")
                    
                    if self.status_callback:
                        self.status_callback("下载音频流...")
                    self._download_file(audio_url, audio_temp, headers, f"download_{page['p']}_audio")
                    
                    # 使用ffmpeg合并视频和音频
                    if self.status_callback:
                        self.status_callback("合并视频和音频...")
                    
                    try:
                        import subprocess
                        
                        # 确保目标文件不存在
                        if output_path.exists():
                            output_path.unlink()
                        
                        # 构建ffmpeg命令
                        ffmpeg_cmd = [
                            'ffmpeg',
                            '-i', str(video_temp),
                            '-i', str(audio_temp),
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            '-strict', 'experimental',
                            str(output_path),
                            '-y'
                        ]
                        
                        # 执行合并
                        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        
                        # 清理临时文件
                        if video_temp.exists():
                            video_temp.unlink()
                        if audio_temp.exists():
                            audio_temp.unlink()
                            
                    except Exception as e:
                        if self.status_callback:
                            self.status_callback(f"合并视频失败: {str(e)}，尝试直接下载...")
                        
                        # 如果合并失败，尝试直接下载durl视频
                        if api_data and 'durl' in api_data and len(api_data['durl']) > 0:
                            direct_url = api_data['durl'][0]['url']
                            self._download_file(direct_url, output_path, headers, f"download_{page['p']}_direct")
                        else:
                            raise Exception(f"无法合并视频和音频: {str(e)}")
                else:
                    # 直接下载完整视频
                    self._download_file(video_url, output_path, headers, f"download_{page['p']}_video")
            
            # 验证下载结果
            if not output_path.exists():
                raise Exception(f"下载后文件不存在: {output_path.name}")
                
            actual_size = output_path.stat().st_size
            if actual_size == 0:
                raise Exception(f"下载文件大小为0: {output_path.name}")
                
            # 完成下载
            if self.status_callback:
                self.status_callback(f"{file_type}下载完成: {output_path.name}")
                
            return True
            
        except Exception as e:
            error_msg = f"下载失败: {str(e)}"
            if self.status_callback:
                self.status_callback(error_msg)
                
            if self.error_callback:
                self.error_callback(f"download_{page['p']}_{content_type.name}", error_msg)
                
            return False
            
    def _download_file(self, url: str, output_path: Path, headers: Dict, task_id: str) -> bool:
        """下载单个文件的通用方法
        
        Args:
            url: 下载URL
            output_path: 输出路径
            headers: HTTP头信息
            task_id: 任务ID，用于进度回调
            
        Returns:
            是否下载成功
        """
        # 强制使用流式下载
        response = self._safe_request("GET", url, headers=headers, stream=True, timeout=30)
        total_size = int(response.headers.get('content-length', 0))
        
        # 确保响应是成功的
        if response.status_code not in [200, 206]:  # 200正常, 206部分内容
            raise Exception(f"下载请求失败: HTTP {response.status_code}")
            
        downloaded = 0
        last_progress_time = time.time()
        chunk_size = 1024 * 1024  # 1MB
        start_time = time.time()
        
        # 实际下载文件
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # 计算下载速度
                    current_time = time.time()
                    elapsed = current_time - start_time
                    speed = downloaded / elapsed / 1024 / 1024 if elapsed > 0 else 0
                    
                    # 更新进度，但不要太频繁
                    if current_time - last_progress_time >= 0.2:  # 200ms更新一次
                        if self.progress_callback:
                            # 回调通知GUI更新进度条
                            self.progress_callback(
                                task_id,
                                downloaded, 
                                total_size,
                                speed
                            )
                            
                        if self.status_callback:
                            percent = (downloaded / total_size * 100) if total_size > 0 else 0
                            self.status_callback(f"下载中: {percent:.1f}% | 速度: {speed:.1f}MB/s")
                            
                        last_progress_time = current_time
                        
        return True
        
    def _convert_to_mp3(self, input_path: Path, output_path: Path) -> bool:
        """将音频文件转换为MP3格式
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            
        Returns:
            是否转换成功
        """
        if self.status_callback:
            self.status_callback("转换音频格式...")
        
        # 尝试使用ffmpeg将下载的音频转换为mp3
        import subprocess
        
        # 使用subprocess而不是os.system，更安全
        ffmpeg_cmd = [
            'ffmpeg', 
            '-i', str(input_path), 
            '-vn', 
            '-acodec', 'libmp3lame', 
            '-q:a', '4', 
            str(output_path), 
            '-y'
        ]
        
        # 执行转换并等待完成
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # 检查转换结果
        if output_path.exists() and output_path.stat().st_size > 0:
            # 替换原文件
            if input_path.exists():
                input_path.unlink()
            output_path.rename(input_path)
            return True
        
        return False

    def _create_download_dir(self, info: Dict) -> Path:
        """创建下载目录
        
        Args:
            info: 视频信息字典
            
        Returns:
            下载目录路径
        """
        # 创建下载目录结构：类型/UP主/视频标题
        download_dir = self.download_root / info['type'].value / self._sanitize_filename(info["author"]) / self._sanitize_filename(info["title"])
        download_dir.mkdir(parents=True, exist_ok=True)
        return download_dir
        
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的文件名
        """
        # 替换Windows下的非法字符
        illegal_chars = '<>:"/\\|?*'
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        return filename.strip()
        
    def _download_single(self, info: Dict, page: Dict, quality: DownloadQuality,
                        content_type: DownloadContent, download_dir: Path) -> bool:
        """下载单个文件
        
        Args:
            info: 视频信息
            page: 分P信息
            quality: 下载质量
            content_type: 下载内容类型
            download_dir: 下载目录
            
        Returns:
            是否下载成功
        """
        try:
            # 构建视频URL
            video_url = f"https://www.bilibili.com/video/{info['bvid']}"
            if info['type'] == VideoType.COLLECTION:
                video_url += f"?p={page['p']}"
                
            # 构建输出文件名
            output_filename = f"P{page['p']}_{self._sanitize_filename(page['title'])}"
            
            # 根据内容类型选择下载方式
            if content_type == DownloadContent.VIDEO:
                output_path = download_dir / f"{output_filename}.mp4"
            elif content_type == DownloadContent.AUDIO:
                output_path = download_dir / f"{output_filename}.mp3"
            else:
                return False
                
            # 如果文件已存在且大小不为0，跳过下载
            if output_path.exists() and output_path.stat().st_size > 0:
                if self.status_callback:
                    self.status_callback(f"文件已存在，跳过下载: {output_path}")
                return True
                
            # 记录初始状态
            file_existed_before = output_path.exists()
            initial_size = output_path.stat().st_size if file_existed_before else 0
            
            # 调用yt-dlp下载
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if content_type == DownloadContent.VIDEO else 'bestaudio/best',
                'outtmpl': str(output_path),
                'quiet': True,
                'no_warnings': True,
                'extract_audio': content_type == DownloadContent.AUDIO,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }] if content_type == DownloadContent.AUDIO else [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }],
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                'extractor_retries': 5,
                'http_headers': {  # 添加必要的请求头
                    'Referer': 'https://www.bilibili.com',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                },
                'cookiesfrombrowser': ('chrome',), # 从浏览器获取cookies以应对需要登录的视频
                'writeinfojson': True, # 保存视频信息以便调试
                'verbose': True, # 更详细的输出
            }
            
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([video_url])
                    
                    # 验证文件是否成功下载
                    if not output_path.exists():
                        raise Exception(f"下载后文件不存在: {output_path}")
                    
                    # 如果文件没有增长，视为下载失败
                    if output_path.stat().st_size <= initial_size:
                        raise Exception(f"文件大小未变化，可能下载失败: {output_path}")
                    
                    if self.status_callback:
                        self.status_callback(f"下载成功: {output_path}")
                    
                    return True
                    
                except Exception as e:
                    retry_count += 1
                    error_msg = str(e)
                    if self.status_callback:
                        self.status_callback(f"下载失败({retry_count}/{max_retries}): {error_msg}")
                    
                    # 尝试使用直接API下载
                    if retry_count == max_retries:
                        try:
                            # 直接使用requests下载
                            if self.status_callback:
                                self.status_callback(f"尝试使用备用方法下载...")
                            
                            # 尝试获取视频真实地址
                            api_url = f"https://api.bilibili.com/x/player/playurl?bvid={info['bvid']}&cid={page['cid']}&qn=80&fnval=16"
                            response = self._safe_request("GET", api_url)
                            data = response.json().get('data', {})
                            
                            if not data or 'durl' not in data:
                                raise Exception("无法获取视频下载地址")
                            
                            # 获取下载地址
                            download_url = data['durl'][0]['url']
                            
                            # 下载视频
                            headers = {
                                'Referer': 'https://www.bilibili.com',
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                            }
                            
                            response = self._safe_request("GET", download_url, headers=headers, stream=True)
                            with open(output_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                            
                            # 验证文件大小
                            if output_path.stat().st_size > 0:
                                if self.status_callback:
                                    self.status_callback(f"备用方法下载成功: {output_path}")
                                return True
                            else:
                                raise Exception("下载文件大小为0")
                            
                        except Exception as direct_error:
                            if self.status_callback:
                                self.status_callback(f"备用下载方法失败: {str(direct_error)}")
                            raise
                    
                    if retry_count < max_retries:
                        time.sleep(2)  # 等待2秒后重试
                    else:
                        raise  # 重试次数用完，抛出异常
            
            return False
            
        except Exception as e:
            error_msg = f"下载失败: {str(e)}"
            if "HTTP Error 404" in str(e):
                error_msg = "视频不存在或已被删除"
            elif "HTTP Error 403" in str(e):
                error_msg = "访问被拒绝，可能需要登录或cookies已过期"
            elif "KeyError" in str(e):
                error_msg = "解析视频信息失败，请检查视频是否可以正常访问"
            
            if self.error_callback:
                self.error_callback(video_url, error_msg)
            return False
            
    def _error_callback(self, task_id: str, error: str):
        """处理错误回调
        
        Args:
            task_id: 任务ID（通常是URL）
            error: 错误信息
        """
        if self.error_callback:
            self.error_callback(task_id, error)

    def batch_download_from_file(self, file_path: Path):
        file_path = Path(str(file_path).strip().strip("'").strip('"'))
        if not file_path.exists():
            console.print(f"[red]文件不存在: {file_path}[/red]")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip()]
            
            if not urls:
                console.print("[red]文件中没有有效的URL[/red]")
                return

            console.print("\n[bold cyan]╭────────── 批量下载设置 ──────────╮[/bold cyan]")
            quality = self.select_quality()
            content = self.select_content()
            max_workers = self._get_valid_max_workers()
            console.print("[bold cyan]╰──────────────────────────────────╯[/bold cyan]\n")

            self.config["max_workers"] = max_workers
            self.save_config()

            for url in urls:
                console.print(f"\n[cyan]开始下载: {url}[/cyan]")
                self.download_video(url, quality=quality, content=content, batch_mode=True)
        except Exception as e:
            console.print(f"[red]批量下载失败: {str(e)}[/red]")

    def _get_valid_max_workers(self) -> int:
        """获取有效线程数（1-32）"""
        while True:
            try:
                max_workers = IntPrompt.ask("下载线程数 (1-32)", default=self.config.get("max_workers", 4))
                if 1 <= max_workers <= 32:
                    return max_workers
                console.print("[red]请输入1-32之间的数字[/red]")
            except:
                console.print("[red]输入无效，请重新输入[/red]")

    def single_download(self):
        url = Prompt.ask(
            "\n[bold cyan]➜[/bold cyan] 输入视频链接 (或输入 back 返回)", 
            default="back"
        )
        if url.lower() == "back":
            return
        
        # 新增单视频线程数选择
        console.print("\n[bold cyan]╭────────── 下载设置 ──────────╮[/bold cyan]")
        quality = self.select_quality()
        content = self.select_content()
        max_workers = self._get_valid_max_workers()
        console.print("[bold cyan]╰──────────────────────────────╯[/bold cyan]\n")
        
        self.download_video(
            url, 
            quality=quality,
            content=content,
            custom_max_workers=max_workers  # 传递自定义线程数
        )

    def select_quality(self) -> DownloadQuality:
        table = Table(title="视频质量", box=SIMPLE)
        table.add_column("编号", style="cyan")
        table.add_column("质量", style="green")
        for i, q in enumerate(DownloadQuality, 1):
            table.add_row(str(i), q.name.replace("_", " "))
        
        console.print(table)
        
        while True:
            choice = Prompt.ask("选择质量 (1-6)", default="1")
            try:
                return list(DownloadQuality)[int(choice)-1]
            except:
                console.print("[red]无效选择，请重新输入[/red]")

    def select_content(self) -> List[DownloadContent]:
        table = Table(title="下载内容", box=SIMPLE)
        table.add_column("编号", style="cyan")
        table.add_column("内容", style="green")
        for i, c in enumerate(DownloadContent, 1):
            table.add_row(str(i), c.value)
        
        console.print(table)
        
        while True:
            choices = Prompt.ask("选择内容 (逗号分隔)", default="1")
            try:
                selected = [list(DownloadContent)[int(x)-1] for x in choices.split(",")]
                if DownloadContent.ALL in selected:
                    return list(DownloadContent)
                return selected
            except:
                console.print("[red]无效选择，请重新输入[/red]")

    def show_settings(self):
        settings_table = Table(
            title="[bold blue]当前设置[/bold blue]",
            box=SIMPLE,
            title_style="bold blue",
            border_style="cyan"
        )
        settings_table.add_column("设置项", style="cyan", justify="right")
        settings_table.add_column("值", style="green")
        
        settings_table.add_row("📁 下载目录", str(self.download_root))
        settings_table.add_row("🎥 默认质量", self.config.get("quality", "HIGH_1080"))
        settings_table.add_row("⚡ 最大线程", str(self.config.get("max_workers", 4)))
        settings_table.add_row("🛡️ 当前代理", str(self.proxies or "无"))
        
        console.print(Panel(
            settings_table,
            border_style="cyan",
            padding=(1,2)
        ))
        
        if Confirm.ask("[bold cyan]→[/bold cyan] 是否修改设置?"):
            self.change_settings()

    def change_settings(self):
        new_path = Prompt.ask(f"新下载目录 (当前: {self.download_root})", default=str(self.download_root))
        self.download_root = Path(new_path)
        self.download_root.mkdir(parents=True, exist_ok=True)
        
        if Confirm.ask("是否配置代理？"):
            proxy = Prompt.ask("输入代理地址 (格式: http://ip:port)", default="")
            if proxy:
                self.proxies = {"http": proxy, "https": proxy}
                self.config["proxies"] = self.proxies
        
        # 修改线程数设置逻辑
        self.config["max_workers"] = self._get_valid_max_workers()
        self.config["quality"] = self.select_quality().name
        self.save_config()
        console.print("[green]设置已保存![/green]")

    def update_settings(self, settings: Dict):
        """更新下载器设置
        
        Args:
            settings (Dict): 包含以下键的字典：
                - download_path: 下载路径
                - quality: 默认质量
                - download_content: 默认下载内容列表
                - max_workers: 最大线程数
                - proxies: 代理设置
        """
        try:
            # 更新下载路径
            if "download_path" in settings:
                self.download_root = Path(settings["download_path"])
                self.download_root.mkdir(parents=True, exist_ok=True)
            
            # 更新其他设置
            self.config.update({
                "quality": settings.get("quality", self.config.get("quality")),
                "max_workers": settings.get("max_workers", self.config.get("max_workers")),
                "download_content": settings.get("download_content", self.config.get("download_content")),
                "proxies": settings.get("proxies")
            })
            
            # 更新代理设置
            self.proxies = settings.get("proxies")
            
            # 保存配置
            self.save_config()
            
            if self.status_callback:
                self.status_callback("设置已保存")
            return True
            
        except Exception as e:
            if self.error_callback:
                self.error_callback("settings", f"保存设置失败: {str(e)}")
            return False

    def run(self):
        console.print(Panel.fit(r"""
[bold blue]╭──────────────────────────────────╮
│        哔哩下载助手 v4.3        │
│                                  │
│   [cyan]██████[/cyan]╗ [red]██[/red]╗     [red]██[/red]╗[yellow]██[/yellow]╗[yellow]██[/yellow]╗    │
│   [cyan]██[/cyan]╔══[cyan]██[/cyan]╗[red]██[/red]║     [red]██[/red]║[yellow]██[/yellow]║[yellow]██[/yellow]║    │
│   [cyan]██████[/cyan]╔╝[red]██[/red]║     [red]██[/red]║[yellow]██[/yellow]║[yellow]██[/yellow]║    │
│   [cyan]██[/cyan]╔══[cyan]██[/cyan]╗[red]██[/red]║     [red]██[/red]║[yellow]██[/yellow]║[yellow]██[/yellow]║    │
│   [cyan]██████[/cyan]╔╝[red]███████[/red]╗[red]██[/red]║[yellow]███████[/yellow]╗  │
│   [cyan]╚═════[/cyan]╝ [red]╚══════[/red]╝[red]╚═[/red]║[yellow]╚══════[/yellow]╝  │
╰──────────────────────────────────╯[/bold blue]
""", border_style="blue", padding=(1,2)))

        while True:
            menu_panel = Panel(
                Text.from_markup("""
[bold cyan]╭───────────────────────────────╮[/bold cyan]
│                                   │
│   🎬 [bold cyan]1.[/bold cyan] 单视频下载            │
│   📚 [bold cyan]2.[/bold cyan] 批量下载              │
│   ⚙️  [bold cyan]3.[/bold cyan] 设置                 │ 
│   🚪 [bold cyan]4.[/bold cyan] 退出                 │
│                                   │
[bold cyan]╰───────────────────────────────╯[/bold cyan]
                """),
                title="[bold blue]🎯 主菜单[/bold blue]",
                border_style="cyan",
                padding=(1,2)
            )
            console.print(menu_panel)
            
            choice = Prompt.ask(
                "\n[bold cyan]➜[/bold cyan] 请选择操作",
                choices=["1", "2", "3", "4"],
                show_choices=False
            )
            
            if choice == "1":
                self.single_download()
            elif choice == "2":
                console.print("\n[bold cyan]╭──────────── 📚 批量下载 ────────────╮[/bold cyan]")
                file_path = Prompt.ask("[bold cyan]➜[/bold cyan] 输入包含URL的文件路径")
                console.print("[bold cyan]╰────────────────────────────────────╯[/bold cyan]\n")
                self.batch_download_from_file(Path(file_path))
            elif choice == "3":
                console.print("\n[bold cyan]╭──────────── ⚙️ 设置 ────────────╮[/bold cyan]")
                self.show_settings()
                console.print("[bold cyan]╰────────────────────────────────────╯[/bold cyan]\n")
            elif choice == "4":
                console.print(Panel.fit(
                    "[yellow]感谢使用，再见！👋[/yellow]",
                    border_style="yellow",
                    padding=(1,2)
                ))
                break

if __name__ == "__main__":
    try:
        BiliDownloader().run()
    except KeyboardInterrupt:
        console.print("\n[red]程序已中断[/red]")
    except Exception as e:
        console.print(f"[red]致命错误: {str(e)}[/red]")
        console.print(f"[red]致命错误: {str(e)}[/red]")