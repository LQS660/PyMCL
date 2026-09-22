# -*- coding: utf-8 -*-
"""文件变更检查点：写/删工具执行前快照实际触及的路径，可按对话/回合回滚。

快照按 (chat_id, turn_id, seq) 记进 journal；备份内容按 sha256 寻址存盘，
回滚 = 逆序恢复 journal 里那段操作触及的每个路径（原来存在→写回原内容并
还原 mtime；原来不存在→删掉后来新建的）。只有显式按「目录」声明的快照
（如 delete_instance / install_* 的目标目录）才会在回滚时清掉该目录下
快照之后新出现的文件——文件级快照（如 write_mod_config）绝不碰父目录里
的其他文件，用户本次操作之外的文件一个字节都不动。

磁盘占用（可解释）：
- 备份根 cache/ai_checkpoints/<chat_id>/files/<sha256>.bin —— 内容寻址，
  同内容只存一份，跨操作/跨回合去重；
- journal cache/ai_checkpoints/<chat_id>/journal.json；
- begin_chat() 时清理：只留最近 KEEP_CHATS 个对话目录；单对话备份总量超过
  MAX_CHAT_BYTES 时从最旧的操作开始丢弃（这些操作标记为不可回滚）；
- 单次快照内容超 MAX_SNAPSHOT_BYTES → 这次不做内容快照，操作照常执行，
  但标记该回合不可回滚（调用方负责在 UI 上告警）。

检查点任何环节失败都不抛异常给调用方——快照失败绝不能阻断用户本来的操作。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import threading

from pathlib import Path

from mclauncher import utils

# 测试可覆盖；None = 默认 utils.ROOT/cache/ai_checkpoints
CHECKPOINTS_DIR = None

KEEP_CHATS = 20
# 单次快照的内容上限：超过就不做内容快照（delete_instance 可能是几个 GB）
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
# 单对话备份总量上限：超过从最旧的操作开始丢
MAX_CHAT_BYTES = 1024 * 1024 * 1024
# 目录快照最多登记的文件数（防百万小文件把 journal 撑爆）
MAX_DIR_FILES = 20000

_LOCK = threading.RLock()


def _root() -> Path:
    base = CHECKPOINTS_DIR if CHECKPOINTS_DIR is not None \
        else utils.ROOT / "cache" / "ai_checkpoints"
    return utils.ensure_dir(base)


def _chat_dir(chat_id: str) -> Path:
    safe = "".join(ch for ch in str(chat_id or "active") if ch.isalnum() or ch in "-_") or "active"
    return utils.ensure_dir(_root() / safe)


def _journal_path(chat_id: str) -> Path:
    return _chat_dir(chat_id) / "journal.json"


def _files_dir(chat_id: str) -> Path:
    return utils.ensure_dir(_chat_dir(chat_id) / "files")


def _load_journal(chat_id: str) -> list:
    data = utils.read_json(_journal_path(chat_id), None)
    return data if isinstance(data, list) else []


def _save_journal(chat_id: str, ops: list) -> None:
    utils.write_json(_journal_path(chat_id), ops)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iter_files(path: Path) -> tuple[list[Path], bool]:
    """列出 path（文件或目录）下的所有文件。目录递归；超过 MAX_DIR_FILES 时
    置 truncated=True——截断的目录清单绝不能当完整 known 集合用于回滚清扫。"""
    if path.is_file():
        return [path], False
    if not path.is_dir():
        return [], False
    out: list[Path] = []
    truncated = False
    for p in sorted(path.rglob("*")):
        if p.is_file():
            out.append(p)
            if len(out) >= MAX_DIR_FILES:
                truncated = True
                break
    return out, truncated


def _store_blob(chat_id: str, data: bytes, sha: str) -> bool:
    """备份内容落盘（内容寻址去重）。失败返回 False。"""
    try:
        d = _files_dir(chat_id)
        target = d / f"{sha}.bin"
        if not target.exists():
            tmp = d / f".tmp-{sha[:12]}-{datetime.datetime.now().timestamp()}"
            tmp.write_bytes(data)
            tmp.replace(target)
        return True
    except OSError:
        return False


def snapshot(chat_id: str, turn_id: str, paths: list) -> dict:
    """把 paths 的当前内容记进 journal，返回 {ok, seq, files, bytes, reason}。

    paths 里的目录按「目录范围」登记：回滚时会清掉该目录下快照之后新增的
    文件/子目录（install_* / delete_instance 用）；文件只登记文件本身。
    ok=False 表示这次没快照成（磁盘满 / 权限不足 / 内容超上限）：
    原操作照常进行，但这一轮不可回滚，调用方必须告警。
    """
    chat_id = str(chat_id or "active")
    try:
        with _LOCK:
            ops = _load_journal(chat_id)
            files: list[dict] = []
            dir_bases: list[str] = []
            total = 0
            for raw in paths or []:
                try:
                    rp = Path(raw).resolve()
                except OSError:
                    continue
                is_dir = rp.is_dir()
                if is_dir:
                    dir_bases.append(str(rp))
                if not is_dir and not rp.exists():
                    # 文件级快照也要登记「快照时不存在」：disable_mod 这类改名操作
                    # 会在快照后新建 .disabled 文件，回滚时必须删掉它
                    files.append({"path": str(rp), "sha256": "", "size": 0, "mtime": 0})
                    continue
                flist, truncated = _iter_files(rp)
                if truncated:
                    # 截断的目录清单缺了 20000 名之后的老文件，回滚清扫会把它们
                    # 当「新增文件」误删——宁可整轮标记不可回滚
                    _gc_blobs(chat_id, ops)
                    return {"ok": False, "seq": len(ops), "files": 0, "bytes": 0,
                            "reason": f"目录文件数超过 {MAX_DIR_FILES}，本轮不可回滚"}
                for f in flist:
                    try:
                        if not f.is_file():
                            continue
                        data = f.read_bytes()
                    except OSError:
                        _gc_blobs(chat_id, ops)
                        return {"ok": False, "seq": len(ops), "files": 0, "bytes": 0,
                                "reason": f"无法读取 {f}"}
                    sha = _sha256(data)
                    if not _store_blob(chat_id, data, sha):
                        _gc_blobs(chat_id, ops)
                        return {"ok": False, "seq": len(ops), "files": 0, "bytes": 0,
                                "reason": "检查点写入失败（磁盘满或权限不足）"}
                    total += len(data)
                    files.append({"path": str(f), "sha256": sha,
                                  "size": len(data), "mtime": f.stat().st_mtime})
                    if total > MAX_SNAPSHOT_BYTES:
                        _gc_blobs(chat_id, ops)
                        return {"ok": False, "seq": len(ops), "files": 0, "bytes": 0,
                                "reason": "变更体积超过检查点上限"}
            seq = len(ops)
            if files or dir_bases:
                ops.append({
                    "seq": seq,
                    "turn_id": str(turn_id or ""),
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "files": files,
                    "dirs": dir_bases,
                    "bytes": total,
                })
                _save_journal(chat_id, ops)
            return {"ok": True, "seq": seq, "files": len(files), "bytes": total,
                    "reason": ""}
    except Exception:  # noqa: BLE001
        return {"ok": False, "seq": -1, "files": 0, "bytes": 0,
                "reason": "检查点写入失败"}


def _restore_file(chat_id: str, entry: dict) -> None:
    p = Path(entry["path"])
    blob = _files_dir(chat_id) / f"{entry['sha256']}.bin"
    data = blob.read_bytes()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    try:
        mtime = entry.get("mtime") or 0
        if mtime > 0:
            os.utime(p, (mtime, mtime))
    except (OSError, ValueError):
        pass


def _remove_file(path: str) -> bool:
    """删掉回滚目标。快照时不存在、后来出现的目录（如新实例的 mods/）整树删除。
    成功返回 True；失败（占用/权限）返回 False，由调用方计入 failures。"""
    try:
        p = Path(path)
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
            return True
        p.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _sweep_new_entries(base: str, known_files: set, known_dirs: set) -> None:
    """把目录 base 下快照之后新出现的文件/子目录清掉（只限按目录声明的范围）。"""
    root = Path(base)
    if not root.is_dir():
        return
    try:
        for p in sorted(root.rglob("*"), reverse=True):
            sp = str(p)
            if p.is_file():
                if sp not in known_files:
                    _remove_file(sp)
            elif p.is_dir():
                if sp not in known_dirs:
                    shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _apply_op(chat_id: str, op: dict) -> int:
    """恢复一个操作，返回失败条目数（ghost 删除失败 / blob 读写失败都算）。"""
    files = op.get("files") or []
    known_files = {f["path"] for f in files}
    known_dirs = {str(Path(f["path"]).parent) for f in files if f.get("sha256")}
    failures = 0
    for d in op.get("dirs") or []:
        _sweep_new_entries(d, known_files, known_dirs)
    for entry in files:
        if not entry.get("sha256"):
            # 快照时不存在：回滚 = 删掉后来出现的它（可能是目录，整树删）
            if not _remove_file(entry["path"]):
                failures += 1
            continue
        try:
            _restore_file(chat_id, entry)
        except (OSError, KeyError, ValueError):
            failures += 1
    return failures


def rollback(chat_id: str, turn_id: str = "", all_ops: bool = False) -> dict:
    """回滚一个回合（或全部）写操作。返回 {ok, restored_files, restored_bytes}。

    turn_id 为空且 all_ops=False 时回滚 journal 里最近一个有操作的回合——
    即「撤回最近一轮对话」的语义。
    """
    chat_id = str(chat_id or "active")
    with _LOCK:
        ops = _load_journal(chat_id)
        if not ops:
            return {"ok": True, "restored_files": 0, "restored_bytes": 0}
        if all_ops:
            target_seqs = {op.get("seq") for op in ops}
        elif turn_id:
            target_seqs = {op.get("seq") for op in ops
                           if op.get("turn_id") == str(turn_id)}
        else:
            last_turn = ops[-1].get("turn_id") or ""
            target_seqs = {op.get("seq") for op in ops
                           if op.get("turn_id") == last_turn}
        if not target_seqs:
            return {"ok": True, "restored_files": 0, "restored_bytes": 0}
        targets = [op for op in ops if op.get("seq") in target_seqs]
        keep = [op for op in ops if op.get("seq") not in target_seqs]
        restored = 0
        restored_bytes = 0
        failures = 0
        failed_ops: list = []
        for op in sorted(targets, key=lambda o: o.get("seq", 0), reverse=True):
            try:
                op_fails = _apply_op(chat_id, op)
                failures += op_fails
                if op_fails:
                    # 恢复不完整的操作保留在 journal 里：恢复是幂等的（同内容重写、
                    # ghost 删除可重试），删掉记录会让失败轮永久失去重试机会
                    failed_ops.append(op)
                else:
                    restored += len(op.get("files") or [])
                    restored_bytes += int(op.get("bytes") or 0)
            except Exception:  # noqa: BLE001
                failures += 1
                failed_ops.append(op)
        keep = sorted(keep + failed_ops, key=lambda o: o.get("seq", 0))
        _save_journal(chat_id, keep)
        # 回滚后清掉不再被引用的 blob，省磁盘
        _gc_blobs(chat_id, keep)
        return {"ok": failures == 0, "restored_files": restored,
                "restored_bytes": restored_bytes, "failures": failures}


def _gc_blobs(chat_id: str, ops: list) -> None:
    live = {f["sha256"] for op in ops for f in (op.get("files") or [])}
    try:
        for blob in _files_dir(chat_id).glob("*.bin"):
            if blob.stem not in live:
                blob.unlink(missing_ok=True)
    except OSError:
        pass


def last_turn_id(chat_id: str) -> str:
    """journal 里最近一个有写操作的回合 id（没有则空串）。"""
    ops = _load_journal(str(chat_id or "active"))
    return str(ops[-1].get("turn_id") or "") if ops else ""


def turn_has_ops(chat_id: str, turn_id: str) -> bool:
    """某个回合在 journal 里有没有写操作记录。"""
    tid = str(turn_id or "")
    return bool(tid) and any(op.get("turn_id") == tid
                             for op in _load_journal(str(chat_id or "active")))


def usage(chat_id: str) -> dict:
    """一个对话的检查点占用：{ops, files, bytes, rollbackable}。"""
    ops = _load_journal(str(chat_id or "active"))
    n_files = sum(len(op.get("files") or []) for op in ops)
    n_bytes = sum(int(op.get("bytes") or 0) for op in ops)
    return {"ops": len(ops), "files": n_files, "bytes": n_bytes,
            "rollbackable": bool(ops)}


def begin_chat(chat_id: str) -> None:
    """会话开始时清一次：老对话目录、超量的最旧操作。任何失败都吞掉。"""
    try:
        chat_id = str(chat_id or "active")
        with _LOCK:
            # 单对话超量：从最旧的操作开始丢
            ops = _load_journal(chat_id)
            total = sum(int(op.get("bytes") or 0) for op in ops)
            keep: list = []
            for op in reversed(ops):
                if total > MAX_CHAT_BYTES:
                    total -= int(op.get("bytes") or 0)
                    continue
                keep.insert(0, op)
            if len(keep) != len(ops):
                _save_journal(chat_id, keep)
                _gc_blobs(chat_id, keep)
            # 老对话目录
            root = _root()
            dirs = [d for d in root.iterdir() if d.is_dir()]
            dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            for d in dirs[KEEP_CHATS:]:
                shutil.rmtree(d, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
