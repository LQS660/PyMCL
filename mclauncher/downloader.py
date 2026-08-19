# -*- coding: utf-8 -*-
"""下载管理器：多线程、断点友好、sha1 校验、进度回调、失败重试。"""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from urllib3.util.retry import Retry

from . import APP_NAME, APP_VERSION
from . import utils
from .download_status import DownloadTracker, StatusHTTPAdapter
from .mirrors import expand_download_urls


class DownloadError(Exception):
    pass


def _looks_complete(path) -> bool:
    """无 sha1/size 时：拒绝空文件和 HTML 错误页，jar/zip 必须是 PK。"""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return False
    if size < 16:
        return False
    try:
        with open(p, "rb") as f:
            head = f.read(32)
    except OSError:
        return False
    if p.suffix.lower() in (".jar", ".zip"):
        return head.startswith(b"PK")
    stripped = head.lstrip().lower()
    return not stripped.startswith((b"<html", b"<!doctype", b"error"))


def _should_switch_source(err) -> bool:
    """这类错误换下一个镜像，不要在死链上反复重试。"""
    msg = str(err)
    if "用户取消" in msg:
        return True
    return bool(re.search(r"HTTP (403|404|408|409|410|429|5\d{2})\b", msg))


# 全局“目标文件 -> 锁”注册表：任何 DownloadManager 下载同一文件时串行化，
# 防止并发任务写同一个 .part 文件互相打架（WinError 32 / 空壳文件）。
_PATH_LOCKS = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(dest) -> threading.Lock:
    key = os.path.abspath(str(dest))
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[key] = lock
        return lock


def _safe_unlink(path):
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass  # 被杀毒软件/其它进程占用时忽略，避免掩盖真正的错误


def _safe_close(f):
    try:
        f.close()
    except OSError:
        pass


class DownloadManager:
    def __init__(self, threads: int = 8, on_progress=None, cancel=None, tracker=None):
        """
        threads:     并发下载线程数
        on_progress: 回调 (message, done, total)，从工作线程调用
        cancel:      回调 () -> bool，返回 True 时中止下载
        tracker:     DownloadTracker，供 GUI/CLI 读取速度与握手状态
        """
        self.threads = max(1, int(threads))
        self.on_progress = on_progress
        self.cancel = cancel or (lambda: False)
        self.tracker = tracker or DownloadTracker()
        self._lock = threading.Lock()
        self._done = 0
        self._last_notify = 0.0

        self.session = requests.Session()
        from .net import apply_direct_to_session
        apply_direct_to_session(self.session)
        self.session.headers.update({
            "User-Agent": f"{APP_NAME}/{APP_VERSION} (python; +minecraft launcher)",
            # 禁用 gzip，保证 Content-Length 与实际写入字节一致
            "Accept-Encoding": "identity",
        })
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = StatusHTTPAdapter(
            self.tracker, max_retries=retry, pool_connections=16, pool_maxsize=16,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _notify_progress(self, force=False):
        if not self.on_progress:
            return
        now = time.monotonic()
        if not force and now - self._last_notify < 0.15:
            return
        self._last_notify = now
        snap = self.tracker.snapshot()
        done = snap.bytes_done if snap.bytes_total else snap.files_done
        total = snap.bytes_total if snap.bytes_total else snap.files_total
        msg = snap.status_line or ""
        if snap.meta_line:
            msg = f"{msg}  |  {snap.meta_line}" if msg else snap.meta_line
        try:
            self.on_progress(msg, done, total)
        except Exception as e:
            if e.__class__.__name__ == "TaskCancelled":
                raise
            pass

    # ------------------------------------------------------------ HTTP 基础

    def _extra_headers(self, url):
        """官方 CurseForge API 下载需要带 x-api-key。"""
        headers = {}
        if url and ("api.curseforge.com" in url or "/curseforge/v1/" in url):
            from .config import CONFIG
            key = CONFIG.get("curseforge_api_key")
            if key:
                headers["x-api-key"] = key
        return headers

    def _iter_urls(self, url, urls=None):
        raw = []
        if url:
            raw.append(url)
        if urls:
            if isinstance(urls, (list, tuple)):
                raw.extend(urls)
            else:
                raw.append(urls)
        out, seen = [], set()
        for u in raw:
            for e in expand_download_urls(u):
                if e and e not in seen:
                    seen.add(e)
                    out.append(e)
        return out

    def _get_urls(self, url, expand=True):
        if expand:
            return self._iter_urls(url)
        return [str(url)] if url else []

    def fetch_json(self, url, timeout=(4, 15), expand=True, **kwargs):
        last_err = None
        for u in self._get_urls(url, expand=expand):
            try:
                resp = self.session.get(u, timeout=timeout, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_err = e
                if u == url or "github" in (u or ""):
                    utils.log.warning("fetch_json 失败 %s: %s", u, e)
        if last_err:
            raise last_err
        raise DownloadError(f"fetch_json 失败: {url}")

    def fetch_text(self, url, timeout=(4, 15), expand=True, **kwargs):
        last_err = None
        for u in self._get_urls(url, expand=expand):
            try:
                resp = self.session.get(u, timeout=timeout, **kwargs)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                last_err = e
        if last_err:
            raise last_err
        raise DownloadError(f"fetch_text 失败: {url}")

    # ------------------------------------------------------------ 单文件下载

    def download(self, url, dest, sha1=None, size=None, force=False, timeout=300, sha512=None, urls=None) -> Path:
        """
        下载单个文件到 dest。url 可以是单个地址，urls 为额外候选（会自动展开 GitHub 镜像）。
        403/404 会立刻换源，不再对同一死链重试。
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        key = str(dest)
        candidates = self._iter_urls(url, urls)
        if not candidates:
            raise DownloadError(f"没有可下载的地址: {dest.name}")
        self.tracker.start_file(key, dest.name, candidates[0], size)
        self._notify_progress(force=True)
        try:
            with _path_lock(dest):
                result = self._download_locked(candidates, dest, sha1, size, force, timeout, sha512, key)
            self.tracker.finish_file(key, size or (result.stat().st_size if result.is_file() else None))
            self._notify_progress(force=True)
            return result
        except Exception as e:
            self.tracker.fail_file(key, e)
            self._notify_progress(force=True)
            raise

    def _download_locked(self, urls, dest, sha1, size, force, timeout, sha512, key) -> Path:
        if not force:
            if sha1 or size is not None:
                if utils.file_matches(dest, sha1, size):
                    if not sha512 or utils.sha512_file(dest) == sha512.lower():
                        return dest
            elif dest.is_file() and _looks_complete(dest):
                return dest

        part = dest.with_name(dest.name + ".part")
        last_err = None
        for url in urls:
            if self.cancel():
                raise DownloadError("用户取消")
            fatal = False
            for attempt in range(2):
                if self.cancel():
                    raise DownloadError("用户取消")
                try:
                    self.tracker.reset_connect()
                    headers = self._extra_headers(url)
                    with self.session.get(url, stream=True, timeout=timeout, headers=headers) as resp:
                        if not self.tracker.did_connect():
                            self.tracker.reuse()
                        code = resp.status_code
                        if code in (403, 404, 408, 409, 410, 429) or code >= 500:
                            raise DownloadError(f"HTTP {code}: {url}")
                        resp.raise_for_status()
                        expected = int(resp.headers.get("Content-Length") or size or 0)
                        self.tracker.http_ok(resp.status_code, expected)
                        self._notify_progress(force=True)
                        with open(part, "wb") as f:
                            got = 0
                            for chunk in resp.iter_content(chunk_size=64 * 1024):
                                if self.cancel():
                                    _safe_close(f)
                                    _safe_unlink(part)
                                    raise DownloadError("用户取消")
                                if chunk:
                                    f.write(chunk)
                                    got += len(chunk)
                                    self.tracker.transfer(key, got, expected)
                                    self._notify_progress()
                        if expected and got != expected:
                            raise DownloadError(f"下载不完整 {url} ({got}/{expected})")
                    self.tracker.verify(dest.name)
                    self._notify_progress(force=True)
                    if sha1 or size is not None:
                        if not utils.file_matches(part, sha1, size):
                            raise DownloadError(f"校验失败: {url} (期望 sha1={sha1}, size={size})")
                    elif not _looks_complete(part):
                        raise DownloadError(f"下载内容无效: {url}")
                    if sha512 and utils.sha512_file(part) != sha512.lower():
                        raise DownloadError(f"sha512 校验失败: {url}")
                    os.replace(part, dest)
                    return dest
                except DownloadError as e:
                    last_err = e
                    _safe_unlink(part)
                    msg = str(e)
                    if "用户取消" in msg or _should_switch_source(e):
                        fatal = True
                        break
                    time.sleep(1.0 * (attempt + 1))
                except Exception as e:
                    last_err = e
                    _safe_unlink(part)
                    time.sleep(1.0 * (attempt + 1))
            if fatal and last_err and "用户取消" in str(last_err):
                raise last_err
            if last_err:
                utils.log.warning("下载源失败，换下一个: %s", last_err)
        raise DownloadError(f"下载失败 {dest.name}: {last_err}")

    # ------------------------------------------------------------ 批量下载

    def download_all(self, tasks, message="下载中"):
        """
        tasks: [(url, dest, sha1, size), ...]，dest 为 Path 或 str。
        url 可以是单个地址或候选列表。同一 dest 会合并镜像，避免镜像失败把已成功的官方下载判失败。
        全部完成后返回；任何失败抛出 DownloadError（含失败列表）。
        """
        merged = {}
        order = []
        for raw in tasks:
            url, dest, sha1, size = raw[0], raw[1], raw[2], raw[3]
            dest = Path(dest)
            key = os.path.abspath(str(dest))
            urls = list(url) if isinstance(url, (list, tuple)) else [url]
            if key not in merged:
                merged[key] = [urls, dest, sha1, size]
                order.append(key)
            else:
                seen = set(merged[key][0])
                for u in urls:
                    if u and u not in seen:
                        merged[key][0].append(u)
                        seen.add(u)
                if merged[key][2] is None:
                    merged[key][2] = sha1
                if merged[key][3] is None:
                    merged[key][3] = size
        tasks = [tuple(merged[k]) for k in order]
        total = len(tasks)
        errors = []
        self._done = 0
        total_bytes = sum(int(sz) for *_, sz in tasks if sz)
        self.tracker.begin_batch(message, total, total_bytes)
        self._notify_progress(force=True)
        try:
            with ThreadPoolExecutor(max_workers=self.threads) as pool:
                futures = {pool.submit(self._task_download, t): t for t in tasks}
                for fut in as_completed(futures):
                    url, dest, sha1, size = futures[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        errors.append(f"{dest.name}: {e}")
                    with self._lock:
                        self._done += 1
                    self._notify_progress(force=True)
            if errors:
                self.tracker.end_batch(ok=False, message=f"{message}失败 {len(errors)}/{total}")
                raise DownloadError(f"{message}失败（{len(errors)}/{total} 个文件）: {'; '.join(errors[:8])}")
            self.tracker.end_batch(ok=True, message=f"{message}完成")
            self._notify_progress(force=True)
            return True
        except DownloadError:
            raise
        except Exception:
            self.tracker.end_batch(ok=False)
            raise

    def _task_download(self, task):
        url, dest, sha1, size = task
        if isinstance(url, (list, tuple)):
            first = url[0] if url else None
            return self.download(first, dest, sha1=sha1, size=size, urls=url)
        return self.download(url, dest, sha1=sha1, size=size)

    # ------------------------------------------------------------ 解压

    @staticmethod
    def extract_zip(zip_path, dest):
        utils.ensure_dir(dest)
        utils.safe_extract_zip(zip_path, dest)

    @staticmethod
    def extract_targz(path, dest):
        utils.ensure_dir(dest)
        utils.safe_extract_targz(path, dest)

    @staticmethod
    def extract_archive(path, dest):
        p = Path(path)
        name = p.name.lower()
        if name.endswith(".zip") or name.endswith(".jar"):
            DownloadManager.extract_zip(p, dest)
        elif name.endswith((".tar.gz", ".tgz")):
            DownloadManager.extract_targz(p, dest)
        else:
            raise DownloadError(f"不支持的压缩格式: {p.name}")

    @staticmethod
    def extract_jar_natives(jar_path, dest, exclude=None):
        """把 natives jar 解压到目录，支持 extract.exclude 规则。"""
        import zipfile

        dest = utils.ensure_dir(dest)
        exclude = exclude or []
        with zipfile.ZipFile(jar_path) as zf:
            for info in zf.infolist():
                name = info.filename
                if info.is_dir():
                    continue
                if any(name.startswith(prefix) for prefix in exclude):
                    continue
                target = (dest / name).resolve()
                if not str(target).startswith(str(dest.resolve()) + os.sep):
                    raise DownloadError(f"压缩包包含非法路径: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    while True:
                        buf = src.read(256 * 1024)
                        if not buf:
                            break
                        out.write(buf)
