# -*- coding: utf-8 -*-
"""启动器全局配置。"""
from pathlib import Path

from . import utils

CONFIG_FILE = utils.ROOT / "config.json"

# default_isolation 的出厂值从 "none" 换成 "all" 那一次。换了这个字符串，
# 还停在旧出厂值上的老配置会再跟一次；用户自己选过别的档位一律不动。
ISOLATION_DEFAULTS_VERSION = "2026.09-isolate-all"
_LEGACY_DEFAULT_ISOLATION = "none"

DEFAULT_CONFIG = {
    # 游戏目录（相对于启动器主目录）。与 PCL/HMCL 一样用 .minecraft，
    # 版本平铺在它的 versions/ 下面
    "instances_dir": ".minecraft",
    # 历史遗留：旧版把游戏目录再切成 .minecraft/<实例名>/。空 = 单目录模式，
    # 启动时 single_root.migrate() 会把残留的子实例并上来
    "default_instance": "",
    # Java 运行时目录名（所有版本共享）
    "java_dir": "java",
    # libraries/assets 是否放到 shared/ 下（游戏目录之外）
    "shared_libraries": False,
    "shared_assets": False,
    # 默认分配内存 (MB)
    "memory_mb": 4096,
    # 下载并发线程数
    "download_threads": 8,
    # 默认窗口分辨率
    "width": 854,
    "height": 480,
    # 微软 OAuth 客户端 ID（可替换为自己的应用 ID）
    "microsoft_client_id": "00000000402b5328",
    # CurseForge 官方 API key
    # 默认值来自 HMCL 开源分析（已实测可用），商业产品应自行申请
    "curseforge_api_key": "$2a$10$o8pygPrhvKBHuuh5imL2W.LCNFhB15zBYAExXx/TqTx/Zp5px2lxu",
    # GitHub raw/releases 国内镜像前缀（会拼在原始 https URL 前面）
    "github_proxy_prefixes": [
        "https://gitproxy.mrhjx.cn/",
        "https://ghproxy.vip/",
        "https://gh-proxy.com/",
        "https://v6.gh-proxy.org/",
        "https://cdn.gh-proxy.com/",
    ],
    # 每次启动是否强制刷新远程版本清单
    "force_manifest_refresh": False,
    # 文件下载源：auto=官方<4s用官方否则BMCLAPI；official；bmclapi
    "download_source": "auto",
    # 模组/整合包：auto / official / mcim
    "community_source": "auto",
    # 跟随系统代理（Clash 7897）。关了才强制直连
    "use_system_proxy": True,
    # AI 助手：public=公益网关；custom=用户自己的 NewAPI
    "ai_mode": "public",
    "ai_gateway_url": "",
    "ai_base_url": "",
    "ai_api_key": "",
    "ai_model": "deepseek-v4-flash",
    # AI 权限：写操作档位。旧值 standard/full 与 ai_confirm_writes=False
    # 在 backend.get_settings 里平滑映射成 default/acceptEdits/yolo
    "ai_confirm_writes": True,
    "ai_permission_mode": "default",
    "ai_permission_rules": [],
    "ai_permission_dont_ask": False,
    # HMCL 自定义 EasyTier 会合节点（官方 /nodes 表往往不够）
    "terracotta_extra_nodes": [
        "https://terracotta.glavo.site/acebc7d8-1208-47fd-b212-d03ac49e36e0",
    ],
    # 反馈中心：空则用 DEFAULT_FEEDBACK_URL / 环境变量 PYMCL_FEEDBACK_URL
    "feedback_url": "",
    "feedback_heartbeat": True,
    "feedback_consent": None,
    "device_id": "",
    # 新版本的默认隔离档位。出厂「完全独立」：各版本自己一套 mods/config/存档，
    # 换个版本不会把上一个版本的模组一起拖进去
    "default_isolation": "all",
    # 上面那个默认换过一次的标记，见 _migrate_default_isolation
    "isolation_defaults": "",
    "default_jvm_args": "",
    "default_priority": "normal",
    "update_url": "https://pymcl.dev/update.json",
    "theme_color": "#2E9B6B",
    "ui_dark": False,
    # 壁纸：本地图片路径，或 .mp4 等视频（动态壁纸）
    "ui_background": "",
    # 壁纸文件夹：填了就轮播里面的图片/视频，优先级高于上面那张单图
    "ui_background_folder": "",
    # 轮播是随机抽还是按文件名顺序走
    "ui_background_shuffle": False,
    # 轮播间隔（分钟）
    "ui_background_interval": 10,
    # 换过的旧壁纸（最早在前，最新在后），「撤销上一张」就是从这儿往回退。
    # 两个栈成对推进、成对弹出，撤销才能把「单图 + 文件夹」一起退回去。
    "ui_background_history": [],
    "ui_background_folder_history": [],
    # 侧栏与标题栏的不透明度 0–100：调低后壁纸从它们后面透出来
    "ui_sidebar_opacity": 85,
    # 壁纸模糊半径 0–40 px：糊掉壁纸细节，压在上面的字才不跟花纹打架
    "ui_background_blur": 0,
    # 壁纸遮罩浓度 0–80%：在壁纸上盖一层主题底色（浅色提亮 / 深色压暗）
    "ui_background_dim": 25,
    # 这三个键必须在这儿声明，不能只在 save_settings 里写：
    # `save()` 落的是整份 data，`load()` 却只按本表的键名回读 ——
    # 不声明就是「关掉飞入动画、重开启动器它又自己回来了」。
    "ui_fly_animation": True,
    "ui_fly_duration_ms": 620,
    "ui_motion": True,
    # 启动页画布 / 侧栏自定义。缺了这些键的话，界面当场能改，重启就被
    # load() 的白名单丢掉，下一次再 save() 还会把磁盘上的布局一并抹掉。
    "ui_layout": None,
    "ui_layouts": {},
    "ui_layout_profile": "",
    # 启动坞停在哪个角：bl/br/tl/tr（用户拖过去就记住）。
    # auto = 还没拖过，由启动页自己挑一个压不着卡片的角。
    "ui_launch_dock_corner": "auto",
    # 主窗口宽高比：4:3 / 16:9 锁死（拖边拖角都保比例），free = 随便拖。
    # 壁纸是按整窗保比例裁切的，比例锁在图片/视频常见档位上，用户挑同比例
    # 的壁纸就能一点不裁完整显示，拖窗口也不会变成裁头裁脚。
    "ui_window_aspect": "4:3",
    "ui_nav_order": [],
    "ui_nav_hidden": [],
    "ui_nav_pinned": [],
    # 分组排法的分组与成员：[{"title": "通用", "keys": ["settings", …]}, …]。
    # None = 还没拖过，用出厂那三组。不声明这个键的话，用户在分组档下拖出来的
    # 侧栏会在重启后被 load() 的白名单丢掉。
    "ui_nav_groups": None,
    # 出厂侧栏布局的版本号：换了新默认时给没自定义过的用户补一次
    "ui_nav_defaults": "",
    # 侧栏排法：grouped=账户/游戏/通用 分组（出厂）；compact=启动/游戏/版本管理 三项
    "ui_nav_style": "grouped",
    "ui_section_members": {},
    "ui_sidebar_width": 0,
    # 全局默认 Java：版本设置与实例偏好都是「自动」时才生效
    "default_java": "",
    "global_mods_dir": "",
    "launcher_visibility": "keep",
    "gc_preset": "auto",
    "download_limit_kbps": 0,
    "auto_check_update": True,
    "custom_homepage": "",
    "homepage_mode": "news",
    "window_mode": "window",
    "skip_assets": False,
    "first_run": True,
    "show_hidden_versions": False,
    "catalog_favorites": [],
    "offline_skin": "default",
    "allow_multi_instance": False,
    # 导出模组 / 光影 / 存档时的落地目录。空 = 启动器根目录下的 exports/
    "export_dir": "",
    "language": "zh_CN",
}


class Config:
    def __init__(self):
        self.data = dict(DEFAULT_CONFIG)
        # 每次改动 +1。上层（如 app.backend.get_setting）据此判断缓存是否还新鲜，
        # 不用每取一个键就把整份设置字典重建一遍。
        self.revision = 0
        self.load()

    def load(self):
        self.revision += 1
        stored = utils.read_json(CONFIG_FILE, None)
        if isinstance(stored, dict):
            missing = False
            for k in DEFAULT_CONFIG:
                if k in stored:
                    self.data[k] = stored[k]
                else:
                    missing = True
            # 表里还没声明的键也要留下：布局模块走 cfg.set()，审计脚本
            # 扫不到，再漏一个键就会重演「界面改了、重启没了」。
            for k, value in stored.items():
                if k not in DEFAULT_CONFIG:
                    self.data[k] = value
            if self._migrate_legacy_instances_dir():
                missing = True
            if self._migrate_default_isolation():
                missing = True
            if missing:
                self.save()
        else:
            self._migrate_legacy_instances_dir()
            self._migrate_default_isolation()
            self.save()

    def _migrate_legacy_instances_dir(self) -> bool:
        """旧版默认 instances/ 迁到 .minecraft/。用户自己改过的路径不动。"""
        current = str(self.data.get("instances_dir") or "").strip()
        if current != "instances":
            return False
        old = utils.ROOT / "instances"
        new = utils.ROOT / ".minecraft"
        if old.is_dir() and not new.exists():
            old.rename(new)
        self.data["instances_dir"] = ".minecraft"
        return True

    def _migrate_default_isolation(self) -> bool:
        """新版本默认隔离档位换了出厂值：还停在旧出厂值上的配置跟一次。

        只认字面等于旧出厂值的那一份——挑过别的档位的人不动。标记写在
        isolation_defaults 里，所以只做一次：迁完之后他要调回「大锅饭」，
        下次启动不会再被改回来。

        已经建好的版本不受影响：它们的 isolation 早就落在各自的 pymcl.json 里，
        这里改的只是「以后新建的版本按什么档位来」。
        """
        if self.data.get("isolation_defaults") == ISOLATION_DEFAULTS_VERSION:
            return False
        if str(self.data.get("default_isolation") or "") == _LEGACY_DEFAULT_ISOLATION:
            self.data["default_isolation"] = "all"
        self.data["isolation_defaults"] = ISOLATION_DEFAULTS_VERSION
        return True

    def save(self):
        utils.write_json(CONFIG_FILE, self.data)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.revision += 1

    def update(self, mapping):
        self.data.update(mapping)
        self.revision += 1

    # ---- 路径 ----
    @property
    def instances_dir(self) -> Path:
        return utils.ROOT / str(self.data["instances_dir"])

    @property
    def java_dir(self) -> Path:
        return utils.ROOT / str(self.data["java_dir"])

    @property
    def cache_dir(self) -> Path:
        return utils.ROOT / "cache"

    def libraries_dir(self, instance_dir: Path) -> Path:
        if self.data["shared_libraries"]:
            return utils.ROOT / "shared" / "libraries"
        return Path(instance_dir) / "libraries"

    def assets_dir(self, instance_dir: Path) -> Path:
        if self.data["shared_assets"]:
            return utils.ROOT / "shared" / "assets"
        return Path(instance_dir) / "assets"


# 全局单例
CONFIG = Config()

# 壁纸历史栈上限：够反复试几张再退回来，又不至于把 config.json 撑肥
BG_HISTORY_MAX = 20


def _history_paths(raw) -> list:
    """栈里只认字符串和 Path。别的类型 str() 一下会变出一条看着像路径的假货
    （整个栈被误塞进某一格就是这样），撤销时会当真拿去加载。"""
    return [str(p) for p in (raw or []) if isinstance(p, (str, Path))]


def background_history() -> tuple:
    """换下来的旧壁纸，最早在前、最新在后，返回 (单图栈, 文件夹栈)。

    两个栈等长：撤销一次弹一对，才能把当时那一整套壁纸状态原样退回去。
    历史上只写过单图栈的话，文件夹栈在这儿补齐空位。
    """
    images = _history_paths(CONFIG.get("ui_background_history"))
    folders = _history_paths(CONFIG.get("ui_background_folder_history"))
    if len(folders) != len(images):
        folders = (folders + [""] * len(images))[:len(images)]
    return images, folders


def push_background_history(old_image: str, old_folder: str) -> tuple:
    """把换下来的这一组压进历史栈，返回新的两个栈（不落盘，由调用方一起写）。

    放在 config 这层而不是某个前端里：换壁纸的入口不止设置页一个，
    主题包加载也会换，漏掉哪条路径那条路径换过的壁纸就撤销不回来。
    """
    images, folders = background_history()
    old_image, old_folder = str(old_image or ""), str(old_folder or "")
    if images and (images[-1], folders[-1]) == (old_image, old_folder):
        return images, folders
    images.append(old_image)
    folders.append(old_folder)
    return images[-BG_HISTORY_MAX:], folders[-BG_HISTORY_MAX:]
