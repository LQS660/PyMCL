# -*- coding: utf-8 -*-
"""资源包 / 光影包：搜索与下载。

数据源与 PCL 相同，不自造直链：
- 搜索/版本：Modrinth v2、CurseForge v1（官方 + MCIM/BMCLAPI）
- 文件：Modrinth CDN（先 MCIM 再官方）、CurseForge ForgeCDN / 官方 download
"""
import json
import re
import shutil
from pathlib import Path

from . import catalog, utils
from .downloader import DownloadManager
from .instances import Instance
from .mods import (
    CF_CLASS_DATAPACK,
    CF_CLASS_RESOURCEPACK,
    CF_CLASS_SHADER,
    MODRINTH_API,
    ModError,
    _primary_file,
    cf_detail,
    cf_files,
    cf_mod_download_urls,
    detect_mc_version,
    list_versions,
    mirror_modrinth_url,
    modrinth_download_urls,
    search_curseforge,
)

PACK_RESOURCE = "resourcepack"
PACK_SHADER = "shader"
PACK_DATAPACK = "datapack"

_KIND_LABEL = {
    PACK_RESOURCE: "资源包",
    PACK_SHADER: "光影包",
    PACK_DATAPACK: "数据包",
}
_KIND_FOLDER = {
    PACK_RESOURCE: "resourcepacks",
    PACK_SHADER: "shaderpacks",
    PACK_DATAPACK: "datapacks",
}
_KIND_MR_TYPE = {
    PACK_RESOURCE: "resourcepack",
    PACK_SHADER: "shader",
    PACK_DATAPACK: "datapack",
}
_KIND_CF_CLASS = {
    PACK_RESOURCE: CF_CLASS_RESOURCEPACK,
    PACK_SHADER: CF_CLASS_SHADER,
    PACK_DATAPACK: CF_CLASS_DATAPACK,
}
_MR_PATH = {
    PACK_RESOURCE: "resourcepack",
    PACK_SHADER: "shader",
    PACK_DATAPACK: "datapack",
}
_CF_PATH = {
    PACK_RESOURCE: "texture-packs",
    PACK_SHADER: "shaders",
    PACK_DATAPACK: "data-packs",
}

_MR_URL_RE = re.compile(
    r"modrinth\.com/(resourcepack|shader|resource-pack|shaders|datapack)/([^/?#]+)",
    re.I,
)
_CF_URL_RE = re.compile(
    r"curseforge\.com/minecraft/(texture-packs|shaders|customization|data-packs)/([^/?#]+)",
    re.I,
)


class PackError(Exception):
    pass


def _kind(kind) -> str:
    k = (kind or PACK_RESOURCE).strip().lower()
    if k in ("resource", "resourcepacks", "texture", "texturepack", "材质", "材质包"):
        return PACK_RESOURCE
    if k in ("shader", "shaders", "shaderpack", "shaderpacks", "光影", "光影包"):
        return PACK_SHADER
    if k in ("datapack", "datapacks", "data-pack", "数据包"):
        return PACK_DATAPACK
    if k not in (PACK_RESOURCE, PACK_SHADER, PACK_DATAPACK):
        raise PackError(f"未知资源类型: {kind}")
    return k


def kind_label(kind) -> str:
    return _KIND_LABEL[_kind(kind)]


def dest_dir(instance: Instance, kind) -> Path:
    folder = _KIND_FOLDER[_kind(kind)]
    path = instance.path / folder
    utils.ensure_dir(path)
    return path


def _mr_hit(h, source="modrinth"):
    return {
        "source": source,
        "slug": h.get("slug"),
        "id": None,
        "title": h.get("title") or h.get("slug") or "?",
        "author": h.get("author") or "?",
        "downloads": h.get("downloads") or 0,
        "description": (h.get("description") or "")[:120],
    }


def search_modrinth_packs(dm: DownloadManager, query, kind, limit=30):
    """Modrinth 搜索资源包/光影包（空关键词按下载量，即平台热门）。"""
    k = _kind(kind)
    q = (query or "").strip()
    params = {
        "query": q,
        "facets": json.dumps([[f"project_type:{_KIND_MR_TYPE[k]}"]]),
        "limit": limit,
        "index": "relevance" if q else "downloads",
    }
    last_err = None
    from . import source
    for base in source.modrinth_api_bases():
        url = f"{base}/search"
        try:
            data = dm.fetch_json(url, params=params, timeout=12, expand=False)
            hits = data.get("hits") or []
            return [_mr_hit(h) for h in hits]
        except Exception as e:
            last_err = e
            utils.log.warning("Modrinth %s 搜索失败 %s: %s", k, url, e)
    raise PackError(f"搜索{kind_label(k)}失败: {last_err}")


def search_cf_packs(dm: DownloadManager, query, kind, limit=30, api_key=None):
    """CurseForge 搜索：classId 12=材质包，6552=光影（与 PCL/Prism 相同）。"""
    k = _kind(kind)
    hits = search_curseforge(
        dm, query=(query or "").strip() or None, limit=limit,
        api_key=api_key, class_id=_KIND_CF_CLASS[k],
    )
    out = []
    for h in hits:
        row = dict(h)
        row["description"] = row.pop("summary", "") or ""
        out.append(row)
    return out


def search_packs(dm: DownloadManager, query, kind, source="modrinth", limit=30, api_key=None):
    """统一搜索：中文别名先命中真实项目，再走当前源。空搜索 = 平台热门。"""
    k = _kind(kind)
    q = (query or "").strip()
    src = "curseforge" if (source or "").lower().startswith("curse") else "modrinth"
    if q:
        lookup = None
        if k == PACK_RESOURCE:
            lookup = catalog.lookup_resourcepack_alias
        elif k == PACK_SHADER:
            lookup = catalog.lookup_shader_alias
        elif k == PACK_DATAPACK:
            lookup = catalog.lookup_datapack_alias
        slug, title = lookup(q) if lookup else (None, None)
        if slug:
            try:
                data = dm.fetch_json(f"{MODRINTH_API}/project/{slug}", timeout=60)
                return [{
                    "source": "modrinth",
                    "slug": data.get("slug", slug),
                    "id": None,
                    "title": data.get("title") or title or slug,
                    "author": data.get("team") or "?",
                    "downloads": data.get("downloads") or 0,
                    "description": (data.get("description") or "")[:120],
                    "matched_alias": True,
                }]
            except Exception as e:
                utils.log.warning("别名 %s 查 Modrinth 失败: %s", slug, e)
    if src == "curseforge":
        try:
            return search_cf_packs(dm, q, k, limit=limit, api_key=api_key)
        except Exception as e:
            # 国内镜像经常不收光影 classId=6552；改走 Modrinth 真实项目，不编直链
            utils.log.warning("CurseForge %s 搜索不可用，回退 Modrinth: %s", k, e)
            hits = search_modrinth_packs(dm, q, k, limit=limit)
            for h in hits:
                extra = "CurseForge 暂不可用，已改用 Modrinth 同一项目"
                desc = (h.get("description") or "").strip()
                h["description"] = f"{extra} · {desc}" if desc else extra
            return hits
    return search_modrinth_packs(dm, q, k, limit=limit)


def _pick_pack_version(dm, slug, mc_version=None, kind=PACK_RESOURCE):
    """按 MC 版本挑文件；对不上就用最新版。光影优先 Iris/OptiFine 声明。"""
    versions = []
    if mc_version:
        try:
            versions = list_versions(dm, slug, game_version=mc_version)
        except ModError:
            versions = []
    if not versions:
        versions = list_versions(dm, slug)
    if not versions:
        raise PackError(f"{kind_label(kind)} {slug} 没有任何可下载版本")
    if _kind(kind) == PACK_SHADER:
        pref = []
        for v in versions:
            loaders = [str(x).lower() for x in (v.get("loaders") or [])]
            if any(x in loaders for x in ("iris", "optifine", "canvas", "vanilla", "sodium")):
                pref.append(v)
        if pref:
            return pref[0]
    return versions[0]


def install_modrinth_pack(dm: DownloadManager, slug, instance: Instance, kind,
                          mc_version=None, on_progress=None):
    """从 Modrinth 安装到 resourcepacks/ 或 shaderpacks/。"""
    k = _kind(kind)
    inst = instance
    inst.ensure_standard_dirs()
    if not mc_version:
        mc_version = detect_mc_version(inst)
    version = _pick_pack_version(dm, slug, mc_version, k)
    f = _primary_file(version)
    if not f or not f.get("url"):
        raise PackError(f"{kind_label(k)} {slug} 没有可下载文件")
    filename = f.get("filename") or f"{slug}.zip"
    dest = dest_dir(inst, k) / filename
    if on_progress:
        on_progress(f"下载{kind_label(k)} {filename}", 0, 1)
    urls = modrinth_download_urls(f["url"])
    dm.download(urls[0], dest, sha1=f.get("sha1"), size=f.get("size"),
                sha512=f.get("sha512"), urls=urls)
    return {
        "source": "modrinth",
        "slug": slug,
        "version": version.get("version_number"),
        "files": [dest.name],
        "folder": dest.parent.name,
    }


def install_cf_pack(dm: DownloadManager, addon_id, instance: Instance, kind,
                    mc_version=None, api_key=None, on_progress=None):
    """从 CurseForge 安装：ForgeCDN / 官方 API download（与模组同一套候选链）。"""
    k = _kind(kind)
    inst = instance
    inst.ensure_standard_dirs()
    if not mc_version:
        mc_version = detect_mc_version(inst)
    mod = cf_detail(dm, addon_id, api_key=api_key)
    files = mod.get("latestFiles") or []
    if not files:
        files = cf_files(dm, addon_id, api_key=api_key, page_size=100)
    if not files:
        raise PackError(f"{kind_label(k)}没有可下载文件")
    candidates = [f for f in files
                  if not mc_version or mc_version in (f.get("gameVersions") or [])]
    if not candidates:
        candidates = files
    f = candidates[0]
    file_id = f.get("id")
    if file_id is None:
        raise PackError("文件信息缺失")
    filename = f.get("fileName") or f"pack-{addon_id}-{file_id}.zip"
    download_url = f.get("downloadUrl")
    dest = dest_dir(inst, k) / filename
    last_err = None
    tried = set()
    url_sets = []
    if download_url:
        url_sets.append([download_url])
    url_sets.append(cf_mod_download_urls(addon_id, file_id, filename, download_url))
    url_sets.append(cf_mod_download_urls(addon_id, file_id, None, None))
    for urls in url_sets:
        for url in urls:
            if not url or url in tried:
                continue
            tried.add(url)
            try:
                if on_progress:
                    on_progress(f"下载{kind_label(k)} {filename}", 0, 1)
                dm.download(url, dest, timeout=900)
                return {
                    "source": "curseforge",
                    "title": mod.get("name"),
                    "files": [dest.name],
                    "folder": dest.parent.name,
                }
            except Exception as e:
                last_err = e
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
    raise PackError(f"CurseForge {kind_label(k)}下载失败: {last_err}")


def install_pack_from_source(dm: DownloadManager, source, instance: Instance, kind,
                             mc_version=None, on_progress=None, api_key=None):
    """slug / Modrinth 链接 / CurseForge 链接 / 本地 zip / 直链 zip。"""
    k = _kind(kind)
    inst = instance
    inst.ensure_standard_dirs()
    s = str(source).strip()
    if re.match(r"^https?://", s):
        m = _MR_URL_RE.search(s)
        if m:
            return install_modrinth_pack(
                dm, m.group(2), inst, k, mc_version=mc_version, on_progress=on_progress)
        m = _CF_URL_RE.search(s)
        if m:
            hits = search_curseforge(
                dm, slug=m.group(2), limit=5, class_id=_KIND_CF_CLASS[k], api_key=api_key)
            if not hits:
                raise PackError(f"找不到该 CurseForge {kind_label(k)}")
            return install_cf_pack(
                dm, hits[0]["id"], inst, k, mc_version=mc_version,
                api_key=api_key, on_progress=on_progress)
        if s.split("?")[0].lower().endswith(".zip"):
            name = s.split("/")[-1].split("?")[0] or "pack.zip"
            dest = dest_dir(inst, k) / name
            if on_progress:
                on_progress(f"下载{kind_label(k)} {name}", 0, 1)
            dm.download(s, dest, timeout=900)
            return {"source": "url", "files": [dest.name]}
        raise PackError("无法识别的链接：需要 Modrinth/CurseForge 项目页或 .zip 直链")
    p = Path(s)
    if p.is_file():
        if p.suffix.lower() != ".zip":
            raise PackError(f"本地{kind_label(k)}只支持 .zip")
        shutil.copy2(p, dest_dir(inst, k) / p.name)
        return {"source": "file", "files": [p.name]}
    return install_modrinth_pack(
        dm, s, inst, k, mc_version=mc_version, on_progress=on_progress)


def list_instance_packs(instance: Instance, kind):
    folder = dest_dir(instance, kind)
    items = []
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if p.name.startswith("."):
            continue
        if p.is_file() and p.suffix.lower() in (".zip", ".jar"):
            items.append(p)
        elif p.is_dir():
            items.append(p)
    return items


def delete_pack(instance: Instance, kind, filename: str):
    dest = dest_dir(instance, kind) / filename
    if dest.is_file():
        dest.unlink()
        return
    if dest.is_dir():
        utils.remove_tree(dest)
        return
    raise PackError(f"{kind_label(kind)}不存在: {filename}")
