# -*- coding: utf-8 -*-
"""Download URL audit probe. Live HTTP only. Writes JSON to _audit_download_probe_out.json."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mclauncher import catalog
from mclauncher.config import CONFIG
from mclauncher.downloader import DownloadManager
from mclauncher.mods import _cf_file_cdn_url, cf_mod_download_urls
from mclauncher.source import rewrite_to_bmcl, rewrite_to_mcim
from mclauncher.terracotta import VERSION as TC_VER, classifier, download_urls as tc_download_urls

UA = "PyMCL-DownloadAudit/1.0"
TIMEOUT = (6, 18)
OUT = ROOT / "_audit_download_probe_out.json"

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Encoding": "identity"})


def _rec(name, url, **extra):
    rec = {"name": name, "url": url}
    rec.update(extra)
    return rec


def probe(url, method="GET", max_bytes=0, allow_redirects=True, headers=None, stream=False):
    t0 = time.perf_counter()
    try:
        hdrs = dict(headers or {})
        if method == "HEAD":
            r = session.head(url, timeout=TIMEOUT, allow_redirects=allow_redirects, headers=hdrs)
        else:
            r = session.get(
                url, timeout=TIMEOUT, allow_redirects=allow_redirects, headers=hdrs, stream=True
            )
        body = b""
        if method != "HEAD":
            if max_bytes:
                for chunk in r.iter_content(8192):
                    if not chunk:
                        continue
                    body += chunk
                    if len(body) >= max_bytes:
                        break
            else:
                body = r.content
            r.close()
        elapsed = round(time.perf_counter() - t0, 3)
        clen = r.headers.get("Content-Length")
        ctype = (r.headers.get("Content-Type") or "")[:80]
        loc = r.headers.get("Location") or ""
        final = getattr(r, "url", url)
        ok = 200 <= r.status_code < 400
        kind = "bin"
        if body[:1] in (b"{", b"["):
            kind = "json"
        elif body[:4] == b"PK\x03\x04":
            kind = "zip"
        elif body.lstrip()[:5].lower() in (b"<html", b"<!doc"):
            kind = "html"
        elif body[:2] == b"\x1f\x8b":
            kind = "gzip"
        return {
            "ok": ok,
            "status": r.status_code,
            "ms": elapsed,
            "bytes": len(body),
            "content_length": clen,
            "content_type": ctype,
            "final": final,
            "location": loc,
            "kind": kind,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "ms": round(time.perf_counter() - t0, 3),
            "bytes": 0,
            "content_length": None,
            "content_type": "",
            "final": url,
            "location": "",
            "kind": "",
            "error": f"{type(e).__name__}: {e}",
        }


def merge(name, url, result, **extra):
    rec = _rec(name, url, **extra)
    rec.update(result)
    return rec


results = {
    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    "endpoints": [],
    "rewrites": [],
    "downloads": [],
    "github_proxies": [],
    "terracotta": [],
    "catalog_slugs": [],
    "catalog_cf": [],
    "code_bugs": [],
    "errors": [],
}

# ---------- code signature ----------
try:
    sig = str(inspect.signature(DownloadManager.download))
    has_expand = "expand" in inspect.signature(DownloadManager.download).parameters
    results["code_bugs"].append({
        "id": "terracotta_expand_kwarg",
        "file": "mclauncher/terracotta.py:477",
        "detail": "install() 调用 dm.download(..., expand=False)",
        "download_signature": sig,
        "has_expand_param": has_expand,
        "would_typeerror": not has_expand,
    })
except Exception as e:
    results["errors"].append(f"inspect download: {e}")

# ---------- endpoint probes ----------
ENDPOINTS = [
    ("mojang_manifest_v2", "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", 4096),
    ("mojang_legacy_manifest", "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json", 4096),
    ("bmcl_manifest_v2", "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json", 4096),
    ("java_runtime_piston", "https://piston-meta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json", 4096),
    ("java_runtime_legacy", "https://launchermeta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json", 4096),
    ("java_runtime_bmcl", "https://bmclapi2.bangbang93.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json", 4096),
    ("adoptium_jre21_win_x64", "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse", 64),
    ("fabric_meta", "https://meta.fabricmc.net/v2/versions/loader/1.20.1", 2048),
    ("fabric_meta_bmcl", "https://bmclapi2.bangbang93.com/fabric-meta/v2/versions/loader/1.20.1", 2048),
    ("quilt_meta", "https://meta.quiltmc.org/v3/versions/loader/1.20.1", 2048),
    ("quilt_meta_bmcl", "https://bmclapi2.bangbang93.com/quilt-meta/v3/versions/loader/1.20.1", 2048),
    ("forge_maven_meta", "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml", 2048),
    ("forge_maven_bmcl", "https://bmclapi2.bangbang93.com/maven/net/minecraftforge/forge/maven-metadata.xml", 2048),
    ("bmcl_forge_list_1_20_1", "https://bmclapi2.bangbang93.com/forge/minecraft/1.20.1", 2048),
    ("neoforge_maven_meta", "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml", 2048),
    ("neoforge_maven_bmcl", "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/maven-metadata.xml", 2048),
    ("modrinth_api", "https://api.modrinth.com/v2/project/sodium", 1024),
    ("mcim_modrinth_api", "https://mod.mcimirror.top/modrinth/v2/project/sodium", 1024),
    ("cf_official_jei", "https://api.curseforge.com/v1/mods/238222", 1024),
    ("mcim_cf_jei", "https://mod.mcimirror.top/curseforge/v1/mods/238222", 1024),
    ("bmcl_cf_jei", "https://bmclapi2.bangbang93.com/curseforge/v1/mods/238222", 1024),
    ("cf_web_api", "https://www.curseforge.com/api/v1/mods/238222", 512),
    ("hmcl_terracotta_json", "https://raw.githubusercontent.com/HMCL-dev/HMCL/main/HMCL/src/main/resources/assets/terracotta.json", 4096),
    ("terracotta_nodes", "https://terracotta.glavo.site/nodes", 2048),
    ("terracotta_custom_node", "https://terracotta.glavo.site/acebc7d8-1208-47fd-b212-d03ac49e36e0", 512),
    ("etnode1", "https://etnode.zkitefly.eu.org/node1", 256),
    ("etnode2", "https://etnode.zkitefly.eu.org/node2", 256),
    ("easytier_public", "https://public.easytier.top", 256),
    ("gitee_tc_release_page", f"https://gitee.com/burningtnt/Terracotta/releases/tag/v{TC_VER}", 512),
    ("cnb_tc_release_page", f"https://cnb.cool/HMCL-Terracotta/Terracotta/-/releases/tag/v{TC_VER}", 512),
]

CF_KEY = CONFIG.get("curseforge_api_key")


def run_endpoint(item):
    name, url, nbytes = item
    headers = {}
    if "api.curseforge.com" in url or "/curseforge/v1/" in url:
        if CF_KEY:
            headers["x-api-key"] = CF_KEY
    if name.startswith("adoptium"):
        return merge(name, url, probe(url, max_bytes=nbytes, allow_redirects=False), note="no-follow")
    return merge(name, url, probe(url, max_bytes=nbytes, headers=headers))


print("== endpoints ==")
with ThreadPoolExecutor(max_workers=10) as pool:
    futs = [pool.submit(run_endpoint, it) for it in ENDPOINTS]
    for fut in as_completed(futs):
        rec = fut.result()
        results["endpoints"].append(rec)
        print(f"  [{rec.get('status')}] {rec['name']} {rec.get('error') or rec.get('kind')}")

# ---------- rewrite live samples ----------
print("== rewrite samples ==")
# pick a real 1.20.1 version json + a library + an asset from official manifest
try:
    man = session.get(
        "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", timeout=TIMEOUT
    ).json()
    v120 = next(v for v in man["versions"] if v["id"] == "1.20.1")
    vjson_url = v120["url"]
    vjson_bmcl = rewrite_to_bmcl(vjson_url)
    results["rewrites"].append(merge(
        "1.20.1_version_json_official", vjson_url,
        probe(vjson_url, max_bytes=2048),
        rewritten=vjson_bmcl,
    ))
    results["rewrites"].append(merge(
        "1.20.1_version_json_bmcl", vjson_bmcl,
        probe(vjson_bmcl, max_bytes=2048),
        official=vjson_url,
    ))
    vjson = session.get(vjson_url, timeout=TIMEOUT).json()
    lib = None
    for L in vjson.get("libraries") or []:
        art = (L.get("downloads") or {}).get("artifact") or {}
        if art.get("url") and art.get("size") and int(art["size"]) < 80_000:
            lib = art
            break
    if lib:
        off = lib["url"]
        mir = rewrite_to_bmcl(off)
        results["rewrites"].append(merge(
            "small_lib_official", off,
            probe(off, max_bytes=int(lib["size"]) + 16),
            size=lib.get("size"), sha1=lib.get("sha1"), rewritten=mir,
        ))
        if mir:
            results["rewrites"].append(merge(
                "small_lib_bmcl", mir,
                probe(mir, max_bytes=int(lib["size"]) + 16),
                official=off, size=lib.get("size"),
            ))
    idx = (vjson.get("assetIndex") or {})
    idx_url = idx.get("url")
    if idx_url:
        idx_bmcl = rewrite_to_bmcl(idx_url)
        results["rewrites"].append(merge(
            "asset_index_official", idx_url, probe(idx_url, max_bytes=2048), rewritten=idx_bmcl
        ))
        if idx_bmcl:
            results["rewrites"].append(merge(
                "asset_index_bmcl", idx_bmcl, probe(idx_bmcl, max_bytes=2048), official=idx_url
            ))
        idx_json = session.get(idx_url, timeout=TIMEOUT).json()
        # pick a tiny asset
        tiny = None
        for name, obj in (idx_json.get("objects") or {}).items():
            if obj.get("size") and int(obj["size"]) < 4000:
                tiny = obj
                tiny_name = name
                break
        if tiny:
            h = tiny["hash"]
            off = f"https://resources.download.minecraft.net/{h[:2]}/{h}"
            mir = rewrite_to_bmcl(off)
            results["rewrites"].append(merge(
                f"asset_{tiny_name}", off,
                probe(off, max_bytes=int(tiny["size"]) + 16),
                rewritten=mir, size=tiny["size"],
            ))
            if mir:
                results["rewrites"].append(merge(
                    f"asset_bmcl_{tiny_name}", mir,
                    probe(mir, max_bytes=int(tiny["size"]) + 16),
                    official=off, size=tiny["size"],
                ))
    client = ((vjson.get("downloads") or {}).get("client") or {})
    if client.get("url"):
        off = client["url"]
        mir = rewrite_to_bmcl(off)
        results["rewrites"].append(merge(
            "client_jar_head_official", off,
            probe(off, method="HEAD"),
            rewritten=mir, size=client.get("size"),
        ))
        if mir:
            results["rewrites"].append(merge(
                "client_jar_head_bmcl", mir,
                probe(mir, method="HEAD"),
                official=off, size=client.get("size"),
            ))
except Exception as e:
    results["errors"].append(f"rewrite samples: {e}\n{traceback.format_exc()}")

# fabric maven tiny file via official + bmcl
FABRIC_TINY = "https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.16.9/fabric-loader-0.16.9.pom"
results["rewrites"].append(merge(
    "fabric_pom_official", FABRIC_TINY, probe(FABRIC_TINY, max_bytes=2048),
    rewritten=rewrite_to_bmcl(FABRIC_TINY),
))
mir = rewrite_to_bmcl(FABRIC_TINY)
if mir:
    results["rewrites"].append(merge("fabric_pom_bmcl", mir, probe(mir, max_bytes=2048)))

# quilt maven
QUILT_POM = "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-loader/0.26.3/quilt-loader-0.26.3.pom"
results["rewrites"].append(merge(
    "quilt_pom_official", QUILT_POM, probe(QUILT_POM, max_bytes=2048),
    rewritten=rewrite_to_bmcl(QUILT_POM),
))
mir = rewrite_to_bmcl(QUILT_POM)
if mir:
    results["rewrites"].append(merge("quilt_pom_bmcl", mir, probe(mir, max_bytes=2048)))

# ---------- real small downloads via DownloadManager ----------
print("== real downloads ==")
tmpdir = Path(tempfile.mkdtemp(prefix="pymcl_audit_"))
dm = DownloadManager(threads=2)


def try_dl(name, url, dest, **kwargs):
    t0 = time.perf_counter()
    try:
        p = dm.download(url, dest, timeout=60, **kwargs)
        size = p.stat().st_size if p.is_file() else 0
        head = b""
        if p.is_file():
            with open(p, "rb") as f:
                head = f.read(8)
        results["downloads"].append({
            "name": name, "url": url, "ok": True, "size": size,
            "ms": round(time.perf_counter() - t0, 3),
            "head": head.hex(), "path": str(p), "error": None,
        })
        print(f"  [DL-OK] {name} {size}B")
    except Exception as e:
        results["downloads"].append({
            "name": name, "url": url, "ok": False, "size": 0,
            "ms": round(time.perf_counter() - t0, 3),
            "head": "", "path": str(dest), "error": f"{type(e).__name__}: {e}",
        })
        print(f"  [DL-FAIL] {name} {e}")


# official + bmcl manifest
try_dl("manifest_official", "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
       tmpdir / "manifest_official.json")
try_dl("manifest_bmcl_direct", "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
       tmpdir / "manifest_bmcl.json")

# fabric-api latest primary via modrinth API then official+mcim
try:
    proj = session.get("https://api.modrinth.com/v2/project/fabric-api/version", timeout=TIMEOUT,
                       params={"game_versions": '["1.20.1"]', "loaders": '["fabric"]'}).json()
    f0 = None
    for v in proj:
        for f in v.get("files") or []:
            if f.get("url") and f.get("size") and int(f["size"]) < 3_000_000:
                f0 = f
                break
        if f0:
            break
    if f0:
        url = f0["url"]
        mcim = rewrite_to_mcim(url)
        try_dl("fabric_api_modrinth_cdn", url, tmpdir / f0["filename"],
               sha1=f0.get("hashes", {}).get("sha1"), size=f0.get("size"))
        if mcim and mcim != url:
            try_dl("fabric_api_mcim_cdn", mcim, tmpdir / ("mcim_" + f0["filename"]),
                   sha1=f0.get("hashes", {}).get("sha1"), size=f0.get("size"))
        results["rewrites"].append({
            "name": "modrinth_cdn_rewrite",
            "url": url,
            "rewritten": mcim,
            "rule_ok": bool(mcim and mcim.startswith("https://mod.mcimirror.top/data/")),
        })
except Exception as e:
    results["errors"].append(f"modrinth fabric-api: {e}")

# JEI via CF API + CDN construction
try:
    headers = {"Accept": "application/json", "x-api-key": CF_KEY} if CF_KEY else {"Accept": "application/json"}
    files = None
    for base in (
        "https://api.curseforge.com/v1",
        "https://mod.mcimirror.top/curseforge/v1",
        "https://bmclapi2.bangbang93.com/curseforge/v1",
    ):
        try:
            r = session.get(f"{base}/mods/238222/files", headers=headers, timeout=TIMEOUT,
                            params={"pageSize": 5})
            if r.status_code == 200:
                data = r.json()
                items = data.get("data") if isinstance(data, dict) else data
                if items:
                    files = items
                    results["rewrites"].append({
                        "name": "cf_files_base", "url": f"{base}/mods/238222/files",
                        "ok": True, "status": 200, "count": len(items),
                    })
                    break
        except Exception as e:
            results["rewrites"].append({
                "name": "cf_files_base", "url": f"{base}/mods/238222/files",
                "ok": False, "error": str(e),
            })
    if files:
        f = files[0]
        fid = f.get("id")
        fname = f.get("fileName")
        durl = f.get("downloadUrl")
        constructed = _cf_file_cdn_url(int(fid), fname)
        media = _cf_file_cdn_url(int(fid), fname, host="mediafilez.forgecdn.net")
        results["rewrites"].append({
            "name": "cf_jei_urls",
            "file_id": fid,
            "fileName": fname,
            "api_downloadUrl": durl,
            "constructed_edge": constructed,
            "constructed_media": media,
            "candidates": cf_mod_download_urls(238222, fid, fname, durl),
        })
        if durl:
            results["rewrites"].append(merge("cf_jei_api_downloadUrl", durl, probe(durl, method="HEAD")))
        results["rewrites"].append(merge("cf_jei_edge_cdn", constructed, probe(constructed, method="HEAD")))
        results["rewrites"].append(merge("cf_jei_media_cdn", media, probe(media, method="HEAD")))
        mcim_cdn = "https://mod.mcimirror.top" + constructed.split(".net", 1)[-1] if ".net" in constructed else None
        if mcim_cdn:
            results["rewrites"].append(merge(
                "cf_jei_mcim_forgecdn_rewrite", mcim_cdn, probe(mcim_cdn, method="HEAD"),
                note="MCIM docs: forgecdn -> mod.mcimirror.top; code does NOT rewrite this",
            ))
        # download first 64k via GET to prove bytes, or full if small
        if fname and (f.get("fileLength") or 0) < 4_000_000:
            try_dl("cf_jei_file", durl or media, tmpdir / fname)
except Exception as e:
    results["errors"].append(f"cf jei: {e}\n{traceback.format_exc()}")

# forge installer HEAD (1.20.1-47.4.0 is a common recent; discover from bmcl list)
try:
    lst = session.get("https://bmclapi2.bangbang93.com/forge/minecraft/1.20.1", timeout=TIMEOUT).json()
    art = None
    if isinstance(lst, list) and lst:
        item = lst[-1]
        ver = item.get("version")
        mc = item.get("mcversion") or "1.20.1"
        branch = item.get("branch") or ""
        full = f"{mc}-{ver}" + (f"-{branch}" if branch else "")
        art = full
    if art:
        official = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{art}/forge-{art}-installer.jar"
        bmcl = rewrite_to_bmcl(official)
        q = f"https://bmclapi2.bangbang93.com/forge/download?mcversion=1.20.1&version={ver}&category=installer&format=jar"
        results["rewrites"].append(merge("forge_installer_official_head", official, probe(official, method="HEAD"), artifact=art))
        if bmcl:
            results["rewrites"].append(merge("forge_installer_bmcl_maven_head", bmcl, probe(bmcl, method="HEAD"), artifact=art))
        results["rewrites"].append(merge("forge_installer_bmcl_query", q, probe(q, method="HEAD", allow_redirects=True), artifact=art))
except Exception as e:
    results["errors"].append(f"forge installer: {e}")

# neoforge installer HEAD
try:
    xml = session.get(
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml", timeout=TIMEOUT
    ).text
    import re
    vers = re.findall(r"<version>([^<]+)</version>", xml)
    latest = vers[-1] if vers else None
    if latest:
        official = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{latest}/neoforge-{latest}-installer.jar"
        bmcl = rewrite_to_bmcl(official)
        results["rewrites"].append(merge("neoforge_installer_official_head", official, probe(official, method="HEAD"), ver=latest))
        if bmcl:
            results["rewrites"].append(merge("neoforge_installer_bmcl_head", bmcl, probe(bmcl, method="HEAD"), ver=latest))
except Exception as e:
    results["errors"].append(f"neoforge installer: {e}")

# ---------- github proxies ----------
print("== github proxies ==")
GH_RAW = "https://raw.githubusercontent.com/HMCL-dev/HMCL/main/HMCL/src/main/resources/assets/terracotta.json"
prefixes = list(CONFIG.get("github_proxy_prefixes") or [])
for pfx in prefixes:
    u = pfx + GH_RAW
    rec = merge(f"proxy {pfx}", u, probe(u, max_bytes=512))
    results["github_proxies"].append(rec)
    print(f"  [{rec.get('status')}] {pfx} {rec.get('error') or rec.get('kind')}")
results["github_proxies"].append(merge("github_raw_direct", GH_RAW, probe(GH_RAW, max_bytes=512)))

# also test prefix+github release (common fail mode)
GH_REL = f"https://github.com/burningtnt/Terracotta/releases/download/v{TC_VER}/terracotta-{TC_VER}-{classifier()}-pkg.tar.gz"
for pfx in prefixes:
    u = pfx + GH_REL
    rec = merge(f"proxy_release {pfx}", u, probe(u, method="HEAD"))
    results["github_proxies"].append(rec)

# ---------- terracotta packages ----------
print("== terracotta ==")
for u in tc_download_urls():
    rec = merge("tc_pkg", u, probe(u, method="HEAD", allow_redirects=True))
    rec["follow_get"] = probe(u, max_bytes=64, allow_redirects=True)
    results["terracotta"].append(rec)
    print(f"  [{rec.get('status')}] {u} get={rec['follow_get'].get('status')} {rec.get('error') or rec['follow_get'].get('error')}")

# compare HMCL terracotta.json downloads if we got it
try:
    raw = session.get(GH_RAW, timeout=TIMEOUT).json()
    results["terracotta"].append({
        "name": "hmcl_json_meta",
        "ok": True,
        "hmcl_version_keys": list((raw or {}).keys())[:20] if isinstance(raw, dict) else type(raw).__name__,
        "raw_type": type(raw).__name__,
    })
    # find 0.4.2 urls
    blob = json.dumps(raw, ensure_ascii=False)
    results["terracotta"].append({
        "name": "hmcl_json_contains_0_4_2",
        "ok": "0.4.2" in blob,
        "has_gitee": "gitee.com" in blob,
        "has_cnb": "cnb.cool" in blob,
        "has_alist": "alist.8mi.tech" in blob,
        "has_github": "github.com/burningtnt" in blob,
    })
except Exception as e:
    results["errors"].append(f"hmcl terracotta json: {e}")

# ---------- catalog slugs ----------
print("== catalog slugs ==")
slugs = set()
for info in catalog.MOD_ALIASES.values():
    if info.get("slug"):
        slugs.add(("mod", info["slug"]))
for info in catalog.MODPACK_ALIASES.values():
    if info.get("slug"):
        slugs.add(("pack", info["slug"]))
for row in catalog.POPULAR_MODS:
    if row[1] == "modrinth":
        slugs.add(("mod", row[2]))
for row in catalog.POPULAR_MODPACKS:
    if row[1] == "modrinth":
        slugs.add(("pack", row[2]))

# extra popular/hot ones always check
must = [
    "jei", "sodium", "fabric-api", "create", "optifine", "forge", "waila",
    "cocoa-input-fix", "cocoa-input", "torohealth-damage-indicators",
    "create_plus", "simply-skyblock", "tragic-world", "dragon-adventure",
    "greedy-craft", "hbm-nuclear-tech", "better-mc-forge-bmc1",
    "gt-new-horizons", "rlcraft", "fabulously-optimized", "adrenaline",
    "all-of-create-fabric", "worldedit", "industrial-craft",
]


def check_slug(kind, slug):
    url = f"https://api.modrinth.com/v2/project/{slug}"
    r = probe(url, max_bytes=800)
    title = None
    ptype = None
    if r.get("ok") and r.get("kind") == "json":
        try:
            data = session.get(url, timeout=TIMEOUT).json()
            title = data.get("title")
            ptype = data.get("project_type")
        except Exception:
            pass
    return {
        "kind": kind, "slug": slug, "url": url,
        "ok": r.get("ok"), "status": r.get("status"),
        "error": r.get("error"), "title": title, "project_type": ptype,
    }


slug_list = sorted(slugs | {("mod", s) for s in must} | {("pack", s) for s in must})
with ThreadPoolExecutor(max_workers=12) as pool:
    futs = {pool.submit(check_slug, k, s): (k, s) for k, s in slug_list}
    for fut in as_completed(futs):
        rec = fut.result()
        results["catalog_slugs"].append(rec)

# CF IDs of interest
print("== catalog CF ids ==")
cf_ids = {
    225608: "optifine/worldedit collision",
    224791: "blood-magic/portal-gun collision",
    228756: "better-fps/iron-chests collision",
    238222: "JEI control",
    1238396: "CBC",
    1059094: "CDC",
    252507: "GTNH",
    285109: "RLCraft",
    429793: "Better MC",
    302973: "TFC",
    264231: "Ice and Fire",
    235121: "HBM",
    240630: "VeinMiner",
    32274: "JourneyMap",
    227639: "Twilight Forest",
}


def check_cf(cid, note):
    url = f"https://api.curseforge.com/v1/mods/{cid}"
    headers = {"Accept": "application/json"}
    if CF_KEY:
        headers["x-api-key"] = CF_KEY
    try:
        r = session.get(url, headers=headers, timeout=TIMEOUT)
        name = slug = class_id = None
        if r.status_code == 200:
            d = (r.json() or {}).get("data") or {}
            name = d.get("name")
            slug = d.get("slug")
            class_id = d.get("classId")
        return {
            "id": cid, "note": note, "status": r.status_code,
            "name": name, "slug": slug, "classId": class_id, "ok": r.status_code == 200,
        }
    except Exception as e:
        return {"id": cid, "note": note, "ok": False, "error": str(e)}


with ThreadPoolExecutor(max_workers=8) as pool:
    futs = [pool.submit(check_cf, cid, note) for cid, note in cf_ids.items()]
    for fut in as_completed(futs):
        rec = fut.result()
        results["catalog_cf"].append(rec)
        print(f"  CF {rec.get('id')} -> {rec.get('status')} {rec.get('name')} / {rec.get('slug')}")

# also MCIM/BMCL for CBC
for base, label in (
    ("https://mod.mcimirror.top/curseforge/v1", "mcim"),
    ("https://bmclapi2.bangbang93.com/curseforge/v1", "bmcl"),
):
    url = f"{base}/mods/1238396"
    headers = {"x-api-key": CF_KEY} if CF_KEY else {}
    results["catalog_cf"].append(merge(f"{label}_cbc", url, probe(url, max_bytes=512, headers=headers)))

results["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("WROTE", OUT)
print("endpoints", len(results["endpoints"]),
      "rewrites", len(results["rewrites"]),
      "downloads", len(results["downloads"]),
      "slugs", len(results["catalog_slugs"]))
