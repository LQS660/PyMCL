# -*- coding: utf-8 -*-
"""Qt-free BackendAPI，行为对齐 app/backend.py。"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from mclauncher import utils
from mclauncher.auth import AccountManager, MicrosoftAuthenticator
from mclauncher.catalog import CBC_CF_ID, CBC_CF_SLUG, CDC_CF_ID, CDC_CF_SLUG, POPULAR_MODPACKS, POPULAR_MODS
from mclauncher.config import CONFIG
from mclauncher.downloader import DownloadManager
from mclauncher.instances import Instance, InstanceError, list_instances, JAVA_AUTO
from mclauncher.installer import Installer, InstallError
from mclauncher import java as java_mod
from mclauncher import manifest as manifest_mod
from mclauncher import modpack as modpack_mod
from mclauncher import mods as mods_mod
from mclauncher.crash import GameCrashError, analyze_launch, export_report, open_path
from mclauncher.i18n import tr
from mclauncher.ai.result import StopReason
from mclauncher.launcher import LaunchError, build_launch_command, GameProcess
from mclauncher import terracotta as terracotta_mod

_tls = threading.local()

# 侧栏编排的两个键在两套前端之间往返，这里只做类型清洗（字符串列表 / 两栏成员
# 表），键名是否认识交给读它的那一端判断——桥不该知道有哪些页面。
_NAV_SECTIONS = ("download", "more")


def _clamp_int(value, lo: int, hi: int, fallback: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return fallback


def _clamp_opacity(value) -> int:
    """侧栏/标题栏不透明度夹到 30–100（与 app/backend.py 同一档）。"""
    return _clamp_int(value, 30, 100, 100)


_WINDOW_ASPECTS = ("4:3", "16:9", "free")


def _window_aspect(value) -> str:
    key = str(value or "").strip()
    return key if key in _WINDOW_ASPECTS else "4:3"


def _nav_keys(raw) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in raw if isinstance(raw, (list, tuple)) else ():
        key = str(item).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _nav_members(raw) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    picked = {sec: _nav_keys(raw.get(sec)) for sec in _NAV_SECTIONS}
    return picked if any(picked.values()) else {}


def _nav_groups(raw) -> list[dict]:
    """分组排法的分组表：[{title, keys}]。空标题的组丢掉。"""
    if not isinstance(raw, list):
        return []
    out = []
    for group in raw:
        if not isinstance(group, dict):
            continue
        title = str(group.get("title") or "").strip()
        if title:
            out.append({"title": title, "keys": _nav_keys(group.get("keys"))})
    return out


class TaskCancelled(Exception):
    """用户取消任务时由 progress 回调抛出。"""


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: list = []

    def emit(self, event: str, data: dict):
        payload = {"event": event, "data": data}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def subscribe(self):
        import queue
        q = queue.Queue(maxsize=800)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


class BackendWorker(threading.Thread):
    def __init__(self, task_id: str, target, args=(), kwargs=None, emit=None):
        super().__init__(daemon=True, name=task_id)
        self.task_id = task_id
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self._cancelled = False
        self._emit = emit or (lambda *_a, **_k: None)

    def cancel(self):
        self._cancelled = True

    def _progress(self, current, total, message=""):
        if self._cancelled:
            raise TaskCancelled()
        self._emit("progress", {
            "task_id": self.task_id,
            "current": int(current or 0),
            "total": int(total or 0),
            "message": str(message or ""),
        })

    def _log(self, text):
        self._emit("log", {"task_id": self.task_id, "text": str(text)})

    def login_code(self, code, uri):
        self._emit("login_code", {"code": str(code), "uri": str(uri)})

    def login_status(self, text):
        self._emit("login_status", {"text": str(text)})

    def run(self):
        _tls.worker = self
        try:
            result = self._target(self._progress, self._log, *self._args, **self._kwargs)
            msg = result if isinstance(result, str) and result else tr("任务完成")
            self._emit("finished", {"task_id": self.task_id, "success": True, "message": msg})
        except TaskCancelled:
            # 协议值：WPF / WinUI 按 `ev.Message != "已取消"` 原文比对，翻了就把取消当失败弹
            self._emit("finished", {"task_id": self.task_id, "success": False, "message": "已取消"})  # i18n:ignore
        except GameCrashError as exc:
            self._log(f"[错误] {exc}")
            payload = dict(exc.report or {})
            payload["task_id"] = self.task_id
            self._emit("crash", payload)
            self._emit("finished", {
                "task_id": self.task_id, "success": False, "message": str(exc), "crash": True,
            })
        except Exception as exc:  # noqa: BLE001
            self._log(f"[错误] {exc}")
            self._emit("finished", {"task_id": self.task_id, "success": False, "message": str(exc)})
        finally:
            _tls.worker = None


_PERM_MODES = {
    "default", "plan", "edit", "acceptEdits", "auto", "dontAsk", "autoEdit",
    "yolo", "bypassPermissions", "build", "custom",
    "standard", "full",
}  # 与 app/backend.py 的 _PERM_MODES 保持同一份；旧值放行，交给 normalize 兜底


def _stop_note(result) -> str:
    """把「为什么停」拼成一句可以入库的提示，别再让回合静默结束。

    文案逐条照抄 app/pages/ai_page.py 的 _stop_note——两端共用一份聊天记录，
    同一个 stop_reason 在两边必须长一个样。
    """
    reason = getattr(result, "stop_reason", None)
    if reason is None or reason == StopReason.COMPLETED:
        return ""
    detail = (getattr(result, "detail", "") or "").strip()
    notes = {
        StopReason.NO_TOOL_CALL: tr("它没有真的开始执行：模型只回了文字，没有调用任何工具。"),
        StopReason.MAX_ROUNDS: tr("步骤太多，先停在这里。你可以让我继续。"),
        StopReason.PENDING_TASK: tr("下载/安装还在后台跑，可以在「下载任务」里看进度。"),
        StopReason.STREAM_FAILED: tr("接口这轮没有返回内容，已停止。"),
        StopReason.EMPTY_RESPONSE: tr("接口返回了空回复。"),
    }
    note = notes.get(reason)
    if not note:
        return ""
    if detail and detail not in note:
        note += tr("（") + detail + tr("）")
    return tr("（提示：") + note + tr("）")


class BackendAPI:
    """后端门面。行为对齐 app.backend.BackendAPI。"""

    def __init__(self, bus: EventBus):
        self._bus = bus
        self._counter = itertools.count(1)
        self._workers: dict[str, BackendWorker] = {}
        self._titles: dict[str, str] = {}
        self._lock = threading.Lock()
        self.accounts = AccountManager()
        self._game_proc = None
        self._game_lock = threading.Lock()
        self._launch_task_id = None
        self._pack_cache: list[dict] = []
        self._mod_cache: list[dict] = []
        self._crashes: dict[str, dict] = {}
        self._task_results: dict[str, tuple] = {}
        self._ai_lock = threading.Lock()
        self._ai_cancel = False
        self._ai_http = None
        self._ai_confirm_ev = threading.Event()
        self._ai_confirm_ok = False
        self._ai_confirm_ctx = None     # (tool_name, args)：正在等回答的那张确认卡
        self._ai_ask_ev = threading.Event()
        self._ai_ask_result = None
        self._ai_pending_card: dict | None = None   # 正在等回答的确认 / 选择卡（断线对账用）
        self._ai_busy = False
        self._ai_steer: list[str] = []   # 跑动中插话（ai_steer），下一轮模型请求前取走
        self._ui_launch = {}
        # get_instances 的 2.5s TTL 缓存（对齐 app/backend.py）：每次 ui_changed 前端都会
        # 重读一遍实例表，桥这边以前每次都全量扫盘 + 逐实例 Java 扫描。数据一变
        # （finished / ui_changed）就失效，TTL 只合并「没人改数据」时的重复扫描。
        self._inst_cache: list[dict] | None = None
        self._inst_cache_at: float = 0.0
        self._ensure_default_instance()

    def invalidate_instances(self):
        """清掉实例表缓存（对齐 app/backend.py）。"""
        self._inst_cache = None

    def _emit(self, event: str, data: dict):
        if event in ("ui_changed", "finished", "instance_changed"):
            self._inst_cache = None
        if event == "crash":
            tid = (data or {}).get("task_id")
            if tid:
                self._crashes[tid] = data or {}
                if len(self._crashes) > 40:
                    extra = list(self._crashes)[:-20]
                    for k in extra:
                        self._crashes.pop(k, None)
            self._bus.emit("crash", data)
            return
        if event == "finished":
            tid = data.get("task_id")
            self._task_results[tid] = (bool(data.get("success")), str(data.get("message") or ""))
            if len(self._task_results) > 80:
                extra = list(self._task_results)[:-40]
                for k in extra:
                    self._task_results.pop(k, None)
            with self._lock:
                self._workers.pop(tid, None)
                count = len(self._workers)
            self._bus.emit("finished", data)
            self._bus.emit("task_count_changed", {"count": count})
            if data.get("success"):
                self._bus.emit("ui_changed", {})
            return
        self._bus.emit(event, data)

    def _ensure_default_instance(self):
        names = list_instances()
        if names:
            return
        name = CONFIG.get("default_instance", "default") or "default"
        try:
            Instance(name).create()
        except InstanceError:
            pass

    def start_task(self, title: str, fn, *args, **kwargs) -> str:
        task_id = f"task-{next(self._counter)}"
        worker = BackendWorker(task_id, fn, args, kwargs, self._emit)
        with self._lock:
            self._workers[task_id] = worker
            self._titles[task_id] = title
            count = len(self._workers)
        worker.start()
        self._emit("task_added", {"task_id": task_id, "title": title})
        self._emit("task_count_changed", {"count": count})
        return task_id

    def cancel_task(self, task_id: str):
        with self._lock:
            worker = self._workers.get(task_id)
        if worker:
            worker.cancel()
        if task_id != self._launch_task_id:
            return
        with self._game_lock:
            proc = self._game_proc
        if proc:
            try:
                proc.kill()
            except Exception:
                pass

    def task_title(self, task_id: str) -> str:
        return self._titles.get(task_id, task_id)

    def shutdown(self, timeout_ms: int = 800) -> dict:
        """关窗前收拢后台任务（对齐 app.backend.BackendAPI.shutdown）。

        前端退出时直接杀桥进程，正在跑的下载会在半截被砍、临时文件留在磁盘上；
        先调这一下，让任务走 TaskCancelled 的正常收尾。预算只给 800ms——关窗是
        用户动作，等不到就放手。启动游戏那个 worker 不动：它阻塞在 proc.wait()
        上，「关掉启动器但游戏继续跑」是既定行为。返回还没收完的任务 id，
        前端可以据此决定是再等一下还是直接杀。
        """
        import time as _time
        deadline = _time.monotonic() + max(0, int(timeout_ms)) / 1000.0
        with self._lock:
            pending = [(tid, w) for tid, w in self._workers.items() if tid != self._launch_task_id]
        for _tid, worker in pending:
            worker.cancel()
        for _tid, worker in pending:
            remain = deadline - _time.monotonic()
            if remain <= 0:
                break
            worker.join(remain)
        try:
            terracotta_mod.stop()
        except Exception:  # noqa: BLE001
            pass
        return {"pending": [tid for tid, w in pending if w.is_alive()]}

    def get_crash(self, task_id: str = "") -> dict:
        if task_id and task_id in self._crashes:
            return self._crashes[task_id]
        if self._crashes:
            return self._crashes[next(reversed(self._crashes))]
        return {}

    def export_crash_report(self, task_id: str = "", dest: str = "") -> str:
        report = self.get_crash(task_id)
        if not report:
            raise LaunchError(tr("没有可导出的错误报告"))
        return export_report(report, dest or None)

    def open_crash_file(self, path: str = "", task_id: str = "") -> str:
        target = path or (self.get_crash(task_id).get("direct_file") or "")
        if not target:
            raise LaunchError(tr("没有可打开的日志文件"))
        if not open_path(target):
            raise LaunchError(tr("无法打开: {0}").format(target))
        return target

    def _dm(self, progress, log) -> DownloadManager:
        worker = getattr(_tls, "worker", None)
        last_key = [""]

        def on_progress(message, done, total):
            text = message or ""
            progress(done or 0, total or 0, text)
            if "  |  " in text:
                key = text.split("  |  ", 1)[0].strip(" ·")
                if key and key != last_key[0]:
                    last_key[0] = key
                    log(text)
                return
            stripped = text.strip()
            if stripped and stripped != last_key[0]:
                last_key[0] = stripped
                log(stripped)

        def cancelled():
            return bool(getattr(worker, "_cancelled", False))

        return DownloadManager(
            threads=CONFIG.get("download_threads", 8),
            on_progress=on_progress,
            cancel=cancelled,
        )

    def _instance(self, name=None) -> Instance:
        name = name or CONFIG.get("default_instance", "default")
        inst = Instance(name)
        if not inst.path.is_dir():
            inst.create()
        else:
            inst.ensure_standard_dirs()
        return inst

    def _lookup_pack(self, name: str, source: str) -> dict:
        q = (name or "").lower().strip()
        for hit in self._pack_cache:
            name_l = (hit.get("name") or "").lower()
            slug_l = (hit.get("slug") or "").lower()
            id_l = str(hit.get("id") or "").lower()
            if q and q in (name_l, slug_l, id_l):
                return hit
        src = "curseforge" if source.lower().startswith("curse") else "modrinth"
        for title, pack_src, key, slug in POPULAR_MODPACKS:
            if title.lower() == q or str(key).lower() == q:
                return {
                    "name": title,
                    "source": pack_src,
                    "id": key if pack_src == "curseforge" else None,
                    "slug": slug if pack_src == "curseforge" else key,
                }
        return {"name": name, "source": src, "slug": name}

    def _lookup_mod(self, name: str, source: str) -> dict:
        q = (name or "").lower().strip()
        for hit in self._mod_cache:
            name_l = (hit.get("name") or "").lower()
            slug_l = (hit.get("slug") or "").lower()
            id_l = str(hit.get("id") or "").lower()
            if q and q in (name_l, slug_l, id_l):
                return hit
        for title, mod_src, key, *_rest in POPULAR_MODS:
            if title.lower() == q or str(key).lower() == q:
                return {
                    "name": title,
                    "source": mod_src,
                    "id": key if mod_src == "curseforge" else None,
                    "slug": key if mod_src != "curseforge" else None,
                }
        src = "curseforge" if source.lower().startswith("curse") else "modrinth"
        return {"name": name, "source": src, "slug": name}

    def install_game(self, version: str, loader: str = "无", loader_version: str = "",  # i18n:ignore 协议值：前端传「无」表示不装加载器
                     instance: str = "", extra: dict | None = None) -> str:
        inst = instance or CONFIG.get("default_instance", "default")
        extra = extra or {}
        bits = [version]
        if loader and loader not in ("", "无"):  # i18n:ignore 协议值
            bits.append(loader)
        if extra.get("optifine"):
            bits.append("OptiFine")
        if extra.get("liteloader"):
            bits.append("LiteLoader")
        title = "安装游戏 " + " + ".join(bits)  # i18n:ignore 任务标题按原文拼，见 is_download_title
        return self.start_task(title, self._install_game_impl, version, loader, loader_version, inst, extra)

    def install_modpack(self, name: str, source: str = "Modrinth", extra: dict | None = None) -> str:
        return self.start_task(f"安装整合包 {Path(name).name}", self._install_modpack_impl,
                               name, source, extra or {})

    def install_mod(self, name: str, instance: str = "default", extra: dict | None = None) -> str:
        return self.start_task(f"安装模组 {Path(str(name)).name}", self._install_mod_impl,
                               name, instance, extra or {})

    def install_shader(self, name: str, instance: str = "default", extra: dict | None = None) -> str:
        return self.start_task(f"安装光影 {Path(str(name)).name}", self._install_content_impl,
                               "shader", name, instance, extra or {})

    def install_resourcepack(self, name: str, instance: str = "default", extra: dict | None = None) -> str:
        return self.start_task(f"安装资源包 {Path(str(name)).name}", self._install_content_impl,
                               "resourcepack", name, instance, extra or {})

    def install_datapack(self, name: str, instance: str = "default", extra: dict | None = None) -> str:
        return self.start_task(f"安装数据包 {Path(str(name)).name}", self._install_content_impl,
                               "datapack", name, instance, extra or {})

    def install_world(self, name: str, instance: str = "default", extra: dict | None = None) -> str:
        return self.start_task(f"安装世界 {Path(str(name)).name}", self._install_world_impl,
                               name, instance, extra or {})

    def list_catalog_files(self, extra: dict | None = None) -> list[dict]:
        from mclauncher.catalog_files import list_project_files
        return list_project_files(DownloadManager(threads=2), extra or {})

    def list_loader_versions(self, mc_version: str, loader: str) -> list[dict]:
        from mclauncher.loader_meta import list_loader_versions
        return list_loader_versions(DownloadManager(threads=2), mc_version, loader)

    def search_worlds(self, query: str, source: str = "CurseForge", extra: dict | None = None) -> list[dict]:
        from mclauncher import worlds as worlds_mod
        extra = dict(extra or {})
        extra.setdefault("source", source)
        return worlds_mod.search_worlds(DownloadManager(threads=2), query, extra)

    def rename_version(self, instance: str, version: str, new_id: str) -> str:
        from mclauncher import version_ops as vops
        return vops.rename_version(self._instance(instance), version, new_id)

    def copy_version(self, instance: str, version: str, new_id: str) -> str:
        from mclauncher import version_ops as vops
        return vops.copy_version(self._instance(instance), version, new_id)

    def hide_version(self, instance: str, version: str, hidden: bool = True) -> dict:
        from mclauncher import version_ops as vops
        return vops.set_hidden(self._instance(instance), version, hidden)

    def open_version_folder(self, instance: str, version: str = "", which: str = "root") -> str:
        from mclauncher import version_ops as vops
        return vops.open_folder(self._instance(instance), version, which)

    def export_launch_script(self, instance: str, version: str, dest: str = "") -> str:
        return self.start_task(f"导出启动脚本 {version}", self._export_bat_impl, instance, version, dest)

    def create_desktop_shortcut(self, instance: str, version: str, username: str = "",
                                account: str = "", name: str = "") -> str:
        from mclauncher import shortcut
        return shortcut.create_launch_shortcut(instance, version, username, account, name)

    def backup_save(self, instance: str, name: str, version: str = "") -> str:
        return self.start_task(f"备份存档 {name}", self._backup_save_impl, instance, name, version)

    def _backup_save_impl(self, progress, log, instance, name, version):
        from mclauncher import saves as saves_mod
        info = saves_mod.backup_save(
            self._instance(instance), name, version,
            on_progress=lambda text, cur, total: progress(cur, total, text))
        log(f"备份完成: {info['path']}")
        self._emit("ui_changed", {})
        return tr("已备份到 {0}").format(info['name'])

    def list_save_backups(self, instance: str, name: str = "", version: str = "") -> list[dict]:
        from mclauncher import saves as saves_mod
        return saves_mod.list_backups(self._instance(instance), name, version)

    def restore_save_backup(self, instance: str, backup_name: str, version: str = "",
                            overwrite: bool = False) -> dict:
        from mclauncher import saves as saves_mod
        out = saves_mod.restore_backup(
            self._instance(instance), backup_name, version, overwrite=overwrite)
        self._emit("ui_changed", {})
        return out

    def delete_save_backup(self, instance: str, backup_name: str, version: str = ""):
        from mclauncher import saves as saves_mod
        saves_mod.delete_backup(self._instance(instance), backup_name, version)
        self._emit("ui_changed", {})

    def export_save(self, instance: str, name: str, dest: str, version: str = "") -> str:
        from mclauncher import saves as saves_mod
        return saves_mod.export_save(self._instance(instance), name, dest, version)

    def list_saves(self, instance: str, version: str = "") -> list[dict]:
        from mclauncher import saves as saves_mod
        return saves_mod.list_saves(self._instance(instance), version)

    def delete_save(self, instance: str, name: str, version: str = ""):
        from mclauncher import saves as saves_mod
        saves_mod.delete_save(self._instance(instance), name, version)

    def open_save(self, instance: str, name: str, version: str = "") -> str:
        from mclauncher import saves as saves_mod
        return saves_mod.open_save(self._instance(instance), name, version)

    def install_datapack_into_save(self, instance: str, filename: str, save_name: str,
                                   version: str = "") -> str:
        from mclauncher import saves as saves_mod
        return saves_mod.install_datapack_into_save(self._instance(instance), filename, save_name, version)

    def list_media(self, instance: str, kind: str, version: str = "") -> list[dict]:
        from mclauncher import saves as saves_mod
        return saves_mod.list_media(self._instance(instance), kind, version)

    def open_media(self, path: str) -> bool:
        return bool(open_path(path))

    def set_game_dir(self, path: str):
        p = Path(path).expanduser()
        target = p if p.is_absolute() else (utils.ROOT / path)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".pymcl-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise InstanceError(tr("游戏目录不可写: {0}").format(target) + f"\n{exc}") from exc
        CONFIG.set("instances_dir", str(p) if p.is_absolute() else path)
        CONFIG.save()
        self._emit("ui_changed", {})
        return str(CONFIG.instances_dir)

    def delete_modpack(self, instance: str, filename: str = "", purge_instance: bool = False):
        """默认只清整合包标记；删整个实例必须显式要求。"""
        inst = self._instance(instance)
        meta = inst.meta() or {}
        pack = meta.get("modpack")
        if not isinstance(pack, dict) or not pack.get("name"):
            raise InstanceError(tr("该实例没有已安装整合包"))
        if purge_instance:
            inst.delete()
        else:
            inst.set_meta("modpack", None)
        self._emit("ui_changed", {})

    def list_global_mods(self) -> list[dict]:
        from mclauncher import global_mods as gm
        return gm.list_entries()

    def set_global_mod_enabled(self, filename: str, enabled: bool) -> str:
        from mclauncher import global_mods as gm
        return gm.set_enabled(filename, enabled)

    def start_nide8_login(self, server_id: str, username: str, password: str) -> str:
        return self.start_task("统一通行证登录", self._nide8_login_impl, server_id, username, password)

    def catalog_favorites(self) -> list:
        return list(CONFIG.get("catalog_favorites") or [])

    def toggle_favorite(self, item: dict) -> list:
        rows = list(CONFIG.get("catalog_favorites") or [])
        key = (str(item.get("source") or ""), str(item.get("slug") or item.get("id") or item.get("name") or ""))
        kept, found = [], False
        for r in rows:
            rk = (str(r.get("source") or ""), str(r.get("slug") or r.get("id") or r.get("name") or ""))
            if rk == key:
                found = True
                continue
            kept.append(r)
        if not found:
            kept.append({"name": item.get("name"), "source": item.get("source"),
                         "slug": item.get("slug"), "id": item.get("id")})
        CONFIG.set("catalog_favorites", kept)
        CONFIG.save()
        return kept

    def download_java(self, major: str, vendor: str = "adoptium") -> str:
        vendor = (vendor or "adoptium").strip() or "adoptium"
        if vendor != "adoptium":
            try:
                return self.install_java(int(major), vendor=vendor)
            except Exception:
                pass
        return self.start_task(f"下载 Java {major}", self._download_java_impl, major)

    def terracotta_player(self) -> str:
        acc = self.accounts.get_active()
        if acc and acc.get("name"):
            return str(acc["name"])
        return "Player"

    def terracotta_snapshot(self) -> dict:
        game_on = bool(self._game_proc and getattr(self._game_proc, "poll", lambda: 0)() is None)
        return terracotta_mod.snapshot(self.terracotta_player(), game_running=game_on)

    def terracotta_prepare(self) -> str:
        return self.start_task("准备陶瓦联机", self._terracotta_prepare_impl)

    def terracotta_host(self):
        terracotta_mod.set_scanning(self.terracotta_player())

    def terracotta_join(self, room: str):
        terracotta_mod.set_guesting(room, self.terracotta_player())

    def terracotta_idle(self):
        terracotta_mod.set_waiting()

    def terracotta_allow_firewall(self) -> str:
        return terracotta_mod.allow_firewall()

    def terracotta_open_firewall_settings(self):
        terracotta_mod.open_firewall_settings()

    def terracotta_shutdown(self):
        terracotta_mod.stop()

    def terracotta_enter_world(self):
        info = self.terracotta_snapshot()
        url = str(info.get("url") or "")
        if info.get("state") != "guest-ok" or not url:
            raise terracotta_mod.TerracottaError(tr("还没连上房间。请先输入邀请码加入。"))
        return self._launch_into_server(url, tr("请到游戏「多人游戏」双击「陶瓦联机大厅」。"))

    def terracotta_direct_connect(self, address: str):
        host, port = terracotta_mod.split_join_url(address)
        if not host or host in ("127.0.0.1", "localhost"):
            raise terracotta_mod.TerracottaError(tr("请输入房主的公网地址，例如 1.2.3.4:25565"))
        return self._launch_into_server(f"{host}:{port}", tr("请到游戏「多人游戏」双击「陶瓦联机大厅」。"))

    def _launch_into_server(self, url: str, already_msg: str):
        inst = self._instance()
        terracotta_mod.remember_lobby(url, inst.path)
        info = self.terracotta_snapshot()
        if info.get("game_running"):
            return already_msg
        ids = inst.installed_ids()
        if not ids:
            raise LaunchError(tr("请先到「启动」页安装一个版本。"))
        version = max(ids, key=lambda vid: (inst.versions_dir() / vid).stat().st_mtime)
        host, port = terracotta_mod.split_join_url(url)
        acc = self.accounts.get_active()
        if acc and acc.get("type") == "microsoft":
            account = acc.get("name") or tr("离线模式")
            username = acc.get("name") or "Player"
        else:
            account = tr("离线模式")
            username = (acc or {}).get("name") or self.terracotta_player()
        return self.launch_game(
            instance=inst.name,
            version=version,
            account=account,
            username=username,
            memory_mb=int(CONFIG.get("memory_mb") or 4096),
            width=int(CONFIG.get("width") or 854),
            height=int(CONFIG.get("height") or 480),
            extra_game_args=["--server", host, "--port", str(port)],
        )

    @staticmethod
    def _is_offline_account(account) -> bool:
        """「离线模式」这个哨兵原文和译文都认：eziapp / WinUI 传原文，WPF 传的是 L() 过的译文。"""
        text = str(account or "")
        return not text or text == "离线模式" or text == tr("离线模式")  # i18n:ignore 协议值，原文比对

    def launch_game(self, instance: str, version: str, account: str,
                    username: str, memory_mb: int, width: int, height: int,
                    java: str = JAVA_AUTO, extra_game_args=None,
                    force: bool = False) -> str:
        task_id = self.start_task(
            f"启动游戏 {version}", self._launch_game_impl,
            instance, version, account, username, memory_mb, width, height, java,
            extra_game_args, force,
        )
        self._launch_task_id = task_id
        return task_id

    def build_launch_command(self, instance: str, version: str, account: str,
                              username: str, memory_mb: int, width: int, height: int,
                              java: str = JAVA_AUTO) -> str:
        """生成启动命令文本（不实际启动）。"""
        inst = self._instance(instance)
        if not version:
            raise LaunchError(tr("请先选择版本"))
        if self._is_offline_account(account):
            acc = self.accounts.offline_account(
                username or "Player", skin=CONFIG.get("offline_skin") or "default")
        else:
            acc = self.accounts.get_account(account)
            if not acc:
                raise LaunchError(tr("账号不存在: {0}").format(account))
            acc = self.accounts.ensure_valid(acc)
        props = self.accounts.launch_props(acc)
        from mclauncher import launcher
        from mclauncher import version_settings as _vs
        auth_server = str(_vs.load(inst, version).get("auth_server") or "").strip()
        if auth_server and not props.get("authlib_api"):
            props = dict(props)
            props["authlib_api"] = auth_server
        java_exe = JAVA_AUTO if java in (JAVA_AUTO, "") else java
        cmd, _natives, _vdir, _gdir = launcher.build_launch_command(
            inst, version, props, java_exe, memory_mb=memory_mb,
            width=width, height=height, authlib_api=props.get("authlib_api"))
        return cmd

    def start_microsoft_login(self) -> str:
        return self.start_task("微软登录", self._microsoft_login_impl)

    def uninstall_version(self, spec: str):
        if " / " in spec:
            inst_name, vid = spec.split(" / ", 1)
        else:
            inst_name, vid = CONFIG.get("default_instance", "default"), spec
        Installer(self._instance(inst_name)).uninstall_version(vid.strip())
        self._emit("ui_changed", {})

    def create_instance(self, name: str):
        Instance(name).create()
        self._emit("ui_changed", {})

    def delete_instance(self, name: str):
        Instance(name).delete()
        self._emit("ui_changed", {})

    def rename_instance(self, name: str, new_name: str):
        Instance(name).rename(new_name)
        self._emit("ui_changed", {})

    def open_instance_folder(self, name: str):
        path = self._instance(name).path
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def delete_mod(self, instance: str, filename: str, version: str = ""):
        inst = self._instance(instance)
        folder = self._mods_folder(inst, version)
        mods_mod.delete_mod(inst, filename, mods_dir=folder)
        self._emit("ui_changed", {})

    def disable_mod(self, instance: str, filename: str, version: str = "") -> str:
        inst = self._instance(instance)
        name = mods_mod.set_mod_enabled(inst, filename, False, mods_dir=self._mods_folder(inst, version))
        self._emit("ui_changed", {})
        return name

    def enable_mod(self, instance: str, filename: str, version: str = "") -> str:
        inst = self._instance(instance)
        name = mods_mod.set_mod_enabled(inst, filename, True, mods_dir=self._mods_folder(inst, version))
        self._emit("ui_changed", {})
        return name

    def _mods_folder(self, inst, version: str = ""):
        if version:
            from mclauncher import version_settings as vs
            return vs.mods_dir(inst, version)
        return inst.path / "mods"

    def get_installed_mods(self, instance: str, version: str = "") -> list[str]:
        inst = self._instance(instance)
        return [r["filename"] for r in mods_mod.list_mod_entries_at(self._mods_folder(inst, version)) if r.get("enabled")]

    def get_installed_shaders(self, instance: str) -> list[str]:
        return [p.name for p in mods_mod.list_content_files(self._instance(instance), "shaderpacks")]

    def get_installed_resourcepacks(self, instance: str) -> list[str]:
        return [p.name for p in mods_mod.list_content_files(self._instance(instance), "resourcepacks")]

    def get_installed_datapacks(self, instance: str) -> list[str]:
        return [p.name for p in mods_mod.list_content_files(self._instance(instance), "datapacks")]

    def delete_shader(self, instance: str, filename: str):
        mods_mod.delete_content_file(self._instance(instance), "shaderpacks", filename)
        self._emit("ui_changed", {})

    def delete_resourcepack(self, instance: str, filename: str):
        mods_mod.delete_content_file(self._instance(instance), "resourcepacks", filename)
        self._emit("ui_changed", {})

    def delete_datapack(self, instance: str, filename: str):
        mods_mod.delete_content_file(self._instance(instance), "datapacks", filename)
        self._emit("ui_changed", {})

    def get_setting(self, key: str, default=None):
        settings = self.get_settings()
        return settings.get(key, default)

    def update_settings(self, settings: dict | None = None, **extra):
        self.save_settings(settings, **extra)

    def wait_task(self, task_id: str, timeout: float = 1800, cancelled=None) -> dict:
        import time
        start = time.time()
        while True:
            if task_id in self._task_results:
                ok, msg = self._task_results[task_id]
                return {"ok": ok, "message": msg, "task_id": task_id}
            if cancelled and cancelled():
                self.cancel_task(task_id)
                return {"ok": False, "message": tr("已停止"), "task_id": task_id}
            if time.time() - start > timeout:
                # timeout=True 是结构化的「还在跑」标记，AI agent 不再靠比对文案判断
                return {"ok": False, "message": tr("等待任务超时"), "task_id": task_id,
                        "timeout": True}
            time.sleep(0.3)

    def get_settings(self) -> dict:
        from mclauncher.ai.defaults import DEFAULT_GATEWAY_URL, DEFAULT_MODEL
        from mclauncher.ai.permission import normalize_permission_mode
        from mclauncher.feedback_defaults import DEFAULT_FEEDBACK_URL
        return {
            "share_libraries": bool(CONFIG.get("shared_libraries", False)),
            "share_assets": bool(CONFIG.get("shared_assets", False)),
            "download_threads": int(CONFIG.get("download_threads", 8)),
            "default_memory_mb": int(CONFIG.get("memory_mb", 4096)),
            "default_resolution": [int(CONFIG.get("width", 854)), int(CONFIG.get("height", 480))],
            "ms_client_id": CONFIG.get("microsoft_client_id") or "",
            "curseforge_api_key": CONFIG.get("curseforge_api_key") or "",
            "ai_mode": CONFIG.get("ai_mode") or "public",
            "ai_gateway_url": CONFIG.get("ai_gateway_url") or DEFAULT_GATEWAY_URL or "",
            "ai_base_url": CONFIG.get("ai_base_url") or "",
            "ai_api_key": CONFIG.get("ai_api_key") or "",
            "ai_model": CONFIG.get("ai_model") or DEFAULT_MODEL,
            # AI 权限：词表与 app/backend.py 同一套（W-5）。get_settings 必须归一化——
            # 前端词表不一的历史遗留值（trusted / strict / readonly）在这里统一折回
            # 合法枚举，后端 normalize_permission_mode 认不出时按 confirm_writes 兜底。
            "ai_confirm_writes": bool(CONFIG.get("ai_confirm_writes", True)),
            "ai_permission_mode": normalize_permission_mode(
                CONFIG.get("ai_permission_mode"),
                bool(CONFIG.get("ai_confirm_writes", True))),
            "ai_permission_rules": list(CONFIG.get("ai_permission_rules") or []),
            "ai_permission_dont_ask": bool(CONFIG.get("ai_permission_dont_ask", False)),
            "ai_context_window": max(8192, int(CONFIG.get("ai_context_window")
                                               or 131072)),
            "ai_max_tokens": int(CONFIG.get("ai_max_tokens") or 8192),
            "ai_fallback_model": str(CONFIG.get("ai_fallback_model") or ""),
            "root": str(utils.ROOT),
            "feedback_url": CONFIG.get("feedback_url") or DEFAULT_FEEDBACK_URL or "",
            "feedback_heartbeat": bool(CONFIG.get("feedback_heartbeat", True)),
            "feedback_consent": CONFIG.get("feedback_consent") is True,
            "default_isolation": CONFIG.get("default_isolation") or "none",
            "default_jvm_args": CONFIG.get("default_jvm_args") or "",
            "update_url": CONFIG.get("update_url") or "",
            "download_source": CONFIG.get("download_source") or "auto",
            "community_source": CONFIG.get("community_source") or "auto",
            "use_system_proxy": bool(CONFIG.get("use_system_proxy", True)),
            "launcher_visibility": CONFIG.get("launcher_visibility") or "keep",
            "gc_preset": CONFIG.get("gc_preset") or "auto",
            "download_limit_kbps": int(CONFIG.get("download_limit_kbps") or 0),
            "auto_check_update": bool(CONFIG.get("auto_check_update", True)),
            "custom_homepage": CONFIG.get("custom_homepage") or "",
            "homepage_mode": CONFIG.get("homepage_mode") or "news",
            "window_mode": CONFIG.get("window_mode") or "window",
            "game_dir": str(CONFIG.instances_dir),
            "offline_skin": CONFIG.get("offline_skin") or "default",
            "default_java": CONFIG.get("default_java") or "",
            "default_instance": CONFIG.get("default_instance") or "default",
            "ui_dark": bool(CONFIG.get("ui_dark", False)),
            # 外观 / 壁纸 / 动效 / 首次运行：Qt 门面（app/backend.py get_settings）一直回这些键，
            # 桥这边漏了——WPF 拖图设壁纸后 Wallpaper.ReloadAsync() 读回空串、设置页外观项
            # 重启即丢、首次运行向导永不弹出，而两端都提示「已保存」。与 save_settings 成对补齐。
            "theme_color": CONFIG.get("theme_color") or "#2E9B6B",
            "ui_background": CONFIG.get("ui_background") or "",
            "ui_background_folder": CONFIG.get("ui_background_folder") or "",
            "ui_background_shuffle": bool(CONFIG.get("ui_background_shuffle", False)),
            "ui_background_interval": _clamp_int(
                CONFIG.get("ui_background_interval", 10), 1, 1440, 10),
            "ui_background_history": list(CONFIG.get("ui_background_history") or []),
            "ui_background_blur": _clamp_int(CONFIG.get("ui_background_blur", 0), 0, 40, 0),
            "ui_background_dim": _clamp_int(CONFIG.get("ui_background_dim", 0), 0, 80, 0),
            "ui_sidebar_opacity": _clamp_opacity(CONFIG.get("ui_sidebar_opacity", 100)),
            "ui_window_aspect": _window_aspect(CONFIG.get("ui_window_aspect")),
            "ui_motion": bool(CONFIG.get("ui_motion", True)),
            "ui_fly_animation": bool(CONFIG.get("ui_fly_animation", True)),
            "ui_fly_duration_ms": int(CONFIG.get("ui_fly_duration_ms", 620) or 620),
            "first_run": bool(CONFIG.get("first_run", True)),
            "skip_assets": bool(CONFIG.get("skip_assets", False)),
            "allow_multi_instance": bool(CONFIG.get("allow_multi_instance", False)),
            "show_hidden_versions": bool(CONFIG.get("show_hidden_versions", False)),
            "export_dir": CONFIG.get("export_dir") or "",
            "default_priority": CONFIG.get("default_priority") or "normal",
            "global_mods_dir": CONFIG.get("global_mods_dir") or "",
            "instances_dir": str(CONFIG.get("instances_dir") or ".minecraft"),
            # 侧栏编排：Qt 版一直在写这几个键，之前没暴露给桥，非 Qt 前端只能
            # 画一套写死的侧栏，用户在 Qt 里排好的顺序被静默忽略。
            "ui_nav_order": list(CONFIG.get("ui_nav_order") or []),
            "ui_nav_pinned": list(CONFIG.get("ui_nav_pinned") or []),
            "ui_nav_hidden": list(CONFIG.get("ui_nav_hidden") or []),
            # 排法与分区成员：少了这两个键，前端只能猜出厂排法，用户在 Qt 里
            # 切成「精简」或挪过分区成员，网页版仍按分组画。
            "ui_nav_style": CONFIG.get("ui_nav_style") or "",
            "ui_nav_defaults": CONFIG.get("ui_nav_defaults") or "",
            "ui_nav_groups": _nav_groups(CONFIG.get("ui_nav_groups")),
            "ui_section_members": _nav_members(CONFIG.get("ui_section_members")),
            "ui_sidebar_width": int(CONFIG.get("ui_sidebar_width") or 0),
        }

    def save_settings(self, data: dict | None = None, **extra):
        """两种参数形状都认：{"data": {...}} 与整包平铺。

        JSON-RPC 这一层按形参名分发（bridge/server.py _call_kwargs），前端把整包
        设置直接当 params 发过来时，形参 `data` 一个键也收不到，整调用以
        「缺少必需参数」失败——保存设置在网页版就是点了没反应。
        """
        data = {**(data if isinstance(data, dict) else {}), **extra}
        # 严格的局部更新：只写 `data` 里真正带来的键。前端（eziapp 设置页只提交 11 个键）
        # 提交部分设置时，未提交的键必须原样保留，否则等于静默清空用户配置。
        patch = {}
        if "default_resolution" in data:
            res = data.get("default_resolution") or [854, 480]
            patch["width"] = int(res[0])
            patch["height"] = int(res[1])
        if "share_libraries" in data:
            patch["shared_libraries"] = bool(data.get("share_libraries"))
        if "share_assets" in data:
            patch["shared_assets"] = bool(data.get("share_assets"))
        if "download_threads" in data:
            patch["download_threads"] = int(data.get("download_threads") or 8)
        if "default_memory_mb" in data:
            patch["memory_mb"] = int(data.get("default_memory_mb") or 4096)
        if "ms_client_id" in data:
            patch["microsoft_client_id"] = ((data.get("ms_client_id") or "").strip()
                                            or CONFIG.get("microsoft_client_id"))
        if "curseforge_api_key" in data:
            patch["curseforge_api_key"] = (data.get("curseforge_api_key") or "").strip()
        if "ai_mode" in data:
            patch["ai_mode"] = data.get("ai_mode") or "public"
        # 地址类键各自独立判定，不能挂在 `"ai_mode" in data` 下面：否则前端只要
        # 提交了 ai_mode，它们就会被 data 里不存在的值覆写成空串，
        # 自定义模式随即抛「请在设置里填写自定义 NewAPI 地址」，AI 助手整个不可用。
        if "ai_gateway_url" in data:
            patch["ai_gateway_url"] = (data.get("ai_gateway_url") or "").strip()
        if "ai_base_url" in data:
            patch["ai_base_url"] = (data.get("ai_base_url") or "").strip()
        if "ai_api_key" in data:
            patch["ai_api_key"] = data.get("ai_api_key") or ""
        if "ai_model" in data:
            patch["ai_model"] = (data.get("ai_model") or CONFIG.get("ai_model") or "deepseek-v4-flash")
        # AI 权限三键：之前不在白名单里，WPF 设置页提交了也被静默丢掉。词表校验
        # 与 app/backend.py 相同——认不出的档位不写入，按 confirm_writes 折回，
        # 决不让「只看不动」悄悄变成「每步都问」。
        if "ai_permission_mode" in data:
            mode = str(data.get("ai_permission_mode") or "")
            if mode not in _PERM_MODES:
                confirm = bool(data["ai_confirm_writes"]) if "ai_confirm_writes" in data \
                    else bool(CONFIG.get("ai_confirm_writes", True))
                mode = "default" if confirm else "yolo"
            patch["ai_permission_mode"] = mode
        if "ai_confirm_writes" in data:
            patch["ai_confirm_writes"] = bool(data.get("ai_confirm_writes"))
        if "ai_permission_rules" in data:
            patch["ai_permission_rules"] = list(data.get("ai_permission_rules") or [])
        if "ai_permission_dont_ask" in data:
            patch["ai_permission_dont_ask"] = bool(data.get("ai_permission_dont_ask"))
        if "ai_context_window" in data:
            patch["ai_context_window"] = max(8192, min(
                int(data.get("ai_context_window") or 131072), 2_000_000))
        if "ai_max_tokens" in data:
            patch["ai_max_tokens"] = int(data.get("ai_max_tokens") or 8192)
        if "ai_fallback_model" in data:
            patch["ai_fallback_model"] = str(data.get("ai_fallback_model") or "").strip()
        if "feedback_url" in data:
            patch["feedback_url"] = (data.get("feedback_url") or "").strip()
        if "feedback_heartbeat" in data:
            patch["feedback_heartbeat"] = bool(data.get("feedback_heartbeat"))
        if "feedback_consent" in data:
            patch["feedback_consent"] = bool(data.get("feedback_consent"))
        if "default_isolation" in data:
            patch["default_isolation"] = data.get("default_isolation") or "none"
        if "default_jvm_args" in data:
            patch["default_jvm_args"] = data.get("default_jvm_args") or ""
        if "update_url" in data:
            patch["update_url"] = data.get("update_url") or ""
        if "download_source" in data:
            patch["download_source"] = data.get("download_source") or "auto"
        if "community_source" in data:
            patch["community_source"] = data.get("community_source") or "auto"
        if "use_system_proxy" in data:
            patch["use_system_proxy"] = bool(data.get("use_system_proxy"))
        for key in ("launcher_visibility", "gc_preset", "custom_homepage", "homepage_mode",
                    "window_mode", "offline_skin", "instances_dir", "default_java"):
            if key in data:
                patch[key] = data.get(key)
        # 设置页的「默认实例」与实例页的「设为默认」都走这里；之前这个键不在白名单里，
        # 前端提交了也被静默丢掉，界面上却提示已保存。
        if "default_instance" in data:
            name = str(data.get("default_instance") or "").strip()
            if name:
                patch["default_instance"] = name
        if "download_limit_kbps" in data:
            patch["download_limit_kbps"] = int(data.get("download_limit_kbps") or 0)
        if "auto_check_update" in data:
            patch["auto_check_update"] = bool(data.get("auto_check_update"))
        if "skip_assets" in data:
            patch["skip_assets"] = bool(data.get("skip_assets"))
        if "ui_dark" in data:
            patch["ui_dark"] = bool(data.get("ui_dark"))
        # 外观 / 壁纸 / 动效 / 首次运行（与 get_settings 成对；键表照 app/backend.py save_settings）。
        # 之前这些键不在白名单里，WPF 写了桥静默丢、_call_kwargs 也不报——两端都报成功。
        if "theme_color" in data:
            color = str(data.get("theme_color") or "").strip()
            if color:
                patch["theme_color"] = color
        for key in ("ui_motion", "ui_fly_animation", "allow_multi_instance",
                    "show_hidden_versions", "first_run", "ui_background_shuffle"):
            if key in data:
                patch[key] = bool(data.get(key))
        if "ui_fly_duration_ms" in data:
            patch["ui_fly_duration_ms"] = _clamp_int(data.get("ui_fly_duration_ms"), 1, 10000, 620)
        if "ui_background_interval" in data:
            patch["ui_background_interval"] = _clamp_int(data.get("ui_background_interval"), 1, 1440, 10)
        if "ui_background_blur" in data:
            patch["ui_background_blur"] = _clamp_int(data.get("ui_background_blur"), 0, 40, 0)
        if "ui_background_dim" in data:
            patch["ui_background_dim"] = _clamp_int(data.get("ui_background_dim"), 0, 80, 0)
        if "ui_sidebar_opacity" in data:
            patch["ui_sidebar_opacity"] = _clamp_opacity(data.get("ui_sidebar_opacity"))
        if "ui_window_aspect" in data:
            patch["ui_window_aspect"] = _window_aspect(data.get("ui_window_aspect"))
        for key in ("export_dir", "global_mods_dir"):
            if key in data:
                patch[key] = str(data.get(key) or "").strip()
        if "default_priority" in data:
            patch["default_priority"] = str(data.get("default_priority") or "normal")
        # 壁纸：单图 / 文件夹动了哪个都把旧的那一组压进历史栈，「撤销上一张」才有得退
        # （与 app/backend.py 一致；undo_background / reset_background 已经在读这两个栈）。
        if "ui_background" in data or "ui_background_folder" in data:
            from mclauncher.config import push_background_history as _push_bg_history
            old_bg = str(CONFIG.get("ui_background") or "")
            old_dir = str(CONFIG.get("ui_background_folder") or "")
            new_bg = str(data.get("ui_background", old_bg) or "")
            new_dir = str(data.get("ui_background_folder", old_dir) or "")
            if (new_bg, new_dir) != (old_bg, old_dir):
                images, folders = _push_bg_history(old_bg, old_dir)
                patch["ui_background_history"] = images
                patch["ui_background_folder_history"] = folders
            patch["ui_background"] = new_bg
            patch["ui_background_folder"] = new_dir
        # 侧栏编排：空列表要能写进去（「一项都不隐藏」是合法状态，不是没提交），
        # 所以按「键在不在 data 里」判断，不按值真假。
        for key in ("ui_nav_order", "ui_nav_pinned", "ui_nav_hidden"):
            if key in data:
                patch[key] = _nav_keys(data.get(key))
        if "ui_section_members" in data:
            patch["ui_section_members"] = _nav_members(data.get("ui_section_members")) or None
        if "ui_nav_groups" in data:
            patch["ui_nav_groups"] = _nav_groups(data.get("ui_nav_groups")) or None
        if "ui_nav_style" in data:
            style = str(data.get("ui_nav_style") or "").strip()
            patch["ui_nav_style"] = style if style in ("compact", "grouped") else "grouped"
        if "ui_nav_defaults" in data:
            patch["ui_nav_defaults"] = str(data.get("ui_nav_defaults") or "")
        if "ui_sidebar_width" in data:
            try:
                # 越界的夹回去（140~320 是侧栏能用的范围），非数字当没设过
                width = max(140, min(320, int(data.get("ui_sidebar_width"))))
            except (TypeError, ValueError):
                width = 0
            patch["ui_sidebar_width"] = width or None
        CONFIG.update(patch)
        CONFIG.save()
        if "instances_dir" in patch:
            self._inst_cache = None

    def collect_sysinfo(self, force: bool = False, scan_system_java: bool = False) -> dict:
        from mclauncher import sysinfo as sysinfo_mod
        return sysinfo_mod.collect(force=force, scan_system_java=scan_system_java)

    def sysinfo_text(self, info=None) -> str:
        from mclauncher import sysinfo as sysinfo_mod
        return sysinfo_mod.format_text(info)

    def submit_feedback(self, category: str, title: str, body: str, contact: str = "",
                        include_sysinfo: bool = True) -> dict:
        from mclauncher import feedback as fb
        return fb.submit(
            category=category, title=title, body=body, contact=contact,
            include_sysinfo=include_sysinfo)

    def submit_crash_feedback(self, report: dict, extra: str = "") -> dict:
        from mclauncher import feedback as fb
        return fb.submit_crash(report, extra)

    def feedback_history(self) -> list:
        from mclauncher import feedback as fb
        return fb.history()

    def help_articles(self, query: str = "") -> list:
        from mclauncher import help_content as hc
        return [BackendAPI._localize_article(a) for a in hc.search_articles(query)]

    def help_article(self, article_id: str) -> dict:
        from mclauncher import help_content as hc
        return BackendAPI._localize_article(hc.get_article(article_id) or {})

    @staticmethod
    def _localize_article(article: dict) -> dict:
        """帮助文章的标题过一遍词表（词表里有的才会变）；正文是整篇文章，不翻。"""
        if not isinstance(article, dict) or not article.get("title"):
            return article
        out = dict(article)
        out["title"] = tr(str(out["title"]))
        return out

    def get_accounts(self) -> list[str]:
        names = [tr("离线模式")]
        for acc in self.accounts.accounts:
            name = acc.get("name")
            if name and name not in names:
                names.append(name)
        return names

    def get_account_rows(self) -> list[dict]:
        from mclauncher import skin as skin_mod
        rows = []
        for acc in self.accounts.accounts:
            rows.append({
                "name": acc.get("name") or "",
                "type": acc.get("type") or "offline",
                "uuid": acc.get("uuid") or "",
                "api": acc.get("api") or "",
                "avatar": skin_mod.avatar_url(acc),
                "body": skin_mod.body_url(acc),
                "active": acc.get("name") == self.accounts.active,
                "skin_file": acc.get("skin_file") or "",
                "skin_model": skin_mod.skin_model(acc),
            })
        return rows

    def set_account_skin(self, name: str, path: str = "", model: str = "classic",
                         data: str = "") -> dict:
        """给离线账号绑一张自定义皮肤（PNG）。path 和 data 都空表示清除。

        `data` 收浏览器文件选择器读出来的 base64（可带 data: 前缀）——Web 前端拿不到
        真实路径，只能走这条；桌面端仍可直接传 `path`。真正让皮肤显示出来的是启动时
        拉起的本地 Yggdrasil 服务，见 mclauncher/skinserver.py。
        """
        import base64
        import binascii
        from mclauncher import skin as skin_mod
        acc = self.accounts.get_account(name)
        if not acc:
            raise ValueError(tr("没有这个账号：{0}").format(name))
        if acc.get("type") != "offline":
            raise ValueError(tr("自定义皮肤只对离线账号有效；正版和皮肤站账号的皮肤在各自的网站上改"))
        blob = (data or "").strip()
        if blob:
            raw = blob.split(",", 1)[-1] if blob.startswith("data:") else blob
            try:
                png = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(tr("皮肤数据不是有效的 base64")) from exc
            skin_mod.validate_skin(png)
            acc["skin_file"] = skin_mod.save_skin_bytes(name, png)
            acc["skin_model"] = skin_mod.SLIM if str(model).lower() == "slim" else skin_mod.CLASSIC
        elif not (path or "").strip():
            skin_mod.remove_skin(acc)
            acc.pop("skin_file", None)
            acc.pop("skin_model", None)
        else:
            acc["skin_file"] = skin_mod.import_skin(name, path)
            acc["skin_model"] = skin_mod.SLIM if str(model).lower() == "slim" else skin_mod.CLASSIC
        self.accounts.save()
        self._emit("ui_changed", {})
        return {"name": name, "skin_file": acc.get("skin_file") or "",
                "skin_model": skin_mod.skin_model(acc)}

    def get_account_skin(self, name: str) -> dict:
        """账号当前绑的皮肤；`data_url` 可以直接塞进 <img src> 预览。"""
        import base64
        from mclauncher import skin as skin_mod
        acc = self.accounts.get_account(name) or {}
        png = skin_mod.load_skin_png(acc)
        return {
            "name": name,
            "skin_file": acc.get("skin_file") or "",
            "skin_model": skin_mod.skin_model(acc),
            "data_url": ("data:image/png;base64,"
                         + base64.b64encode(png).decode("ascii")) if png else "",
        }

    def remove_account(self, name: str):
        self.accounts.remove_account(name)
        self._emit("ui_changed", {})

    def set_active_account(self, name: str):
        self.accounts.set_active(name)
        self._emit("ui_changed", {})
        return self.accounts.active

    def add_offline_account(self, username: str, skin: str = ""):
        acc = self.accounts.offline_account(
            username, skin=skin or CONFIG.get("offline_skin") or "default")
        self.accounts.add_account({**acc, "type": "offline"})
        self._emit("ui_changed", {})
        return acc["name"]
        return acc["name"]

    def start_authlib_login(self, api: str, username: str, password: str) -> str:
        return self.start_task("皮肤站登录", self._authlib_login_impl, api, username, password)

    def get_version_settings(self, instance: str, version: str) -> dict:
        from mclauncher import version_settings as vs
        return vs.load(self._instance(instance), version)

    def save_version_settings(self, instance: str, version: str, data: dict) -> dict:
        from mclauncher import version_settings as vs
        out = vs.save(self._instance(instance), version, data or {})
        self._emit("ui_changed", {})
        return out

    def repair_version(self, instance: str, version: str) -> str:
        return self.start_task(f"修复 {version}", self._repair_impl, instance, version)

    def preflight_launch(self, instance: str = "", version: str = "",
                         memory_mb: int = 0, java: str = "") -> dict:
        from mclauncher import preflight as preflight_mod
        from mclauncher.instances import JAVA_AUTO
        java_exe = ""
        if java and java not in (JAVA_AUTO, "auto", "default", ""):
            java_exe = str(java)
        return preflight_mod.check_launch(
            self._instance(instance or ""), version or "",
            memory_mb=int(memory_mb or 0), java_exe=java_exe,
        )

    def apply_crash_action(self, action: dict | None = None, report: dict | None = None) -> dict:
        action = action or {}
        report = report or {}
        aid = (action.get("id") or "").strip()
        instance = (action.get("instance") or report.get("instance")
                    or CONFIG.get("default_instance") or "default")
        version = (action.get("version") or report.get("version") or "")

        if aid == "disable_mods":
            mods = list(action.get("mods") or [])
            done, failed = [], []
            for name in mods:
                try:
                    self.disable_mod(instance, name, version)
                    done.append(name)
                except Exception as exc:
                    failed.append(f"{name}: {exc}")
            if not done and failed:
                return {"ok": False, "message": tr("未能禁用：") + "; ".join(failed)}
            msg = tr("已禁用 {0} 个 Mod").format(len(done))
            if failed:
                msg += tr("；部分失败：") + "; ".join(failed)
            return {"ok": True, "message": msg}

        if aid == "repair_version":
            if not version:
                return {"ok": False, "message": tr("报告里没有版本号，无法修复")}
            tid = self.repair_version(instance, version)
            return {"ok": True, "message": tr("已开始修复 {0}").format(version), "task_id": tid}

        if aid == "need_java":
            major = int(action.get("major") or 17)
            tid = self.download_java(str(major), vendor="adoptium")
            return {"ok": True, "message": tr("已开始下载 Java {0}").format(major), "task_id": tid}

        if aid == "bump_memory":
            mb = int(action.get("memory_mb") or 6144)
            mb = max(1024, min(32768, mb))
            CONFIG.set("memory_mb", mb)
            CONFIG.save()
            self._emit("ui_changed", {})
            return {"ok": True, "message": tr("默认内存已设为 {0} MB").format(mb)}

        if aid == "open_mods_folder":
            from mclauncher.crash import open_path
            inst = self._instance(instance)
            folder = getattr(self, "_mods_folder", None)
            if callable(folder):
                path = folder(inst, version)
            else:
                path = inst.path / "mods"
            path.mkdir(parents=True, exist_ok=True)
            open_path(path)
            return {"ok": True, "message": tr("已打开 Mods 文件夹")}

        if aid == "open_crash_file":
            from pathlib import Path as _P
            from mclauncher.crash import open_path
            target = (action.get("path") or report.get("direct_file") or "").strip()
            if not target or not _P(target).is_file():
                return {"ok": False, "message": tr("没有可打开的崩溃文件")}
            open_path(target)
            return {"ok": True, "message": tr("已打开崩溃报告")}

        if aid == "open_gpu_hint":
            return {
                "ok": True,
                "message": tr(
                    "显卡/OpenGL 相关崩溃：请更新显卡驱动，关闭独显强制、"
                    "超采样/滤镜，并确认不是远程桌面/虚拟机缺 OpenGL。"
                ),
            }

        if aid == "reset_jvm_args":
            CONFIG.set("default_jvm_args", "")
            CONFIG.save()
            try:
                from mclauncher import version_settings as vs
                inst = self._instance(instance)
                if version:
                    data = vs.load(inst, version)
                    data["jvm_args"] = ""
                    vs.save(inst, version, data)
            except Exception:
                pass
            self._emit("ui_changed", {})
            return {"ok": True, "message": tr("已清空自定义 JVM 参数")}

        return {"ok": False, "message": tr("未知动作: {0}").format(aid)}

    def export_modpack(self, instance: str, dest: str = "") -> str:
        return self.start_task(f"导出整合包 {instance}", self._export_pack_impl, instance, dest)

    def check_mod_updates(self, instance: str) -> list:
        from mclauncher.mod_update import check_updates
        return check_updates(self._instance(instance))

    def start_mod_updates(self, instance: str) -> str:
        return self.start_task(f"检查模组更新 {instance}", self._mod_update_impl, instance)

    def apply_mod_update(self, instance: str, row: dict) -> str:
        from mclauncher.mod_update import apply_update
        name = apply_update(self._instance(instance), row)
        self._emit("ui_changed", {})
        return name

    def cleaner_preview(self) -> dict:
        from mclauncher import cleaner as cleaner_mod
        return cleaner_mod.preview()

    def cleaner_apply(self, kinds=None) -> dict:
        from mclauncher import cleaner as cleaner_mod
        return cleaner_mod.apply(kinds)

    def check_update(self) -> dict:
        from mclauncher import updater as updater_mod
        return updater_mod.check()

    def fetch_news(self) -> list:
        from mclauncher import news as news_mod
        return news_mod.fetch()

    def cached_news(self) -> list:
        from mclauncher import news as news_mod
        return news_mod.load_cached()

    def lan_hint(self, port: int = 25565) -> str:
        from mclauncher import lan as lan_mod
        return lan_mod.lan_hint(port)

    def local_ips(self) -> list:
        from mclauncher import lan as lan_mod
        return lan_mod.local_ips()

    def skin_urls(self, account_name: str = "") -> dict:
        from mclauncher import skin as skin_mod
        if self._is_offline_account(account_name):
            acc = {"type": "offline", "name": "Steve"}
        else:
            acc = self.accounts.get_account(account_name) or {"type": "offline", "name": account_name}
        return {"avatar": skin_mod.avatar_url(acc), "body": skin_mod.body_url(acc)}

    def authlib_presets(self) -> list:
        from mclauncher.authlib import PRESETS
        return [{"name": a, "api": b} for a, b in PRESETS]

    def get_installed_mod_entries(self, instance: str, version: str = "") -> list:
        inst = self._instance(instance)
        if version:
            return mods_mod.list_mod_entries_at(self._mods_folder(inst, version))
        return mods_mod.list_instance_mod_entries(inst)

    def get_mods_targets(self, instance: str) -> list[dict]:
        from mclauncher import version_settings as vs
        inst = self._instance(instance)
        rows = [{"label": tr("实例共享 mods 目录"), "value": ""}]
        for vid in inst.installed_ids():
            iso = vs.load(inst, vid).get("isolation")
            if iso in (vs.ISOLATION_MODS, vs.ISOLATION_ALL):
                rows.append({"label": f"{vid} · {tr('独立 mods')}", "value": vid})
        return rows

    def open_mods_folder(self, instance: str, version: str = "") -> str:
        folder = self._mods_folder(self._instance(instance), version)
        utils.ensure_dir(folder)
        if os.name == "nt":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        return str(folder)

    def get_installed_modpacks(self, instance: str) -> list[str]:
        meta = self._instance(instance).meta() or {}
        pack = meta.get("modpack")
        if isinstance(pack, dict) and pack.get("name"):
            label = pack.get("name")
            if pack.get("version"):
                label = f"{label} {pack.get('version')}"
            return [str(label)]
        return []

    def open_global_mods(self):
        from mclauncher import global_mods as gm
        path = gm.root()
        utils.ensure_dir(path)
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def start_self_update(self) -> str:
        return self.start_task("更新启动器", self._self_update_impl)

    def get_version_list(self) -> list[dict]:
        cached = utils.read_json(utils.ROOT / "cache" / "version_manifest.json", None) or {}
        versions = {
            v["id"]: v for v in cached.get("versions", [])
            if isinstance(v, dict) and v.get("id")
        }
        return self._version_rows(versions)

    def fetch_version_list(self) -> list[dict]:
        dm = DownloadManager(threads=2)
        versions = manifest_mod.list_remote_versions(dm) or {}
        return self._version_rows(versions)

    def _version_rows(self, versions) -> list[dict]:
        rows = []
        for vid, v in (versions or {}).items():
            raw = v.get("type") or "snapshot"
            if raw == "release":
                vtype = "release"
            elif raw in ("old_alpha", "old_beta"):
                vtype = raw
            else:
                vtype = "snapshot"
            rows.append({
                "version": vid,
                "type": vtype,
                "date": str(v.get("releaseTime") or v.get("time") or "")[:10],
            })
        rows.sort(key=lambda r: r["date"], reverse=True)
        return rows

    def get_installed_versions(self, instance: str, include_hidden: bool = False) -> list[str]:
        from mclauncher import version_settings as vs
        if instance:
            inst = self._instance(instance)
            ids = inst.installed_ids()
            if include_hidden or CONFIG.get("show_hidden_versions"):
                return ids
            return [vid for vid in ids if not vs.load(inst, vid).get("hidden")]
        out = []
        for name in list_instances():
            for vid in Instance(name).installed_ids():
                out.append(f"{name} / {vid}")
        return out

    def get_instances(self) -> list[dict]:
        """实例表快照（带 2.5s TTL 缓存，对齐 app/backend.py.get_instances）。"""
        now = time.monotonic()
        cached = self._inst_cache
        if cached is not None and now - self._inst_cache_at < 2.5:
            return [dict(r) for r in cached]
        self._ensure_default_instance()
        rows = []
        for name in list_instances():
            inst = Instance(name)
            ids = inst.installed_ids()
            meta = inst.meta() or {}
            pack = meta.get("modpack") if isinstance(meta.get("modpack"), dict) else {}
            pack_name = pack.get("name") if pack else None
            mc = pack_name or meta.get("mc_version") or (ids[0] if ids else tr("未安装版本"))
            rows.append({
                "name": name,
                "versions": len(ids),
                "mc": str(mc),
                "pack": pack_name or "",
                "pack_version": (pack.get("version") if pack else "") or "",
                "mc_version": (pack.get("mc_version") if pack else None) or meta.get("mc_version") or "",
                "java": inst.java_pref(),
                "java_label": self.instance_java_label(name),
            })
        self._inst_cache = rows
        self._inst_cache_at = now
        return [dict(r) for r in rows]

    def _modpack_row(self, hit: dict, default_source: str = "") -> dict:
        src = (hit.get("source") or default_source or "").lower()
        return {
            "name": hit.get("title") or hit.get("name") or "?",
            "author": hit.get("author") or "?",
            "downloads": int(hit.get("downloads") or 0),
            "id": hit.get("id"),
            "slug": hit.get("slug"),
            "source": src or default_source,
            "description": hit.get("description") or "",
        }

    def search_modpacks(self, query: str, source: str, extra: dict | None = None) -> list[dict]:
        src = self._catalog_source(source)
        extra = extra or {}
        q = (query or "").strip()
        if not q:
            rows = []
            seen = set()
            for title, pack_src, key, slug in POPULAR_MODPACKS:
                if src != "all" and pack_src != src and pack_src == "modrinth":
                    continue
                if src != "all" and pack_src != src and key != CBC_CF_ID:
                    continue
                row = {
                    "name": title,
                    "author": "CurseForge" if pack_src == "curseforge" else "Modrinth",
                    "downloads": 0,
                    "id": key if pack_src == "curseforge" else None,
                    "slug": slug if pack_src == "curseforge" else key,
                    "source": pack_src,
                    "description": tr("Forge 1.20.1 黄铜协奏曲，不是 Create+/CDC") if key == CBC_CF_ID else "",
                }
                mark = (row["source"], row["id"] or row["slug"])
                if mark in seen:
                    continue
                seen.add(mark)
                if key == CBC_CF_ID:
                    rows.insert(0, row)
                else:
                    rows.append(row)
            self._pack_cache = rows
            return rows
        dm = DownloadManager(threads=2)
        key = CONFIG.get("curseforge_api_key")
        from mclauncher.catalog_files import category_facets
        cats = category_facets(extra.get("category") or extra.get("type") or "")
        gv = extra.get("game_version") or extra.get("version") or ""
        if isinstance(gv, str) and gv.startswith("全部"):  # i18n:ignore 协议值：前端传的筛选项原文
            gv = ""
        hits = []
        try:
            hits = modpack_mod.search_modpacks_chinese(
                dm, q, limit=25, api_key=key, game_version=gv or None,
                categories=cats or None)
        except Exception:
            hits = []
        if hits and any(h.get("matched_alias") for h in hits):
            rows = [self._modpack_row(h, src) for h in hits]
            self._pack_cache = rows
            return rows
        if not hits:
            fetchers = []
            if src in ("all", "modrinth"):
                fetchers.append(("modrinth", lambda: modpack_mod.modrinth_search(
                    dm, q, limit=25, game_version=gv or None, categories=cats or None)))
            if src in ("all", "curseforge"):
                fetchers.append(("curseforge", lambda: modpack_mod.search_cf_modpacks(
                    dm, q, limit=25, api_key=key, game_version=gv or None,
                    categories=cats or None)))
            hits = mods_mod.rank_hits(self._gather_hits(fetchers), q, "modpack")
        else:
            hits = sorted(
                hits,
                key=lambda h: 0 if (h.get("source") or src) == src else 1,
            )
        rows = [self._modpack_row(h, src) for h in hits]
        self._pack_cache = rows
        return rows

    def _popular_mods_offline(self, src: str) -> list[dict]:
        """联网拿不到热门榜时退回内置的中文推荐清单。"""
        rows = []
        for title, mod_src, key, *_rest in POPULAR_MODS:
            if src != "all" and mod_src != src:
                continue
            rows.append({
                "name": title,
                "author": "CurseForge" if mod_src == "curseforge" else "Modrinth",
                "downloads": 0,
                "id": key if mod_src == "curseforge" else None,
                "slug": None if mod_src == "curseforge" else key,
                "source": mod_src,
            })
        self._mod_cache = rows
        return rows

    def search_mods(self, query: str, source: str, extra: dict | None = None) -> list[dict]:
        src = self._catalog_source(source)
        q = (query or "").strip()
        dm = DownloadManager(threads=2)
        extra = extra or {}
        gv = extra.get("game_version") or extra.get("version") or ""
        if isinstance(gv, str) and gv.startswith("全部"):  # i18n:ignore 协议值：前端传的筛选项原文
            gv = ""
        from mclauncher.catalog_files import category_facets, cf_category_tokens
        label = extra.get("category") or extra.get("type") or ""
        cats = category_facets(label)
        cf_cats = cf_category_tokens(label)
        fetchers = []
        if src in ("all", "modrinth"):
            fetchers.append(("modrinth", lambda: mods_mod.search_mods(
                dm, q, limit=30, game_version=gv or None, categories=cats)))
        if src in ("all", "curseforge"):
            fetchers.append(("curseforge", lambda: mods_mod.search_curseforge(
                dm, q or None, limit=30, api_key=CONFIG.get("curseforge_api_key"),
                class_id=mods_mod.CF_CLASS_MOD, game_version=gv or None,
                categories=cf_cats or None)))
        # 空查询走的是同一条路：两个源各自按下载量取头一页，合并后按折算下载量排，
        # 也就是「热门推荐」。联网整个失败时才退回内置清单。
        try:
            hits = self._gather_hits(fetchers)
        except Exception:
            if q:
                raise
            hits = []
        if not q and not hits:
            return self._popular_mods_offline(src)
        rows = []
        for h in mods_mod.rank_hits(hits, q, "mod"):
            rows.append({
                "name": h.get("title") or h.get("name") or "?",
                "author": h.get("author") or "?",
                "downloads": int(h.get("downloads") or 0),
                "id": h.get("id"),
                "slug": h.get("slug"),
                "source": h.get("source") or src,
                "description": h.get("description") or h.get("summary") or "",
                "tags": h.get("tags") or [],
                "updated": h.get("updated") or "",
            })
        self._mod_cache = rows
        return rows

    @staticmethod
    def _catalog_source(source: str) -> str:
        s = (source or "").strip().lower()
        if s in ("", "全部", "all"):  # i18n:ignore 协议值：来源筛选原文
            return "all"
        if s.startswith("curse"):
            return "curseforge"
        return "modrinth"

    @staticmethod
    def _gather_hits(fetchers) -> list[dict]:
        """依次取各来源结果。部分源失败保留其余；全部失败才抛出。

        与 app/backend.py 同一套语义：搜索报错不能伪装成「没搜到」。
        """
        rows: list[dict] = []
        errors: list[Exception] = []
        for tag, fetch in fetchers:
            try:
                for hit in fetch() or []:
                    if isinstance(hit, dict):
                        hit.setdefault("source", tag)
                        rows.append(hit)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        if errors and len(errors) == len(fetchers):
            raise errors[0]
        return rows

    def _content_row(self, hit: dict, default_source: str = "") -> dict:
        src = hit.get("source") or default_source
        return {
            "name": hit.get("title") or hit.get("name") or "?",
            "author": hit.get("author") or "?",
            "downloads": int(hit.get("downloads") or 0),
            "id": hit.get("id"),
            "slug": hit.get("slug"),
            "source": src,
            "description": hit.get("description") or hit.get("summary") or "",
            "tags": hit.get("tags") or [],
            "updated": hit.get("updated") or "",
        }

    def _search_content(self, kind: str, query: str, source: str, extra: dict | None = None) -> list[dict]:
        spec = mods_mod.CONTENT_KINDS[kind]
        src = (source or "").lower()
        extra = extra or {}
        want_mr = src in ("", "全部", "all", "modrinth")  # i18n:ignore 协议值
        want_cf = src in ("", "全部", "all") or src.startswith("curse")  # i18n:ignore 协议值
        if src.startswith("modrinth"):
            want_cf = False
        if src.startswith("curse"):
            want_mr = False
        dm = DownloadManager(threads=2)
        rows = []
        q = (query or "").strip()
        gv = extra.get("game_version") or extra.get("version") or ""
        if isinstance(gv, str) and gv.startswith("全部"):  # i18n:ignore 协议值：前端传的筛选项原文
            gv = ""
        from mclauncher.catalog_files import category_facets, cf_category_tokens
        label = extra.get("category") or extra.get("type") or ""
        cats = category_facets(label)
        cf_cats = cf_category_tokens(label)
        fetchers = []
        if want_mr:
            fetchers.append(("modrinth", lambda: mods_mod.search_modrinth_projects(
                dm, q, spec["mr"], limit=30, game_version=gv or None, categories=cats)))
        if want_cf:
            fetchers.append(("curseforge", lambda: mods_mod.search_curseforge(
                dm, q or None, limit=30,
                api_key=CONFIG.get("curseforge_api_key"),
                class_id=spec["cf"],
                game_version=gv or None,
                categories=cf_cats or None,
            )))
        for hit in mods_mod.rank_hits(self._gather_hits(fetchers), q, kind):
            row = self._content_row(hit, hit.get("source") or "")
            if hit.get("source") == "curseforge":
                row["description"] = hit.get("summary") or row["description"]
            rows.append(row)
        return rows

    def search_shaders(self, query: str, source: str, extra: dict | None = None) -> list[dict]:
        return self._search_content("shader", query, source, extra)

    def search_resourcepacks(self, query: str, source: str, extra: dict | None = None) -> list[dict]:
        return self._search_content("resourcepack", query, source, extra)

    def search_datapacks(self, query: str, source: str, extra: dict | None = None) -> list[dict]:
        return self._search_content("datapack", query, source, extra)

    def get_java_list(self, scan_system: bool = False) -> list[dict]:
        javas = java_mod.all_javas() if scan_system else java_mod.list_installed_javas()
        rows = []
        for j in javas:
            rows.append({
                "name": j.get("name") or f"Java {j.get('major')}",
                "major": str(j.get("major") or "?"),
                "path": j.get("exe") or j.get("path") or "",
            })
        return rows

    def normalize_java_pref(self, java: str) -> str:
        if not java or java in (JAVA_AUTO, "auto", "default"):
            return JAVA_AUTO
        for j in java_mod.all_javas():
            if j.get("name") == java or j.get("exe") == java:
                return j.get("exe") or java
        p = Path(java)
        if p.is_file():
            return str(p)
        return java

    def get_instance_java(self, name: str) -> str:
        return self._instance(name).java_pref()

    def set_instance_java(self, name: str, java: str):
        self._instance(name).set_java_pref(self.normalize_java_pref(java))

    def java_combo_options(self, instance: str, scan_system: bool = False) -> list[dict]:
        opts = [{"label": JAVA_AUTO, "value": JAVA_AUTO}]
        seen = set()
        for j in self.get_java_list(scan_system=scan_system):
            exe = j.get("path") or ""
            if not exe or exe in seen:
                continue
            seen.add(exe)
            opts.append({"label": j.get("name") or exe, "value": exe})
        stored = self.get_instance_java(instance)
        if stored != JAVA_AUTO and stored not in seen:
            opts.append({"label": tr("已保存 ({0})").format(stored), "value": stored})
        return opts

    def java_combo_label_for(self, instance: str, options=None) -> str:
        stored = self.get_instance_java(instance)
        for o in options or self.java_combo_options(instance):
            if o["value"] == stored:
                return o["label"]
        return JAVA_AUTO

    def instance_java_label(self, name: str) -> str:
        stored = self.get_instance_java(name)
        if stored == JAVA_AUTO:
            return JAVA_AUTO
        for j in java_mod.all_javas():
            if j.get("exe") == stored:
                return f"Java {j.get('major') or '?'}"
        return Path(stored).name

    def _install_game_impl(self, progress, log, version, loader="无", loader_version="", instance="", extra=None):  # i18n:ignore 协议值：「无」= 不装加载器
        extra = dict(extra or {})
        extra.setdefault("skip_assets", bool(CONFIG.get("skip_assets")))
        inst = self._instance(instance)
        dm = self._dm(progress, log)
        installer = Installer(
            inst, dm,
            on_progress=dm.on_progress,
            cancel=dm.cancel,
        )
        log(f"安装到实例 {inst.name}")
        from mclauncher.game_install import install_game
        vid = install_game(installer, version, loader, loader_version, extra)
        log(f"版本安装完成: {vid}")
        iso = CONFIG.get("default_isolation") or "none"
        if iso and iso != "none":
            from mclauncher import version_settings as vs
            vs.save(inst, vid, {"isolation": iso})
            log(f"已套用默认隔离: {iso}")
        return tr("已安装 {0}").format(vid)

    def _install_modpack_impl(self, progress, log, name, source, extra=None):
        extra = extra or {}
        inst = self._instance(extra.get("instance"))
        dm = self._dm(progress, log)
        path = extra.get("path") or name
        on_progress = dm.on_progress
        src_l = (source or "").lower()
        log(tr("整合包安装引擎：按声明的 Forge/Fabric 版本直装（不依赖残缺的 Maven 列表）"))

        if src_l.startswith("本地") or Path(str(path)).is_file():  # i18n:ignore 协议值：source=本地 是前端传的原文
            p = Path(path)
            log(f"从本地文件安装: {p}")
            log(f"实例: {inst.name}  路径: {inst.path}")
            if p.suffix.lower() == ".mrpack":
                meta = modpack_mod.install_mrpack(dm, str(p), inst, on_progress=on_progress, cancel=dm.cancel)
            else:
                meta = modpack_mod.install_cf_zip(dm, str(p), inst, on_progress=on_progress, cancel=dm.cancel)
        elif src_l.startswith("curse"):
            hit = extra if extra.get("id") or extra.get("slug") else self._lookup_pack(name, source)
            addon_id = hit.get("id")
            slug = hit.get("slug")
            if not addon_id and not slug:
                raise RuntimeError(tr("无法解析整合包: {0}").format(name))
            log(f"从 CurseForge 安装 {hit.get('name') or name} (id={addon_id} slug={slug})")
            log(f"实例: {inst.name}  路径: {inst.path}")
            if str(addon_id) == str(CBC_CF_ID) or (slug or "") == CBC_CF_SLUG:
                log(tr("目标包：机械动力：黄铜协奏曲（CBC），Minecraft 1.20.1 Forge。这不是 Create+ / CDC。"))
            elif str(addon_id) == str(CDC_CF_ID) or (slug or "") == CDC_CF_SLUG:
                log(tr("目标包：机械动力：齿轮盛宴（CDC），Minecraft 1.20.1 Forge。"))
            existing = (inst.meta() or {}).get("modpack")
            if isinstance(existing, dict) and existing.get("name"):
                log(f"注意：实例 {inst.name} 当前已是 {existing.get('name')} "
                    f"{existing.get('version') or ''} / {existing.get('mc_version') or ''}。"
                    "覆盖安装会混入旧模组，建议先新建实例再装。")
            meta = modpack_mod.install_cf_modpack(
                dm, addon_id, inst,
                api_key=CONFIG.get("curseforge_api_key"),
                on_progress=on_progress, cancel=dm.cancel, cf_slug=slug,
                file_id=extra.get("file_id") or extra.get("version_id"),
            )
        else:
            hit = extra if extra.get("slug") else self._lookup_pack(name, source)
            slug = hit.get("slug") or name
            log(f"从 Modrinth 安装 {hit.get('name') or slug} ({slug})")
            log(f"实例: {inst.name}  路径: {inst.path}")
            meta = modpack_mod.install_mrpack_by_slug(
                dm, slug, inst, on_progress=on_progress, cancel=dm.cancel,
                version_id=extra.get("version_id"))
        if isinstance(meta, dict) and meta.get("instance"):
            CONFIG.set("default_instance", meta["instance"])
            CONFIG.save()
        log(f"整合包安装完成: {(meta or {}).get('name') or name}")

    def _install_mod_impl(self, progress, log, name, instance, extra=None):
        extra = extra or {}
        inst = self._instance(instance or extra.get("instance"))
        dm = self._dm(progress, log)
        on_progress = dm.on_progress
        src_kind = (extra.get("source") or "").lower()
        vid = extra.get("version_id")
        fid = extra.get("file_id")
        gv = extra.get("game_version") or extra.get("mc_version")
        if extra.get("path") or extra.get("url"):
            source = extra.get("path") or extra.get("url")
            log(f"安装模组: {source}")
            mods_mod.install_mod_from_source(dm, str(source), inst, on_progress=on_progress,
                                             version_id=vid)
        elif src_kind.startswith("curse") and extra.get("id"):
            log(f"从 CurseForge 安装模组 id={extra.get('id')}")
            mods_mod.install_curseforge_mod(
                dm, extra["id"], inst, mc_version=gv, on_progress=on_progress, file_id=fid)
        else:
            hit = extra if extra.get("slug") else self._lookup_mod(str(name), extra.get("source") or "Modrinth")
            if hit.get("id") and str(hit.get("source") or src_kind).lower().startswith("curse"):
                log(f"从 CurseForge 安装模组 id={hit.get('id')}")
                mods_mod.install_curseforge_mod(
                    dm, hit["id"], inst, mc_version=gv, on_progress=on_progress,
                    file_id=fid or extra.get("version_id"))
            else:
                slug = hit.get("slug") or name
                log(f"从 Modrinth 安装模组 {slug}")
                mods_mod.install_mod_from_source(
                    dm, str(slug), inst, mc_version=gv, on_progress=on_progress, version_id=vid)
        log(tr("模组安装完成"))

    def _install_content_impl(self, progress, log, kind, name, instance, extra=None):
        extra = dict(extra or {})
        extra.setdefault("name", name)
        extra.setdefault("slug", extra.get("slug") or name)
        inst = self._instance(instance or extra.get("instance"))
        spec = mods_mod.CONTENT_KINDS[kind]
        dm = self._dm(progress, log)
        log(f"安装到 {inst.name}/{spec['subdir']}")
        result = mods_mod.install_content_from_source(
            dm, inst, spec["subdir"], extra=extra, on_progress=dm.on_progress)
        files = (result or {}).get("files") or []
        log(f"完成: {', '.join(files) or name}")
        if kind == "datapack":
            log(tr("数据包已放到实例 datapacks 目录，请复制到对应存档的 datapacks 文件夹后进入世界。"))

    def _download_java_impl(self, progress, log, major):
        dm = self._dm(progress, log)
        log(f"下载 Adoptium Java {major}")
        exe = java_mod.install_adoptium(
            dm, int(major),
            on_progress=dm.on_progress,
        )
        log(f"Java {major} 就绪: {exe}")

    def _terracotta_prepare_impl(self, progress, log):
        dm = self._dm(progress, log)
        terracotta_mod.install(dm, log=log)
        progress(1, 1, tr("启动内核"))
        terracotta_mod.start(log=log)
        return tr("陶瓦联机已就绪")

    def _launch_game_impl(self, progress, log, instance, version, account,
                          username, memory_mb, width, height, java=JAVA_AUTO,
                          extra_game_args=None, force: bool = False):
        if not version:
            raise LaunchError(tr("请先选择版本（到「版本」页安装）"))
        # 多开检查
        allow_multi = bool(CONFIG.get("allow_multi_instance", False))
        if not allow_multi and self.is_game_running():
            raise LaunchError(tr("游戏正在运行中\n若要同时运行多个游戏，请到设置开启「允许多开」"))

        from mclauncher import preflight as preflight_mod
        java_exe_hint = ""
        if java and java != JAVA_AUTO:
            java_exe_hint = self.normalize_java_pref(java) if hasattr(self, "normalize_java_pref") else str(java)
            if java_exe_hint == JAVA_AUTO:
                java_exe_hint = ""
        pf = preflight_mod.check_launch(
            self._instance(instance), version,
            memory_mb=int(memory_mb or 0), java_exe=java_exe_hint or "",
        )
        for it in pf.get("items") or []:
            lvl = it.get("level")
            if lvl in ("error", "warn"):
                log(f"[预检:{lvl}] {it.get('title')}: {it.get('detail')}")
        if not pf.get("ok", True):
            errs = [it for it in (pf.get("items") or []) if it.get("level") == "error"]
            if force:
                # 预检弹框里用户选了「仍要启动」：把忽略了哪几条记进任务日志头，崩溃归因好定位
                log("[预检:强制启动] 忽略 " + str(len(errs)) + " 条 error 强制启动："
                    + "; ".join(f"{e.get('code')}·{e.get('title')}" for e in errs))
            else:
                msg = "\n\n".join(f"· {e.get('title')}\n{e.get('detail')}" for e in errs) or tr("启动预检未通过")
                raise LaunchError(tr("启动预检未通过") + "\n\n" + msg)

        inst = self._instance(instance)
        log(f"实例: {inst.name} | 版本: {version}")
        log(f"实例 Java 设置: {inst.java_pref()}")
        CONFIG.set("default_instance", inst.name)
        CONFIG.save()
        from mclauncher import version_settings as vs
        bound = vs.load(inst, version).get("login_account") or ""
        if bound:
            account = bound
            log(f"该版本绑定账号: {bound}")
        if self._is_offline_account(account):
            acc = self.accounts.offline_account(
                username or "Player", skin=CONFIG.get("offline_skin") or "default")
        else:
            acc = self.accounts.get_account(account)
            if not acc:
                raise LaunchError(tr("账号不存在: {0}").format(account))
            acc = self.accounts.ensure_valid(acc)
        props = self.accounts.launch_props(acc)
        kind = tr("正版") if props.get("user_type") == "msa" else (
            tr("皮肤站") if props.get("authlib_api") else (
                tr("统一通行证") if props.get("nide8_id") else tr("离线")))
        log(f"账号: {props.get('name')} ({kind})")
        log(f"内存: {memory_mb} MB | 分辨率: {width}x{height}")

        from mclauncher import launch_flow
        prep = launch_flow.prepare(inst, version, extra_game_args=extra_game_args, memory_mb=memory_mb)
        memory_mb = prep["memory_mb"] or memory_mb
        extra_game_args = prep["extra_game_args"]
        game_dir = prep["game_dir"]
        launch_flow.run_hook(
            prep["settings"].get("pre_launch") or "", game_dir, log=log,
            wait=bool(prep.get("pre_launch_wait", True)))

        progress(1, 4, tr("检查 Java"))
        vjson = inst.version_json(version) or {}
        try:
            resolved = manifest_mod.resolve_inherits(vjson, lambda pid: inst.version_json(pid))
        except Exception:
            resolved = vjson
        prefer = None
        java_choice = java
        if prep["settings"].get("java") and prep["settings"]["java"] != JAVA_AUTO:
            java_choice = prep["settings"]["java"]
        if not java_choice or java_choice == JAVA_AUTO:
            java_choice = inst.java_pref()
        if not java_choice or java_choice == JAVA_AUTO:
            # 全局默认 Java：版本设置与实例偏好都是「自动」时才生效。
            java_choice = CONFIG.get("default_java") or ""
        if java_choice and java_choice != JAVA_AUTO:
            for j in java_mod.all_javas():
                if j.get("name") == java_choice or j.get("exe") == java_choice:
                    prefer = j.get("exe")
                    break
            if not prefer and Path(java_choice).is_file():
                prefer = java_choice
        need = java_mod.required_java_major(resolved)
        java_exe = java_mod.resolve_launch_java(resolved, prefer=prefer, on_note=log)
        if not java_mod.java_usable_for(resolved, java_exe):
            log(f"未找到 Java {need}，自动下载中…")
            dm = self._dm(progress, log)
            java_exe = java_mod.resolve_launch_java(
                resolved, prefer=None, dm=dm,
                on_progress=dm.on_progress, on_note=log,
            )
        ver_line = next((ln.strip() for ln in (java_mod.java_version_output(java_exe) or "").splitlines() if ln.strip()), "?")
        log(f"Java -version: {ver_line}")
        log(f"使用 Java {java_mod.get_java_major(java_exe) or '?'}: {java_exe}")
        progress(2, 4, tr("构建启动参数"))
        if props.get("authlib_api"):
            from mclauncher import authlib as authlib_mod
            authlib_mod.ensure_injector(self._dm(progress, log), on_note=log)
        if props.get("nide8_id") or prep.get("nide8_id"):
            from mclauncher import nide8 as nide8_mod
            nide8_mod.ensure_jar(self._dm(progress, log), on_note=log)
            if prep.get("nide8_id") and not props.get("nide8_id"):
                props = dict(props)
                props["nide8_id"] = prep["nide8_id"]
        width, height = launch_flow.resolve_resolution(prep, width, height)
        cmd, _natives, _vdir, game_dir = build_launch_command(
            inst, version, props, java_exe,
            memory_mb=memory_mb, width=width, height=height,
            extra_game_args=extra_game_args,
            extra_jvm_args=prep["jvm_args"],
            game_directory=game_dir,
            authlib_api=props.get("authlib_api"),
        )
        log(f"实际启动: {cmd[0]}")
        log(tr("正在启动游戏进程…"))
        progress(3, 4, tr("游戏启动中"))
        worker = getattr(_tls, "worker", None)
        proc = GameProcess(cmd, cwd=game_dir, on_line=log, priority=prep["priority"],
                           window_title=prep.get("window_title") or "")
        with self._game_lock:
            self._game_proc = proc
        self._emit("game_started", {})
        code = None
        # 游戏时长统计
        try:
            from mclauncher import playtime as playtime_mod
            tracker = playtime_mod.PlaytimeTracker(inst.name, version)
        except Exception:
            tracker = None
        if tracker is not None:
            tracker.start()
        try:
            code = proc.wait()
        finally:
            if tracker is not None:
                try:
                    dur = tracker.stop()
                    if dur:
                        log(f"本次游玩 {playtime_mod.format_duration(dur)}")
                except Exception:
                    pass
            with self._game_lock:
                if self._game_proc is proc:
                    self._game_proc = None
            self._emit("game_exited", {"code": code})
        if getattr(worker, "_cancelled", False):
            log(tr("已停止游戏"))
            return
        log(f"游戏已退出，退出码 {code}")
        launch_flow.run_hook(prep["settings"].get("post_launch") or "", game_dir, log=log)
        report = analyze_launch(
            inst, exit_code=code, output_lines=proc.last_lines(),
            started_at=getattr(proc, "started_at", None),
            cancelled=False, version=version,
            extra_roots=[game_dir],
        )
        if report.get("is_crash"):
            log(f"[崩溃分析] {report.get('summary') or report.get('headline')}")
            raise GameCrashError(report)
        return tr("游戏已退出")

    def _microsoft_login_impl(self, progress, log):
        client_id = CONFIG.get("microsoft_client_id") or "00000000402b5328"
        auth = MicrosoftAuthenticator(client_id=client_id)
        worker = getattr(_tls, "worker", None)

        def on_code(code, uri, exp):
            if worker:
                worker.login_code(code, uri)
            log(f"请打开 {uri} 并输入代码 {code}（{exp // 60} 分钟内有效）")

        def on_status(s):
            if worker:
                worker.login_status(str(s))
            log(str(s))
            progress(0, 0, str(s))

        account = auth.login(on_code=on_code, on_status=on_status, open_browser=True)
        self.accounts.add_account(account)
        log(f"登录成功：{account.get('name')}")
        return tr("已登录 {0}").format(account.get('name'))

    def _authlib_login_impl(self, progress, log, api, username, password):
        from mclauncher import authlib as authlib_mod
        authlib_mod.ensure_injector(self._dm(progress, log), on_note=log)
        account = authlib_mod.login(api, username, password)
        self.accounts.add_account(account)
        log(f"皮肤站登录成功：{account.get('name')}")
        return tr("已登录 {0}").format(account.get('name'))

    def _repair_impl(self, progress, log, instance, version):
        from mclauncher.repair import repair
        inst = self._instance(instance)
        dm = self._dm(progress, log)
        installer = Installer(inst, dm, on_progress=dm.on_progress, cancel=dm.cancel)
        return repair(installer, version)

    def _export_pack_impl(self, progress, log, instance, dest):
        from mclauncher.export_pack import export_mrpack
        inst = self._instance(instance)
        if not dest:
            dest = str(utils.ROOT / "exports" / f"{inst.name}.mrpack")
        dm = self._dm(progress, log)
        return export_mrpack(inst, dest, dm=dm, on_note=lambda m, a, b: progress(a, b, m))

    def _mod_update_impl(self, progress, log, instance):
        from mclauncher.mod_update import apply_update, check_updates
        inst = self._instance(instance)
        dm = self._dm(progress, log)
        rows = check_updates(inst, dm=dm)
        if not rows:
            return tr("没有可更新的模组")
        for i, row in enumerate(rows):
            apply_update(inst, row, dm=dm)
            progress(i + 1, len(rows), row.get("name") or "")
        return tr("已更新 {0} 个模组").format(len(rows))

    def _self_update_impl(self, progress, log):
        from mclauncher import updater as updater_mod
        info = updater_mod.check(self._dm(progress, log))
        if not info.get("has_update"):
            return info.get("message") or tr("已是最新")
        log(info.get("message") or tr("下载更新"))
        path = updater_mod.download(info, self._dm(progress, log))
        # 这里不能走 apply_exe：bridge 是宿主壳拉起来的子进程，sys.argv[0]
        # 指向 bridge 自己而不是 PyMCL.exe，替换脚本会盯错目标、还会一直
        # 等一个不会退出的进程。只把包备好，交给宿主壳去替换。
        log(f"更新包已下载: {path}")
        self._emit("update_staged", {"package": str(path), "version": info.get("latest") or ""})
        return tr("更新包已下载到 {0}，关闭启动器后运行它即可完成更新").format(path)

    def _nide8_login_impl(self, progress, log, server_id, username, password):
        from mclauncher import nide8 as nide8_mod
        nide8_mod.ensure_jar(self._dm(progress, log), on_note=log)
        account = nide8_mod.login(server_id, username, password)
        self.accounts.add_account(account)
        log(f"统一通行证登录成功：{account.get('name')}")
        return tr("已登录 {0}").format(account.get('name'))

    def _install_world_impl(self, progress, log, name, instance, extra=None):
        from mclauncher import worlds as worlds_mod
        extra = dict(extra or {})
        extra.setdefault("name", name)
        inst = self._instance(instance or extra.get("instance"))
        dm = self._dm(progress, log)
        target_version = str(extra.get("version") or "")
        log(f"安装世界到 {worlds_mod.saves_root(inst, target_version)}")
        result = worlds_mod.install_world(dm, extra, inst, on_progress=dm.on_progress,
                                          version_id=target_version)
        files = (result or {}).get("files") or []
        log(f"完成: {', '.join(files) or name}")
        return tr("已安装世界 {0}").format(', '.join(files) or name)

    def _export_bat_impl(self, progress, log, instance, version, dest):
        from mclauncher import launch_flow, version_ops as vops
        inst = self._instance(instance)
        acc = self.accounts.get_account(self.accounts.active) if self.accounts.active else None
        if not acc:
            acc = self.accounts.offline_account("Player")
        props = self.accounts.launch_props(acc)
        prep = launch_flow.prepare(inst, version, memory_mb=int(CONFIG.get("memory_mb") or 4096))
        java_exe = java_mod.resolve_launch_java(inst.version_json(version) or {}, on_note=log)
        cmd, _n, _v, gdir = build_launch_command(
            inst, version, props, java_exe,
            memory_mb=prep["memory_mb"] or 4096,
            extra_game_args=prep["extra_game_args"],
            extra_jvm_args=prep["jvm_args"],
            game_directory=prep["game_dir"],
            authlib_api=props.get("authlib_api"),
        )
        if not dest:
            dest = str(utils.ROOT / "exports" / f"launch-{inst.name}-{version}.bat")
        path = vops.export_launch_bat(Path(dest), cmd, gdir)
        log(f"已写出 {path}")
        return path

    # ==================================================================
    # 新增 API：服务器管理
    # ==================================================================

    def list_servers(self, instance: str = "") -> list[dict]:
        from mclauncher import servers as servers_mod
        inst = self._instance(instance)
        return servers_mod.list_servers(inst)

    def add_server(self, instance: str, name: str, ip: str, port: int = 25565,
                   description: str = "") -> dict:
        from mclauncher import servers as servers_mod
        inst = self._instance(instance)
        return servers_mod.add_server(inst, name, ip, port, description)

    def update_server(self, instance: str, index: int, **kwargs) -> dict:
        from mclauncher import servers as servers_mod
        inst = self._instance(instance)
        return servers_mod.update_server(inst, index, **kwargs)

    def delete_server(self, instance: str, index: int):
        from mclauncher import servers as servers_mod
        inst = self._instance(instance)
        servers_mod.delete_server(inst, index)

    def import_servers(self, instance: str, text: str) -> int:
        from mclauncher import servers as servers_mod
        inst = self._instance(instance)
        return servers_mod.import_servers_txt(inst, text)

    def export_servers(self, instance: str) -> str:
        from mclauncher import servers as servers_mod
        inst = self._instance(instance)
        return servers_mod.export_servers_txt(inst)

    # ==================================================================
    # 新增 API：游玩时长
    # ==================================================================

    def get_playtime(self, instance: str = "") -> dict:
        from mclauncher import playtime as playtime_mod
        inst_name = instance or CONFIG.get("default_instance", "default")
        return playtime_mod.get_playtime(inst_name)

    def get_all_playtime(self) -> dict:
        from mclauncher import playtime as playtime_mod
        return playtime_mod.get_all_playtime()

    def get_total_playtime(self) -> int:
        from mclauncher import playtime as playtime_mod
        return playtime_mod.get_total_playtime()

    def format_playtime(self, seconds: int) -> str:
        from mclauncher import playtime as playtime_mod
        return playtime_mod.format_duration(seconds)

    def clear_playtime(self, instance: str = "", version: str = ""):
        from mclauncher import playtime as playtime_mod
        playtime_mod.clear_playtime(instance, version)

    # ==================================================================
    # 新增 API：缩略图
    # ==================================================================

    def thumb_path(self, url: str) -> str:
        from mclauncher import thumbnails as thumb_mod
        return thumb_mod.thumb_path(url)

    def ensure_thumb(self, url: str) -> str:
        from mclauncher import thumbnails as thumb_mod
        return thumb_mod.ensure_thumb(url)

    # ==================================================================
    # 新增 API：Java 多发行版
    # ==================================================================

    def java_vendor_list(self) -> list[str]:
        from mclauncher import java as java_mod
        return java_mod.java_vendor_list()

    def java_vendor_label(self, vendor: str) -> str:
        from mclauncher import java as java_mod
        return java_mod.java_vendor_label(vendor)

    def install_java(self, major: int, vendor: str = "adoptium") -> str:
        return self.start_task(
            f"下载 {vendor} Java {major}",
            self._install_java_impl, major, vendor,
        )

    def _install_java_impl(self, progress, log, major, vendor):
        from mclauncher import java as java_mod
        dm = self._dm(progress, log)
        exe = java_mod.install_java_vendor(dm, major, vendor=vendor, on_progress=dm.on_progress)
        log(f"Java 已安装: {exe}")
        return tr("Java {0} ({1}) 安装完成").format(major, vendor)

    # ==================================================================
    # 新增 API：多语言
    # ==================================================================

    def get_language(self) -> str:
        from mclauncher import i18n
        return i18n.current_language()

    def set_language(self, lang: str):
        from mclauncher import i18n
        i18n.set_language(lang)

    def available_languages(self) -> dict[str, str]:
        from mclauncher import i18n
        return i18n.available_languages()

    def translate(self, key: str, lang: str = "") -> str:
        from mclauncher import i18n
        return i18n._(key, lang or None)

    # ==================================================================
    # 新增 API：前端上传暂存
    # ==================================================================

    def stash_upload(self, name: str, data: str) -> str:
        """把前端读上来的文件落到 ROOT/uploads，返回真实路径。

        浏览器的文件选择器只给文件名不给路径，而导入模组 / 主题 / 本地整合包
        那几个 RPC 收的都是路径——中间就差这一步。`data` 收 base64（可带
        data: 前缀），跟 set_account_skin 是同一套约定。
        """
        import base64
        import binascii
        import re

        blob = (data or "").strip()
        raw = blob.split(",", 1)[-1] if blob.startswith("data:") else blob
        try:
            payload = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(tr("上传的数据不是有效的 base64")) from exc
        if not payload:
            raise ValueError(tr("上传的文件是空的"))

        # 文件名是前端给的，直接当路径用就能被 ../ 跳出暂存目录
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", os.path.basename(name or "")).strip(" .")
        folder = utils.ROOT / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        self._prune_uploads(folder)
        dest = folder / (safe or "upload.bin")
        if dest.exists():
            dest = folder / f"{dest.stem}-{int(time.time())}{dest.suffix}"
        dest.write_bytes(payload)
        return str(dest)

    @staticmethod
    def _prune_uploads(folder: Path, keep_seconds: int = 24 * 3600) -> None:
        """暂存目录只是个中转站：导入完那份拷贝就没用了，留着白占盘。"""
        cutoff = time.time() - keep_seconds
        for old in folder.glob("*"):
            try:
                if old.is_file() and old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass

    # ==================================================================
    # 新增 API：主题包
    # ==================================================================

    def list_themes(self) -> list[dict]:
        from mclauncher import themes as themes_mod
        return themes_mod.list_themes()

    def save_theme(self, name: str) -> dict:
        from mclauncher import themes as themes_mod
        return themes_mod.save_theme(name)

    def load_theme(self, name: str) -> dict:
        from mclauncher import themes as themes_mod
        return themes_mod.load_theme(name)

    def delete_theme(self, name: str):
        from mclauncher import themes as themes_mod
        themes_mod.delete_theme(name)

    def import_theme(self, path: str) -> str:
        from mclauncher import themes as themes_mod
        return themes_mod.import_theme(path)

    def export_theme(self, name: str, dest: str) -> str:
        from mclauncher import themes as themes_mod
        return themes_mod.export_theme(name, dest)

    # ==================================================================
    # 新增 API：启动页自定义布局
    # 与 Qt 版 app/dashboard.py 共用 mclauncher.ui_layout 这一份数据层和
    # config.json 里同一组键：一边拖好的布局，另一边打开就是同一个。
    # 文档格式见 ui_layout 模块头；导入/导出的文件读写由前端自己完成，
    # 这里只收发已经解析好的 JSON 对象。
    # ==================================================================

    def get_layout(self) -> dict:
        """当前生效布局 + 方案列表 + 内置默认 + 各卡片最小尺寸，一次拿全。"""
        from mclauncher import ui_layout as lm
        return {
            "doc": lm.load_active_doc().to_dict(),
            "profile": lm.active_profile(),
            "profiles": sorted(lm.list_profiles().keys()),
            "default": lm.default_doc().to_dict(),
            "min_sizes": {k: list(v) for k, v in lm.CARD_MIN_SIZE.items()},
        }

    def save_layout(self, doc: dict) -> dict:
        """落盘当前布局。命名方案生效中时同步写回方案表（对齐 Qt 版
        LaunchPage._persist_layout_now），切换回来不丢改动。"""
        from mclauncher import ui_layout as lm
        parsed = lm.parse_doc(doc)
        if parsed is None:
            raise ValueError(tr("不是有效的布局文档"))
        name = lm.active_profile()
        lm.save_active_doc(parsed)
        if name:
            lm.save_profile(name, parsed)
        return {"profile": name}

    def save_layout_profile(self, name: str, doc: dict | None = None) -> dict:
        """把布局另存为方案并切换到它。doc 缺省 = 当前生效布局。"""
        from mclauncher import ui_layout as lm
        name = (name or "").strip()
        if not name:
            raise ValueError(tr("方案名称不能为空"))
        if doc is None:
            parsed = lm.load_active_doc()
        else:
            parsed = lm.parse_doc(doc)
            if parsed is None:
                raise ValueError(tr("不是有效的布局文档"))
        lm.save_profile(name, parsed)
        return self.get_layout()

    def activate_layout_profile(self, name: str = "") -> dict:
        """切换布局方案；空名 = 回到内置默认。"""
        from mclauncher import ui_layout as lm
        lm.activate_profile(name)
        return self.get_layout()

    def delete_layout_profile(self, name: str) -> dict:
        from mclauncher import ui_layout as lm
        if not lm.delete_profile(name):
            raise ValueError(tr("布局方案「{0}」不存在").format(name))
        return self.get_layout()

    def reset_layout(self) -> dict:
        from mclauncher import ui_layout as lm
        lm.reset_to_default()
        return self.get_layout()

    def import_layout(self, doc: dict) -> dict:
        """导入一份布局文档（前端已读好的 JSON）。未知卡片类型丢弃，
        结构不对抛错；应用后不改当前方案名（对齐 Qt 版 import_layout_file）。"""
        from mclauncher import ui_layout as lm
        parsed = lm.parse_doc(doc)
        if parsed is None:
            raise ValueError(tr("不是有效的布局文件"))
        lm.save_active_doc(parsed)
        return self.get_layout()

    # ==================================================================
    # 新增 API：官方启动器迁移
    # ==================================================================

    def detect_official_launcher(self) -> bool:
        from mclauncher import official_migrate as om
        return om.detect_official()

    def official_launcher_dir(self) -> str:
        from mclauncher import official_migrate as om
        d = om.official_dir()
        return str(d) if d else ""

    def scan_official_versions(self) -> list[str]:
        from mclauncher import official_migrate as om
        d = om.official_dir()
        if not d:
            return []
        return om.scan_versions(d)

    def migrate_official_launcher(self, instance: str = "default") -> str:
        return self.start_task(
            "导入官方启动器",
            self._migrate_official_impl, instance,
        )

    def _migrate_official_impl(self, progress, log, instance):
        from mclauncher import official_migrate as om
        src = om.official_dir()
        if not src:
            raise FileNotFoundError(tr("未找到官方启动器目录"))
        log(f"正在从 {src} 迁移…")
        progress(1, 3, tr("扫描版本"))
        versions = om.scan_versions(src)
        if not versions:
            log(tr("未发现版本"))
            return tr("无版本可导入")
        log(f"发现 {len(versions)} 个版本")
        progress(2, 3, tr("导入 {0} 个版本（含依赖库）").format(len(versions)))
        result = om.migrate(str(src), instance)
        imported = result.get("versions") or []
        accounts = result.get("accounts") or []
        log(f"已导入 {len(imported)} 个版本（含各版本用到的 libraries）")
        if accounts:
            log("已导入账号: " + "、".join(accounts))
            log(tr("官方只存了访问令牌、没有刷新令牌，过期后需要重新登录"))
        self._emit("ui_changed", {})
        summary = tr("已导入 {0} 个版本").format(len(imported))
        if accounts:
            summary += tr("、{0} 个账号").format(len(accounts))
        return summary

    # ==================================================================
    # 新增 API：多开
    # ==================================================================

    def is_game_running(self) -> bool:
        with self._game_lock:
            proc = self._game_proc
        return proc is not None and getattr(proc, "poll", lambda: 0)() is None

    def allow_multi_instance(self) -> bool:
        return bool(CONFIG.get("allow_multi_instance", False))

    def set_multi_instance(self, allow: bool):
        CONFIG.set("allow_multi_instance", bool(allow))
        CONFIG.save()

    # ==================================================================
    # 新增 API：崩溃报告上传
    # ==================================================================

    def submit_crash_report(self, task_id: str = "") -> str:
        report = self.get_crash(task_id)
        if not report:
            raise LaunchError(tr("没有可上传的崩溃报告"))
        from mclauncher import feedback as fb
        result = fb.submit_crash(report)
        return result.get("message") or tr("已上传")

    # ==================================================================
    # 新增 API：启动命令展示
    # ==================================================================

    def get_launch_command(self, instance: str, version: str, account: str = "",
                           username: str = "", memory_mb: int = 0) -> str:
        from mclauncher import launch_flow, version_ops as vops
        from mclauncher.launcher import build_launch_command
        inst = self._instance(instance)
        if not version:
            raise LaunchError(tr("请先选择版本"))
        vjson = inst.version_json(version) or {}
        from mclauncher import manifest as manifest_mod
        try:
            resolved = manifest_mod.resolve_inherits(vjson, lambda pid: inst.version_json(pid))
        except Exception:
            resolved = vjson
        java_exe = java_mod.resolve_launch_java(resolved, on_note=None)
        if not java_exe:
            java_exe = java_mod.resolve_launch_java(resolved, dm=DownloadManager(threads=2))
        if not java_exe:
            raise LaunchError(tr("无法确定 Java 路径"))
        if not account:
            acc = self.accounts.get_account(self.accounts.active) if self.accounts.active else None
            if not acc:
                acc = self.accounts.offline_account(username or "Player")
        else:
            acc = self.accounts.get_account(account)
            if acc:
                acc = self.accounts.ensure_valid(acc)
            else:
                acc = self.accounts.offline_account(username or "Player")
        props = self.accounts.launch_props(acc)
        prep = launch_flow.prepare(inst, version, memory_mb=memory_mb or int(CONFIG.get("memory_mb") or 4096))
        cmd, _n, _v, _g = build_launch_command(
            inst, version, props, java_exe,
            memory_mb=prep["memory_mb"],
            extra_game_args=prep["extra_game_args"],
            extra_jvm_args=prep["jvm_args"],
            game_directory=prep["game_dir"],
        )
        return " ".join(cmd)

    # ==================================================================
    # 新增 API：首次运行智能推荐
    # ==================================================================

    def get_smart_recommendation(self) -> dict:
        from mclauncher.sysinfo import get_smart_recommendation
        return get_smart_recommendation()

    def test_ai_connection(self, settings: dict | None = None) -> str:
        """试连 AI。传 settings 就用它，让设置页能测「还没保存的值」而不必先落盘。"""
        from mclauncher.ai.client import test_connection
        return test_connection(settings if settings is not None else self.get_settings())

    def ai_list_chats(self) -> dict:
        from mclauncher.ai import store as chat_store
        out = self._localize_chats(chat_store.load())
        # 前端重进页面 / 刷新时靠这一位把「发送 / 停止」按钮对回后端的真实状态：
        # 桥进程重启、事件漏掉一帖，前端自己那份 busy 就永远卡在上一回合。
        out["busy"] = bool(self._ai_busy)
        # 正在等回答的确认 / 选择卡（没有就是 None）：SSE 断线期间丢掉的 ai.confirm /
        # ai.ask 靠这一位补画，否则用户只看到「卡住」，内核却在等他点。
        out["pending_card"] = self.ai_pending_card()
        return out

    def ai_pending_card(self) -> dict | None:
        """当前正在等用户回答的卡片：{kind: confirm|ask, …原事件字段, chat_id}；没有则 None。"""
        card = getattr(self, "_ai_pending_card", None)
        if not card or not self._ai_busy:
            return None
        return dict(card)

    def list_tasks(self) -> dict:
        """断线对账：正在跑的任务与最近完成的结果。

        SSE 重连窗口里丢掉的 finished 事件没有别的地方能补回来——前端重连后拿这一份
        把「运行中」的行对回真实状态。finished 只保留最近几十条（见 _emit 的裁剪）。
        """
        with self._lock:
            running = [{"task_id": tid, "title": self._titles.get(tid, tid)}
                       for tid in list(self._workers)]
        finished = [{"task_id": tid, "success": bool(ok), "message": str(msg or "")}
                    for tid, (ok, msg) in list(self._task_results.items())]
        return {"running": running, "finished": finished}

    def ai_new_chat(self) -> dict:
        from mclauncher.ai import store as chat_store
        data = chat_store.load()
        chat_store.new_chat(data)
        return self._localize_chats(data)

    def ai_delete_chat(self, chat_id: str) -> dict:
        from mclauncher.ai import store as chat_store
        data = chat_store.load()
        chat_store.delete_chat(data, chat_id)
        return self._localize_chats(data)

    def ai_set_active(self, chat_id: str) -> dict:
        from mclauncher.ai import store as chat_store
        data = chat_store.load()
        chat_store.set_active(data, chat_id)
        return self._localize_chats(data)

    def ai_rewind(self, chat_id: str = "") -> dict:
        """撤回最近一轮：对话截回上一轮之前，该轮写/删改动用检查点还原。

        与 Qt 端 app/pages/ai_page.py 的 _rewind 走同一个 rewind.rewind_last_round，
        两端行为一致。busy 时不给撤（回合还在跑，截了也会被结果覆盖）。
        """
        from mclauncher.ai import rewind as ai_rewind_mod
        if self._ai_busy:
            return {"ok": False, "truncated": False, "restored_files": 0,
                    "restored_bytes": 0, "rollbackable": False, "disk_changed": False,
                    "message": tr("回合还在跑，先停止再撤回")}
        cid = str(chat_id or "").strip()
        if not cid:
            from mclauncher.ai import store as chat_store
            data = chat_store.load()
            cid = str(data.get("active_id") or "")
        return ai_rewind_mod.rewind_last_round(cid)

    @staticmethod
    def _localize_chats(data: dict) -> dict:
        """对话列表吐给前端前把默认标题「新对话」翻掉。

        只改返回的这一份拷贝，不动 store 里存的原文：`ai/store.py` 自动起标题时还按
        原文「新对话」认「这条还没起过名」，翻进文件里就认不出来了。
        """
        if not isinstance(data, dict):
            return data
        chats = []
        for chat in data.get("chats") or []:
            if isinstance(chat, dict) and chat.get("title") in ("", "新对话"):  # i18n:ignore 存盘原文，只翻出口
                chat = dict(chat)
                chat["title"] = tr("新对话")
            chats.append(chat)
        out = dict(data)
        out["chats"] = chats
        return out

    def ai_stop(self) -> dict:
        # 回执带上「当时有没有回合在跑」：没有的话前端就别再等 ai.fail 来复位按钮——
        # 那一帖不会来（前端的 busy 是脱节的旧状态），得拿这一位当场复位。
        was_busy = bool(self._ai_busy)
        self._ai_cancel = True
        http = self._ai_http
        if http:
            try:
                http.abort()
            except Exception:
                pass
        self.ai_confirm(False)
        self.ai_answer(None)
        return {"ok": True, "busy": was_busy}

    def ai_confirm(self, ok: bool = False, always: bool = False,
                   scope: str = "instance") -> dict:
        """回答确认卡。always=True 即「始终允许」：按 scope（instance / global）记成规则，
        内核收到 Rule 会自己落盘；卡片上下文来自 confirm_fn 那一刻存下的 name / args。"""
        answer: object = bool(ok)
        ctx = getattr(self, "_ai_confirm_ctx", None)
        if ok and always and ctx:
            from mclauncher.ai.permission import (
                SCOPE_GLOBAL, SCOPE_INSTANCE, Behavior, Rule, rule_content_from_input)
            name, args = ctx
            answer = Rule(name, rule_content_from_input(args or {}), Behavior.ALLOW,
                          scope=SCOPE_GLOBAL if scope == SCOPE_GLOBAL else SCOPE_INSTANCE)
        self._ai_confirm_ok = answer
        self._ai_confirm_ev.set()
        return {"ok": True}

    # ---- 权限规则（供 WPF 权限面板；Qt 端进程内直调 permission.*）----
    def ai_permission_rules(self) -> list:
        from mclauncher.ai.permission import list_stored_rules
        return list_stored_rules()

    def ai_permission_rule_add(self, tool: str, behavior: str = "allow",
                               content: str = "", instance: str = "") -> list:
        from mclauncher.ai.permission import Behavior, Rule, append_rule, list_stored_rules
        from mclauncher.ai.tools import TOOL_META
        if tool not in TOOL_META:
            raise ValueError(tr("未知工具：{0}").format(tool))
        try:
            beh = Behavior(str(behavior or "allow"))
        except ValueError:
            raise ValueError(tr("未知行为：{0}").format(behavior)) from None
        append_rule(Rule(tool, (content or "").strip() or None, beh), instance or None)
        return list_stored_rules()

    def ai_permission_rule_remove(self, key: str, instance: str = "") -> list:
        from mclauncher.ai.permission import list_stored_rules, remove_rule
        remove_rule(key, instance=instance or "")
        return list_stored_rules()

    def ai_answer(self, result=None) -> dict:
        self._ai_ask_result = result
        self._ai_ask_ev.set()
        return {"ok": True}

    def ai_send(self, text: str, chat_id: str = "", launch: dict | None = None,
                context: str | None = None) -> dict:
        # 检查-置位放在同一把锁里：连点两次「发送」不能并发起两条 run
        with self._ai_lock:
            if self._ai_busy:
                return {"ok": False, "message": tr("上一条还在处理")}
            self._ai_busy = True
            self._ai_cancel = False
            self._ai_steer = []
        self._ui_launch = dict(launch or {})
        t = threading.Thread(
            target=self._ai_run, args=(text, chat_id, context), daemon=True, name="ai-send")
        t.start()
        return {"ok": True, "started": True}

    def ai_steer(self, text: str) -> dict:
        """跑动中插一句（steering）：下一轮模型请求前被采纳，不用等这回合结束。

        没在跑就原样退回 ok=False，前端拿它当普通 ai_send 发。
        """
        text = str(text or "").strip()
        if not text:
            return {"ok": False, "message": tr("内容为空")}
        with self._ai_lock:
            if not self._ai_busy:
                return {"ok": False, "message": tr("当前没有在跑的回合")}
            self._ai_steer.append(text)
        return {"ok": True, "queued": len(self._ai_steer)}

    def _ai_run(self, text: str, chat_id: str, context: str | None = None):
        from mclauncher.ai import store as chat_store
        from mclauncher.ai.agent import AgentCancelled, run_agent
        from mclauncher.ai.client import AIClientError, HttpCancel

        data = chat_store.load()
        if chat_id:
            chat_store.set_active(data, chat_id)
        # 这一回合从头到尾都属于开跑时的这条对话。用户中途切走 / 新建 / 删除对话，
        # 结果仍写回这一条，事件也带着它的 id，前端才分得清「这帖是不是我正看着的对话」。
        run_cid = str(data.get("active_id") or "")
        chat = chat_store.get_chat(data, run_cid) or {}
        history = chat_store.api_messages(chat.get("messages") or [])
        http = HttpCancel()
        self._ai_http = http
        notes = []
        buf = []
        last = [0.0]
        delayed = [None]

        def flush_delta(force=False):
            if not buf:
                return
            now = time.monotonic()
            if not force and now - last[0] < 0.033:
                if delayed[0] is None:
                    t = threading.Timer(0.033, lambda: flush_delta(True))
                    t.daemon = True
                    delayed[0] = t
                    t.start()
                return
            if delayed[0] is not None:
                delayed[0].cancel()
                delayed[0] = None
            last[0] = now
            # 带 chat_id：前端切换对话后，靠它把旧回合的流式文本分流掉，
            # 不写进正看着的新对话
            self._bus.emit("ai.delta", {"text": "".join(buf), "chat_id": run_cid})
            buf.clear()

        def on_delta(piece):
            if piece:
                buf.append(piece)
                flush_delta()

        def on_status(kind, payload):
            payload = payload or {}
            if kind == "tool_done" and payload.get("label"):
                notes.append(payload.get("label"))
            # 带 chat_id：ai.done / ai.fail 之外的中间事件也要分得清归属，
            # 前端 abandon 超时后旧回合的工具行才不会画进新对话
            self._bus.emit("ai.status", {"kind": kind, "chat_id": run_cid, **payload})

        def cancelled():
            return self._ai_cancel

        def _wait_card(ev: threading.Event) -> bool:
            """等确认 / 选择卡片，每 0.2s 看一眼停止位。

            ai_stop 是先 set 事件再由内核走到这里的：若这里先 clear 再无限 wait，
            停止就落空，卡片挂在停止之后弹出，用户不点就一直 busy。
            返回 False = 被停止。
            """
            while not ev.wait(0.2):
                if self._ai_cancel:
                    return False
            return not self._ai_cancel

        # 四参签名：内核 _call_confirm 靠参数个数识别新接口，把判权原因带给前端
        def confirm_fn(name, args, label, reason=""):
            if self._ai_cancel:
                return False
            self._ai_confirm_ev.clear()
            # 记下这张卡对应的工具与参数：前端点「始终允许」时 ai_confirm 靠它拼 Rule
            self._ai_confirm_ctx = (name, dict(args or {}))
            from mclauncher.ai.permission import rule_content_from_input
            # 变更预览与 Qt 端同一函数：两端确认卡渲染同一份 lines，信息量一致
            try:
                from mclauncher.ai import preview as ai_preview
                pv = ai_preview.change_preview(self, name, args or {})
            except Exception:
                pv = None
            payload = {"name": name, "args": args or {}, "label": label, "reason": reason or "",
                       "rule_content": rule_content_from_input(args or {}) or "",
                       "preview": pv or {},
                       "chat_id": run_cid}
            # 卡片在 SSE 断线窗口里发出去就丢了，前端看不到卡、内核却在这儿等；
            # 存一份「待回答的卡」，前端重连后拿 ai_pending_card / ai_list_chats 对账补画。
            self._ai_pending_card = {"kind": "confirm", **payload}
            self._bus.emit("ai.confirm", payload)
            try:
                if not _wait_card(self._ai_confirm_ev):
                    return False
                return self._ai_confirm_ok
            finally:
                self._ai_pending_card = None

        def ask_fn(questions, title):
            if self._ai_cancel:
                return None
            self._ai_ask_ev.clear()
            self._ai_ask_result = None
            payload = {"questions": questions or [], "title": title or "", "chat_id": run_cid}
            self._ai_pending_card = {"kind": "ask", **payload}
            self._bus.emit("ai.ask", payload)
            try:
                if not _wait_card(self._ai_ask_ev):
                    return None
                return self._ai_ask_result
            finally:
                self._ai_pending_card = None

        def drain_inputs():
            with self._ai_lock:
                out = list(self._ai_steer)
                self._ai_steer = []
            return out

        def _turn_compact_and_trajectory(reply) -> tuple:
            """(压缩摘要消息, 工具轨迹)。摘要（id=compact_*）入库且插在用户这句
            之前：下一轮 _trim_history 在被裁段里找到它就直接复用，不再每回合
            重新摘要；autocompact 的摘要同样靠它活过回合结束。"""
            compacts, rows = [], []
            for m in (getattr(reply, "turn_messages", None) or []):
                if not isinstance(m, dict):
                    continue
                role = m.get("role")
                if role == "tool" or (role == "assistant" and m.get("tool_calls")):
                    rows.append(dict(m))
                elif role == "user" and str(m.get("id") or "").startswith("compact_"):
                    compacts.append(dict(m))
            return compacts, rows

        def release():
            # 先放开 busy 再发收尾事件：前端收到 ai.done / ai.fail 往往立刻回查
            # ai_list_chats 的 busy 位或补发排队的下一句，这里若还挂着 busy，
            # 那一发就被「上一条还在处理」顶回去，按钮也会被对回「忙」。
            self._ai_busy = False
            self._ai_http = None

        def persist(new_messages: list) -> dict:
            """把本回合新增的几条追加进所属对话再落盘。

            落盘前重新读一遍：跑的这几十秒里用户可能已经切换 / 新建 / 删除了对话，
            拿开跑前那份旧快照去 save 会把这些改动整份盖掉（新建的对话直接消失、
            激活项跳回旧对话）。只追加、不截 24 条：UI 侧上限由 store 的 MAX_MESSAGES
            管，模型侧上限由 agent 的 MAX_HISTORY 管，这里再截一刀等于把工具轨迹全丢掉。
            对话被删了就只报事件不落盘。
            """
            fresh = chat_store.load()
            cur = chat_store.get_chat(fresh, run_cid)
            if cur is not None:
                chat_store.upsert_messages(
                    fresh, run_cid, list(cur.get("messages") or []) + list(new_messages))
            return fresh

        def fail(text_shown: str, stopped: bool):
            flush_delta(True)
            release()
            # 失败也把用户这句和出错原因存上，否则重开程序这一问就凭空消失了
            try:
                persist([{"role": "user", "content": text},
                         {"role": "error", "content": text_shown}])
            except Exception:  # noqa: BLE001
                pass
            self._bus.emit("ai.fail", {"text": text_shown, "stopped": stopped, "chat_id": run_cid})

        # 事件日志按对话分文件（对齐 app/pages/ai_page.py）：以前桥不设 ai_session_id，
        # trace 全落 active.jsonl 一份，几条对话的轨迹搅在一起。
        settings = dict(self.get_settings())
        settings["ai_session_id"] = run_cid or "active"
        # 「交给 AI 修复」小窗带来的隐藏上下文（崩溃报告）：只进模型请求，
        # 不入库、不出现在对话历史；WPF 主 AI 页不传 context，行为不变
        if context:
            settings["ai_extra_context"] = str(context)
        try:
            reply = run_agent(
                self, settings, history, text,
                on_delta=on_delta, on_status=on_status,
                confirm_fn=confirm_fn, ask_fn=ask_fn, cancelled=cancelled,
                http_cancel=http, drain_inputs_fn=drain_inputs,
            )
            flush_delta(True)
            if self._ai_cancel:
                raise AgentCancelled()
            body = str(reply or "")
            if notes:
                extra = tr("（本轮：{0}）").format(tr("；").join(notes[:8]))
                if extra not in body:
                    body = (body + "\n\n" + extra).strip()
            # 「为什么停」的提示只给人看：正文里带着它入库，下一轮模型会读到自己上一句
            # 后面挂着「没有真的开始执行」，容易误判成要补动作。所以拆成独立字段 note
            # 存着（store 保留、api_messages 不喂给模型），前端渲染历史时再拼回去。
            note = _stop_note(reply)
            shown = (body + note) if note else body
            final = {"role": "assistant", "content": body}
            if note:
                final["note"] = note
            turn_compacts, turn_traj = _turn_compact_and_trajectory(reply)
            fresh = persist(turn_compacts + [{"role": "user", "content": text}]
                            + turn_traj + [final])
            release()
            # 3.4 本回合出了待办计划就随会话持久化，WPF 重开程序也能恢复
            try:
                plan = getattr(reply, "plan", None)
                if plan:
                    chat_store.set_plan(chat_store.load(), run_cid,
                                        {"turn_id": run_cid,
                                         "items": list(plan)})
            except Exception:
                pass
            self._bus.emit("ai.done", {
                "text": shown,
                "note": note,
                "store": fresh,
                "chat_id": run_cid,
                # AgentResult 是 str 子类，旧前端把整包当文本消费不受影响；
                # stop_reason 用 getattr 兜底，内核万一退化回纯 str 也不炸。
                "stop_reason": getattr(reply, "stop_reason", None) and reply.stop_reason.value,
                "detail": getattr(reply, "detail", ""),
                "pending_tasks": list(getattr(reply, "pending_tasks", []) or []),
                "plan": list(getattr(reply, "plan", []) or []),
                # 6.1 会话累计用量（WPF 等价展示的数据源）
                "usage": dict(getattr(reply, "usage", {}) or {}),
            })
        except AgentCancelled:
            fail(tr("已停止"), True)
        except AIClientError as exc:
            fail(str(exc), False)
        except Exception as exc:  # noqa: BLE001
            fail(str(exc), False)
        finally:
            if delayed[0] is not None:
                delayed[0].cancel()
                delayed[0] = None
            release()

    # ==================================================================
    # 补齐 app/backend.py 有、这边没有的公开能力
    #
    # tests/test_bridge_parity.py 开头那句是本节存在的理由：桥必须跟
    # app/backend.py 修得一样，否则同一批缺陷在 eziapp / WinUI / WPF 上原样存在。
    # 实现一律照搬同名方法，不另起炉灶——两边行为不一致比缺失更难查。
    #
    # 没有搬过来的两个及其原因（invalidate_instances 已随 get_instances 的 TTL 缓存一起补上）：
    #   call_async            形参 fn / on_ok / on_err 要的是 Python 可调用对象，
    #                         JSON 送不过去（与 start_task 同类，见决策 d-398）。
    #                         桥这边「后台跑一件事」由 start_task + 事件流承担。
    #   take_migration_report 读的是 Qt 启动时写下的 _migration_report；桥的启动
    #                         路径不跑那次单目录合并，永远只会返回 {}。
    # ==================================================================

    # ---------------- 内容导出 ----------------
    def default_export_dir(self) -> str:
        from mclauncher import content_export
        return str(content_export.default_export_dir())

    def remember_export_dir(self, path: str) -> str:
        from mclauncher import content_export
        return content_export.remember_export_dir(path)

    def export_content(self, kind: str, name: str, dest_dir: str = "",
                       version: str = "", instance: str = "") -> str:
        from mclauncher import content_export
        return content_export.export_one(
            self._instance(instance), kind, name, dest_dir, version)

    def export_contents(self, kind: str, names, dest_dir: str = "",
                        version: str = "", instance: str = "") -> dict:
        from mclauncher import content_export
        return content_export.export_many(
            self._instance(instance), kind, names, dest_dir, version)

    # ---------------- 游戏根目录 ----------------
    def game_root_name(self) -> str:
        """唯一游戏目录的名字。还需要「实例名」的旧接口一律拿它。"""
        from mclauncher.instances import root_name
        return root_name()

    def game_root_path(self) -> str:
        return str(self._instance().path)

    # ---------------- 存档安装目标 ----------------
    def get_saves_targets(self, instance: str = "") -> list[dict]:
        """世界安装目标：共享 saves + 开了存档隔离的版本各自目录。"""
        from mclauncher import version_settings as vs
        inst = self._instance(instance)
        rows = [{"label": tr("大锅饭（所有版本共用）"), "value": ""}]
        for vid in inst.installed_ids():
            iso = vs.load(inst, vid).get("isolation")
            if iso in (vs.ISOLATION_SAVES, vs.ISOLATION_ALL):
                rows.append({"label": f"{vid} · {tr('独立存档')}", "value": vid})
        return rows

    # ---------------- 版本隔离 ----------------
    def get_version_isolation(self, version: str) -> str:
        from mclauncher import version_settings as vs
        return vs.load(self._instance(), version).get("isolation") or vs.ISOLATION_NONE

    def set_version_isolation(self, version: str, mode: str, seed: bool = False) -> dict:
        """切「独立 / 大锅饭」。seed=True 会把共享池里的模组复制一份过去。"""
        from mclauncher import version_settings as vs
        out = vs.set_isolation(self._instance(), version, mode, seed=seed)
        self._emit("ui_changed", {})
        return out

    def toggle_version_isolation(self, version: str, isolated: bool, seed: bool = False) -> dict:
        from mclauncher import version_settings as vs
        mode = vs.ISOLATED_DEFAULT if isolated else vs.ISOLATION_NONE
        return self.set_version_isolation(version, mode, seed=seed)

    # ---------------- 版本管理页数据源 ----------------
    LOADER_TAGS = (
        ("neoforge", "NeoForge", "#D84B28"),
        ("fabric", "Fabric", "#7C5CD6"),
        ("quilt", "Quilt", "#C25BD6"),
        ("forge", "Forge", "#E8862E"),
        ("optifine", "OptiFine", "#2E9B6B"),
        ("liteloader", "LiteLoader", "#4C8BF5"),
    )

    @classmethod
    def loader_of(cls, version_id: str) -> tuple[str, str]:
        from mclauncher.i18n import tr
        low = str(version_id or "").lower()
        for token, label, color in cls.LOADER_TAGS:
            if token in low:
                return label, color
        return tr("原版"), "#8A9099"

    @staticmethod
    def _version_mc_id(inst, version_id: str) -> str:
        """版本 json 里的原版号。继承链上的 inheritsFrom 优先。"""
        data = inst.version_json(version_id) or {}
        return str(data.get("inheritsFrom") or data.get("id") or version_id)

    @staticmethod
    def _count_mods(folder) -> int:
        p = Path(folder)
        if not p.is_dir():
            return 0
        return sum(1 for f in p.iterdir()
                   if f.is_file() and f.name.lower().endswith(".jar"))

    def get_version_rows(self, include_hidden: bool = False) -> list[dict]:
        """版本管理页的数据源：一个版本一行，自带隔离状态与模组数。"""
        from mclauncher import version_settings as vs
        inst = self._instance()
        rows = []
        for vid in inst.installed_ids():
            settings = vs.load(inst, vid)
            hidden = bool(settings.get("hidden"))
            if hidden and not (include_hidden or CONFIG.get("show_hidden_versions")):
                continue
            isolated = vs.is_isolated(settings)
            mods_dir = vs.mods_dir(inst, vid, settings)
            label, color = self.loader_of(vid)
            rows.append({
                "id": vid,
                "loader": label,
                "loader_color": color,
                "mc": self._version_mc_id(inst, vid),
                "isolation": settings.get("isolation") or vs.ISOLATION_NONE,
                "isolation_label": tr(vs.ISOLATION_LABELS.get(
                    settings.get("isolation") or vs.ISOLATION_NONE, "")),
                "isolated": isolated,
                "mods": self._count_mods(mods_dir),
                "mods_dir": str(mods_dir),
                "hidden": hidden,
                "java": settings.get("java") or JAVA_AUTO,
                "memory_mb": settings.get("memory_mb") or 0,
            })
        return rows

    # ---------------- 任务标题归类 ----------------
    #: 这三类是交互流程，不进下载条也不计红点。
    _INTERACTIVE_TITLES = ("启动游戏", "微软登录", "皮肤站登录")  # i18n:ignore 任务标题前缀，WPF/WinUI 按原文比对

    @staticmethod
    def is_download_title(title: str) -> bool:
        """标题是不是「下载类」任务。

        任务标题一律按中文原文拼（`f"启动游戏 {version}"`），WPF / WinUI 也按原文
        前缀认它们，所以标题不翻。这里原文和译文各比一次：桥一旦切到 en，只比译文
        就会把「启动游戏 1.21」错算成下载任务。
        """
        t = str(title or "")
        return not any(t.startswith(k) or t.startswith(tr(k))
                       for k in BackendAPI._INTERACTIVE_TITLES)

    # ---------------- 壁纸历史与撤销 ----------------
    def _current_background(self) -> dict:
        return {"image": str(CONFIG.get("ui_background") or ""),
                "folder": str(CONFIG.get("ui_background_folder") or "")}

    def _after_background_change(self):
        """undo / reset 绕开了 save_settings，得自己补一次通知。

        app/backend.py 这里清的是它自己的 _settings_cache 再发 theme_changed 信号；
        桥没有那层缓存，对应动作就是往事件流上推一条 ui_changed，前端照样会重读。
        """
        self._emit("ui_changed", {})

    def background_history(self) -> list:
        """换下来的旧壁纸，最早在前、最新在后。"""
        from mclauncher.config import background_history as _bg_history
        return _bg_history()[0]

    def can_undo_background(self) -> bool:
        from mclauncher.config import background_history as _bg_history
        return bool(_bg_history()[0])

    def undo_background(self) -> dict:
        """退回上一组壁纸设置，返回 {image, folder}。没历史就原样返回当前值。

        单图和文件夹一起退：只退单图的话，文件夹还挂着轮播，界面上什么都不会变。
        """
        from mclauncher.config import background_history as _bg_history
        images, folders = _bg_history()
        if not images:
            return self._current_background()
        previous = {"image": images.pop(), "folder": folders.pop()}
        CONFIG.update({"ui_background_history": images,
                       "ui_background_folder_history": folders,
                       "ui_background": previous["image"],
                       "ui_background_folder": previous["folder"]})
        CONFIG.save()
        self._after_background_change()
        return previous

    def reset_background(self) -> dict:
        """回到出厂壁纸（纯色，连轮播文件夹一起清）。当前这组照样进历史栈。"""
        from mclauncher.config import DEFAULT_CONFIG
        from mclauncher.config import push_background_history as _push_bg_history
        default = {"image": str(DEFAULT_CONFIG.get("ui_background") or ""),
                   "folder": str(DEFAULT_CONFIG.get("ui_background_folder") or "")}
        current = self._current_background()
        updates = {"ui_background": default["image"],
                   "ui_background_folder": default["folder"]}
        if current != default:
            images, folders = _push_bg_history(current["image"], current["folder"])
            updates["ui_background_history"] = images
            updates["ui_background_folder_history"] = folders
        CONFIG.update(updates)
        CONFIG.save()
        self._after_background_change()
        return default
