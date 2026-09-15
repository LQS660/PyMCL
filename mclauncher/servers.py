# -*- coding: utf-8 -*-
"""服务器列表管理：增删改查、批量导入导出。

游戏只读实例目录下的 servers.dat（NBT），所以以 servers.dat 为准，
json 只当导入导出和旧数据迁移——只写 servers.json 的话界面能加能改，
进游戏多人列表却是空的。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import terracotta as terracotta_mod
from . import utils
from .instances import Instance

SERVER_FILE = "servers.json"
GAME_FILE = "servers.dat"


class ServerError(Exception):
    pass


def _server_path(instance: Instance) -> Path:
    return instance.path / SERVER_FILE


def _game_path(instance: Instance) -> Path:
    return instance.path / GAME_FILE


def _split_addr(ip: str, port=None) -> tuple[str, int]:
    text = str(ip or "").strip()
    if port not in (None, ""):
        try:
            parsed = int(port)
            if 1 <= parsed <= 65535:
                return text, parsed
        except (TypeError, ValueError):
            pass
    if ":" in text:
        host, last = text.rsplit(":", 1)
        if last.isdigit() and 1 <= int(last) <= 65535:
            return host, int(last)
    return text, 25565


def _read_json_rows(instance: Instance) -> list[dict]:
    data = utils.read_json(_server_path(instance), [])
    return data if isinstance(data, list) else []


def _read_servers(instance: Instance) -> list[dict]:
    dat_rows = terracotta_mod.read_game_servers(_game_path(instance))
    json_rows = _read_json_rows(instance)
    if dat_rows:
        extras = {}
        for row in json_rows:
            if not isinstance(row, dict):
                continue
            host, port = _split_addr(row.get("ip") or "", row.get("port"))
            extras[(host, port)] = row
        out = []
        for row in dat_rows:
            host, port = _split_addr(row.get("ip") or "")
            extra = extras.get((host, port), {})
            out.append({
                "name": row.get("name") or extra.get("name") or host,
                "ip": host,
                "port": port,
                "icon": extra.get("icon") or "",
                "description": extra.get("description") or "",
                "hidden": bool(row.get("hidden")),
            })
        return out
    return [row for row in json_rows if isinstance(row, dict)]


def _write_servers(instance: Instance, servers: list[dict]):
    utils.ensure_dir(instance.path)
    utils.write_json(_server_path(instance), servers)
    dat_rows = []
    for row in servers:
        if not isinstance(row, dict):
            continue
        host, port = _split_addr(row.get("ip") or "", row.get("port"))
        if not host:
            continue
        dat_rows.append({
            "name": row.get("name") or host,
            "ip": host if port == 25565 else f"{host}:{port}",
            "hidden": 1 if row.get("hidden") else 0,
        })
    terracotta_mod.write_game_servers(_game_path(instance), dat_rows)


def list_servers(instance: Instance) -> list[dict]:
    """返回该实例的所有服务器。优先读游戏会用的 servers.dat。

    每条记录：{name, ip, port, icon, description, hidden}
    """
    data = _read_servers(instance)
    if not isinstance(data, list):
        return []
    out = []
    for i, s in enumerate(data):
        if isinstance(s, dict):
            out.append(_normalize(s, i))
    return out


def _normalize(s: dict, index: int = 0) -> dict:
    host, port = _split_addr(s.get("ip") or "", s.get("port"))
    return {
        "name": str(s.get("name") or host or f"服务器 #{index + 1}"),
        "ip": host,
        "port": port,
        "icon": str(s.get("icon", "")),
        "description": str(s.get("description", "")),
        "hidden": bool(s.get("hidden", False)),
        "index": index,
    }


def get_server(instance: Instance, index: int) -> Optional[dict]:
    servers = list_servers(instance)
    for s in servers:
        if s["index"] == index:
            return s
    return None


def add_server(instance: Instance, name: str, ip: str, port: int = 25565,
               description: str = "", icon: str = "") -> dict:
    if not ip or not ip.strip():
        raise ServerError("服务器地址不能为空")
    port = int(port) if port else 25565
    if port < 1 or port > 65535:
        raise ServerError("端口号必须在 1-65535 之间")
    servers = _read_servers(instance)
    entry = {
        "name": (name or ip).strip(),
        "ip": ip.strip(),
        "port": port,
        "icon": icon,
        "description": description.strip(),
    }
    servers.append(entry)
    _write_servers(instance, servers)
    return _normalize(entry, len(servers) - 1)


def update_server(instance: Instance, index: int, **kwargs) -> dict:
    servers = _read_servers(instance)
    if not isinstance(servers, list) or index < 0 or index >= len(servers):
        raise ServerError(f"服务器索引 {index} 不存在")
    entry = servers[index]
    if not isinstance(entry, dict):
        raise ServerError(f"服务器数据损坏: {index}")
    if "name" in kwargs:
        entry["name"] = str(kwargs["name"]).strip()
    if "ip" in kwargs:
        ip = str(kwargs["ip"]).strip()
        if not ip:
            raise ServerError("服务器地址不能为空")
        entry["ip"] = ip
    if "port" in kwargs:
        port = int(kwargs["port"])
        if port < 1 or port > 65535:
            raise ServerError("端口号必须在 1-65535 之间")
        entry["port"] = port
    if "description" in kwargs:
        entry["description"] = str(kwargs["description"]).strip()
    if "icon" in kwargs:
        entry["icon"] = str(kwargs["icon"])
    if "hidden" in kwargs:
        entry["hidden"] = bool(kwargs["hidden"])
    _write_servers(instance, servers)
    return _normalize(entry, index)


def delete_server(instance: Instance, index: int):
    servers = _read_servers(instance)
    if not isinstance(servers, list) or index < 0 or index >= len(servers):
        raise ServerError(f"服务器索引 {index} 不存在")
    servers.pop(index)
    _write_servers(instance, servers)


def import_servers_txt(instance: Instance, text: str) -> int:
    """从纯文本批量导入服务器，每行格式：
    - 服务器名\t地址:端口
    - 地址:端口
    - 地址
    空行和 # 注释行被忽略。
    """
    imported = 0
    servers = _read_servers(instance)
    existing_addrs = set()
    for s in servers:
        if isinstance(s, dict):
            addr = f"{s.get('ip', '')}:{s.get('port', 25565)}"
            existing_addrs.add(addr)

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 尝试解析: 名字\t地址:端口 或 地址:端口 或 地址
        if "\t" in line:
            parts = line.split("\t", 1)
            name = parts[0].strip()
            addr_part = parts[1].strip()
        else:
            name = ""
            addr_part = line

        # 解析地址和端口
        if ":" in addr_part:
            ip, port_str = addr_part.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 25565
            ip = ip.strip()
        else:
            ip = addr_part
            port = 25565

        if not ip:
            continue
        addr = f"{ip}:{port}"
        if addr in existing_addrs:
            continue
        entry = {
            "name": name or ip,
            "ip": ip,
            "port": port,
        }
        servers.append(entry)
        existing_addrs.add(addr)
        imported += 1

    if imported > 0:
        _write_servers(instance, servers)
    return imported


def export_servers_txt(instance: Instance) -> str:
    """导出为纯文本格式。"""
    servers = list_servers(instance)
    lines = ["# PyMCL 服务器列表导出", f"# 共 {len(servers)} 个服务器", ""]
    for s in servers:
        name = s["name"]
        ip = s["ip"]
        port = s["port"]
        if name and name != ip:
            lines.append(f"{name}\t{ip}:{port}")
        else:
            lines.append(f"{ip}:{port}")
    return "\n".join(lines)


def import_servers_json(instance: Instance, data: list[dict]) -> int:
    """从 JSON 数组导入。"""
    if not isinstance(data, list):
        raise ServerError("导入数据必须是 JSON 数组")
    imported = 0
    servers = _read_servers(instance)
    existing_addrs = set()
    for s in servers:
        if isinstance(s, dict):
            existing_addrs.add(f"{s.get('ip', '')}:{s.get('port', 25565)}")

    for entry in data:
        if not isinstance(entry, dict):
            continue
        ip = str(entry.get("ip", "")).strip()
        if not ip:
            continue
        port = int(entry.get("port") or 25565)
        addr = f"{ip}:{port}"
        if addr in existing_addrs:
            continue
        servers.append(entry)
        existing_addrs.add(addr)
        imported += 1

    if imported > 0:
        _write_servers(instance, servers)
    return imported


def export_servers_json(instance: Instance) -> list[dict]:
    """导出为 JSON 数组。"""
    out = []
    for s in list_servers(instance):
        out.append({
            "name": s["name"],
            "ip": s["ip"],
            "port": s["port"],
            "description": s["description"],
            "icon": s["icon"],
        })
    return out