# -*- coding: utf-8 -*-
"""补全 / 修复已装版本：缺文件或校验失败就重下。"""
from __future__ import annotations

from .installer import Installer, InstallError


def repair(installer: Installer, version_id: str) -> str:
    version_id = (version_id or "").strip()
    if not version_id:
        raise InstallError("请选择要修复的版本")
    local = installer.instance.version_json(version_id)
    if not local:
        raise InstallError(f"版本 {version_id} 未安装")
    installer._note(f"修复 {version_id}：校验并补全缺失文件")
    installer._install_json(version_id, local, force=False)
    return f"已修复 {version_id}"
