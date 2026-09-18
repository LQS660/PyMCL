# WPF / 安卓 对齐 Qt 主版 — 逐方法核对表（2026-09-18）

尺子：`app/backend.py` 的 `BackendAPI` 全部公开方法（Qt 前端能用到的后端能力面），逐条看 WPF 与安卓有没有等价实现。
外壳层（侧栏、卡片、动画、角标、坞、同意提示、FAQ 等不走后端方法的功能）另列一表。

- WPF 一列：C# 调用点里出现了这个 RPC 名（`_wpf_gap.py` 同一口径）。
- 安卓一列：人工对照 `android/app/src/main` 的 data / vm / ui 层逐条判定，证据列写的是文件与函数名。
- 图例：✅ 有等价实现 · ◐ 部分 · ❌ 缺 · — 平台不适用。
- 生成/复核：`python _align_matrix.py`（读本文件的分类表，重算数字并报出 backend 新增而这里没分类的方法）。

## 总数

- backend 公开方法 **195** 个。
- **WPF**：调用了 **191/195**；未调用的 4 个全是桥上不存在/不可 RPC 的（invalidate_instances, take_migration_report, call_async, start_task），即可 RPC 面 **191/191 = 100%**。WPF 的差额全在外壳层与运行时行为（见下表与 t-644/645/646）。
- **安卓**：适用 175 个（剔除 — 20 个）：✅ 175 · ◐ 0 · ❌ 0（`python _align_matrix.py` 2026-09-18 22:1x 重算；指挥官 opus-5-4 补记 t-711 已实现的 4 行与 t-647 早已验收的 4 行；t-714 交付 `terracotta_direct_connect` / `preflight_launch` / `apply_crash_action` 三行）。按 ✅=1、◐=0.5 折算：**现在 100.0%**；逐方法表已无缺口，余下的都是真机验证（见 d-553 的 NOT RUN 清单）。

## 安卓缺口清单（❌ / ◐，这就是要补的活）

已经在、之前被误判为缺的：`export_content`（ContentExport.kt，9/17 已交）、`get/set/toggle_version_isolation`（VersionSettings.setIsolation + seedFromShared）、`import_layout`（LayoutStore.importFrom/exportTo，LayoutSettingsScreen 已接）、`hide_version`（VersionOps.setHidden）。**t-649 / t-650 的任务书里这三项要划掉。**

## 外壳层功能点

| 功能点 | WPF | 安卓 |
|---|---|---|
| 侧栏自定义（ui_nav_order / pinned / hidden / 分区成员） | Y NavModel.cs + test_nav_parity | NA 底栏 MainTab（平台差异），但 ui_nav_* 键一个不认 |
| 首页卡片拖拽 / 吸附 / 布局方案 | Y Dashboard.cs | Y LayoutSettingsScreen + LayoutStore |
| 主题深浅色 / 强调色 / 背景图 / 壁纸历史撤销 | Y Themes + background_history | Y ThemeScreen + WallpaperLayer + WallpaperModel |
| 界面多语言（界面文案随 language 切换） | P 只切后端字串，C# 1204 处硬编码中文（→ t-644） | W t-647 进行中 |
| 崩溃分析对话框 | Y | Y CrashReporter + CrashRules |
| 首次运行向导 | Y FirstRunWizard.cs | Y FirstRunScreen |
| 反馈同意提示（_ask_feedback_consent） | N（→ t-646） | Y FeedbackRepo.hasConsent / setConsent |
| 常见问题 / 帮助库 | N 只有 1 处引用（→ t-646） | Y 反馈页 FaqCard：搜索 + 点标题展开，data/HelpContent 与 help_content.py 逐条一致（9/18 t-710） |
| 飞入任务动画 | Y Motion.cs | N 无（移动端可不做） |
| 任务角标 | Y | Y 底栏「下载」格 + TaskCenter.badgeText（9/18 t-712） |
| 悬浮下载坞（settings/instance/tasks/feedback 页隐藏） | Y | Y data/DownloadDock + ui/DownloadDockBar（9/18 t-712） |
| 启动器可见性（游戏启动后最小化/隐藏） | Y | NA 手机上前后台由系统管 |
| 自动检查更新提示 | Y check_update | P PyMclApp 启动后台查（auto_check_update 开关）+ 设置页「上次检查」结果行 / 检查更新 / 打开下载页；没有全局弹提示（9/18 t-710） |
| 目录页初载异步 / 可取消 / 错误态 | N 3 页超 9 s 预算（→ t-645） | Y ContentLibraryScreen 取消旧任务 + 代次校验（9/17 已交） |
| 全局模组页 / 对话框 | Y | P 共享池能力在，缺页面（→ t-649） |
| 清理 / 维护工具页 | Y cleaner_preview/apply | Y 设置页 CleanerCard，扫描 + 清理两步（9/18 t-712） |

## 逐方法表

| # | backend 方法 | WPF | 安卓 | 安卓证据 / 说明 |
|---:|---|:---:|:---:|---|
| 1 | `invalidate_instances` (L267) | — 桥不暴露（_bridge_gap NOT_EXPOSED） | — | Qt 进程内 _inst_cache，桥也不暴露（d-398 同类） |
| 2 | `take_migration_report` (L289) | — 桥不暴露 | — | Qt 启动时单目录合并的报告，安卓没有这条启动路径 |
| 3 | `start_task` (L298) | — d-398：形参要 Python 可调用对象，永久剔除 | ✅ | vm/AppViewModel.startTask + data/TaskCenter |
| 4 | `is_download_title` (L317) | ✅ | ✅ | data/TaskCenter.isDownloadTitle |
| 5 | `get_crash` (L336) | ✅ | ✅ | data/GameRuntime.latestCrashReport + CrashReporter.analyze |
| 6 | `export_crash_report` (L343) | ✅ | ✅ | data/CrashReporter.export |
| 7 | `open_crash_file` (L349) | ✅ | — | 安卓没有“用系统打开文件”，走分享/导出 |
| 8 | `wait_task` (L369) | ✅ | ✅ | 协程 Job + TaskCenter 状态 |
| 9 | `cancel_task` (L403) | ✅ | ✅ | vm/AppViewModel.cancelTask |
| 10 | `call_async` (L417) | — 桥不暴露 | — | Qt 进程内回调工厂，桥不暴露 |
| 11 | `shutdown` (L450) | ✅ | ✅ | TerracottaRepo/VpnCoordinator.shutdown + Activity 生命周期 |
| 12 | `task_title` (L486) | ✅ | ✅ | data/TaskCenter.summary |
| 13 | `install_game` (L566) | ✅ | ✅ | data/Installer.installVanilla + vm.installSelected |
| 14 | `install_modpack` (L580) | ✅ | ✅ | vm/AppViewModel.installModpack + data/ModpackInstall |
| 15 | `install_mod` (L584) | ✅ | ✅ | data/Mods.install / ContentInstall.install |
| 16 | `install_shader` (L588) | ✅ | ✅ | data/ContentInstall.install(kind=shader) |
| 17 | `install_resourcepack` (L592) | ✅ | ✅ | data/ContentInstall.install(kind=resourcepack) |
| 18 | `install_datapack` (L596) | ✅ | ✅ | vm/AppViewModel.installDatapack |
| 19 | `install_world` (L600) | ✅ | ✅ | data/ContentInstall + Saves.unzipInto |
| 20 | `list_catalog_files` (L604) | ✅ | ✅ | data/CatalogFiles.resolveModrinth / resolveCurseForge |
| 21 | `list_loader_versions` (L608) | ✅ | ✅ | data/LoaderInstall.parseLoaderBuilds + vm.fetchLoaderBuilds |
| 22 | `search_worlds` (L612) | ✅ | ✅ | data/CatalogRepo.searchWorlds（CF classId 17、人气倒序）+ 下载页「世界」分区（t-713） |
| 23 | `rename_version` (L618) | ✅ | ✅ | vm/AppViewModel.renameVersion + VersionOps.rename |
| 24 | `copy_version` (L624) | ✅ | ✅ | vm/AppViewModel.copyVersion |
| 25 | `hide_version` (L630) | ✅ | ✅ | data/VersionOps.setHidden/toggleHidden + vm.toggleVersionHidden |
| 26 | `open_version_folder` (L636) | ✅ | — | 安卓无文件管理器直开 |
| 27 | `export_launch_script` (L640) | ✅ | ✅ | vm/AppViewModel.exportLaunchScript + VersionOps.launchScript |
| 28 | `create_desktop_shortcut` (L643) | ✅ | — | 桌面快捷方式是 PC 概念 |
| 29 | `list_saves` (L648) | ✅ | ✅ | data/Saves.list |
| 30 | `delete_save` (L652) | ✅ | ✅ | data/Saves.delete |
| 31 | `backup_save` (L657) | ✅ | ✅ | data/Saves.backup |
| 32 | `list_save_backups` (L669) | ✅ | ✅ | data/Saves.listBackups |
| 33 | `restore_save_backup` (L673) | ✅ | ✅ | data/Saves.restore |
| 34 | `delete_save_backup` (L681) | ✅ | ✅ | data/Saves.deleteBackup |
| 35 | `export_save` (L686) | ✅ | ✅ | data/Saves.export + vm.exportSave |
| 36 | `open_save` (L690) | ✅ | — | 安卓无文件管理器直开 |
| 37 | `install_datapack_into_save` (L694) | ✅ | ✅ | data/Saves.installDatapack |
| 38 | `list_media` (L699) | ✅ | ✅ | data/Saves.listMedia |
| 39 | `open_media` (L703) | ✅ | ✅ | vm/AppViewModel.mediaKindOf → 应用内查看 |
| 40 | `delete_modpack` (L706) | ✅ | ✅ | vm/AppViewModel.deleteFromLibrary(kind=modpack) |
| 41 | `list_global_mods` (L723) | ✅ | ✅ | data/GlobalMods.list + ui/GlobalModsScreen 列表 + vm.reloadGlobalMods（t-711） |
| 42 | `set_global_mod_enabled` (L727) | ✅ | ✅ | data/GlobalMods.setEnabled + 全局模组页每行 Switch + vm.setGlobalModEnabled（t-711） |
| 43 | `start_nide8_login` (L733) | ✅ | ✅ | data/AuthRepo.loginNide8 |
| 44 | `catalog_favorites` (L736) | ✅ | ✅ | data/CatalogFavorites.list + 下载页收藏夹（t-713） |
| 45 | `toggle_favorite` (L739) | ✅ | ✅ | data/CatalogFavorites.toggle + vm.toggleFavorite（t-713） |
| 46 | `set_game_dir` (L759) | ✅ | ✅ | setGameDir |
| 47 | `download_java` (L776) | ✅ | ✅ | data/RuntimeInstaller.installJava |
| 48 | `terracotta_player` (L782) | ✅ | ✅ | data/TerracottaRepo.metadata / host(player) |
| 49 | `terracotta_snapshot` (L788) | ✅ | ✅ | data/TerracottaRepo.state |
| 50 | `terracotta_prepare` (L792) | ✅ | ✅ | data/TerracottaRepo.initialize |
| 51 | `terracotta_host` (L795) | ✅ | ✅ | data/TerracottaRepo.host |
| 52 | `terracotta_join` (L798) | ✅ | ✅ | data/TerracottaRepo.join |
| 53 | `terracotta_idle` (L801) | ✅ | ✅ | data/TerracottaRepo.setWaiting |
| 54 | `terracotta_allow_firewall` (L804) | ✅ | — | Windows 防火墙放行 |
| 55 | `terracotta_open_firewall_settings` (L807) | ✅ | — | Windows 防火墙设置 |
| 56 | `terracotta_shutdown` (L810) | ✅ | ✅ | data/TerracottaRepo / VpnCoordinator.shutdown |
| 57 | `terracotta_enter_world` (L813) | ✅ | ✅ | vm/MultiplayerViewModel.onEnter |
| 58 | `terracotta_direct_connect` (L820) | ✅ | ✅ | data/TerracottaCore.parseDirect（同桌面 split_join_url：自带端口 / 单填端口 / IPv6 方括号，本机地址与坏端口拦住）+ withLobby 写成多人列表「陶瓦联机大厅」首行；vm/AppViewModel.launchDirect → launchGame(server) 带 --server/--port（LaunchPlanner.serverArgs → LaunchArgs）；入口 ui/MultiplayerScreen「公网直连」卡（t-714） |
| 59 | `launch_game` (L855) | ✅ | ✅ | vm/AppViewModel.launchGame + McLaunch |
| 60 | `build_launch_command` (L866) | ✅ | ✅ | data/LaunchArgs.build |
| 61 | `start_microsoft_login` (L894) | ✅ | ✅ | data/AuthRepo.startDeviceCode / pollOnce |
| 62 | `uninstall_version` (L897) | ✅ | ✅ | vm/AppViewModel.uninstallVersion |
| 63 | `create_instance` (L903) | ✅ | ✅ | vm/AppViewModel.createInstance |
| 64 | `delete_instance` (L907) | ✅ | ✅ | vm/AppViewModel.deleteInstance |
| 65 | `rename_instance` (L911) | ✅ | ✅ | data/InstanceStore.rename |
| 66 | `open_instance_folder` (L915) | ✅ | — | 安卓无文件管理器直开 |
| 67 | `open_mods_folder` (L924) | ✅ | — | 安卓无文件管理器直开 |
| 68 | `delete_mod` (L931) | ✅ | ✅ | vm/AppViewModel.deleteMod |
| 69 | `disable_mod` (L937) | ✅ | ✅ | data/Mods.setEnabled(false) |
| 70 | `enable_mod` (L943) | ✅ | ✅ | data/Mods.setEnabled(true) |
| 71 | `get_installed_mods` (L955) | ✅ | ✅ | data/Mods.list |
| 72 | `get_installed_mod_entries` (L959) | ✅ | ✅ | data/Mods.list + summary |
| 73 | `get_mods_targets` (L965) | ✅ | ✅ | data/Mods.targets |
| 74 | `get_saves_targets` (L975) | ✅ | ✅ | data/VersionSettings.isolatedSaves + Saves.savesDir |
| 75 | `get_installed_shaders` (L986) | ✅ | ✅ | data/ContentLibrary.list(shader) |
| 76 | `get_installed_resourcepacks` (L989) | ✅ | ✅ | data/ContentLibrary.list(resourcepack) |
| 77 | `get_installed_datapacks` (L992) | ✅ | ✅ | data/ContentLibrary.list(datapack) |
| 78 | `get_installed_modpacks` (L995) | ✅ | ✅ | data/ContentLibrary.list(modpack) + ModpackRefs |
| 79 | `default_export_dir` (L1008) | ✅ | — | 安卓走 SAF 选择器，没有“默认导出目录” |
| 80 | `remember_export_dir` (L1012) | ✅ | — | 同上 |
| 81 | `export_content` (L1016) | ✅ | ✅ | data/ContentExport.write + vm.exportFromLibrary（2026-09-17 已交，带 ContentExportTest） |
| 82 | `export_contents` (L1022) | ✅ | ✅ | data/ContentExport.writeMany + bundleName + 内容库页多选/全选/批量导出 + vm.exportManyFromLibrary（t-711） |
| 83 | `delete_shader` (L1028) | ✅ | ✅ | data/ContentLibrary.delete |
| 84 | `delete_resourcepack` (L1032) | ✅ | ✅ | data/ContentLibrary.delete |
| 85 | `delete_datapack` (L1036) | ✅ | ✅ | data/ContentLibrary.delete |
| 86 | `get_setting` (L1040) | ✅ | ✅ | data/Settings.str/int/bool |
| 87 | `update_settings` (L1050) | ✅ | ✅ | data/Settings.update |
| 88 | `get_settings` (L1053) | ✅ | ✅ | data/Settings.all |
| 89 | `save_settings` (L1125) | ✅ | ✅ | data/Settings.update + flushIfDirty |
| 90 | `background_history` (L1265) | ✅ | ✅ | data/Settings.pushBackgroundHistory + WallpaperModel |
| 91 | `can_undo_background` (L1269) | ✅ | ✅ | data/WallpaperModel.undone / ThemeStore.undoBackground |
| 92 | `undo_background` (L1276) | ✅ | ✅ | data/ThemeStore.undoBackground |
| 93 | `reset_background` (L1293) | ✅ | ✅ | data/WallpaperModel.clearedToBaseColor |
| 94 | `test_ai_connection` (L1315) | ✅ | ✅ | data/AiRepo.testConnection |
| 95 | `collect_sysinfo` (L1320) | ✅ | ✅ | data/SysInfo.collect |
| 96 | `sysinfo_text` (L1324) | ✅ | ✅ | data/SysInfo.describe |
| 97 | `submit_feedback` (L1328) | ✅ | ✅ | data/FeedbackRepo.submit |
| 98 | `submit_crash_feedback` (L1335) | ✅ | ✅ | data/FeedbackRepo.submitCrash |
| 99 | `feedback_history` (L1339) | ✅ | ✅ | data/FeedbackRepo.history |
| 100 | `help_articles` (L1343) | ✅ | ✅ | data/HelpContent.search / list（6 篇，id/title/body 与 help_content.py 逐条一致，HelpContentTest 对照 Python 源）+ ui/FeedbackScreen FaqCard 搜索（9/18 t-710） |
| 101 | `help_article` (L1347) | ✅ | ✅ | data/HelpContent.get（按 id、trim、找不到 null）+ FaqCard 点标题展开正文（9/18 t-710） |
| 102 | `get_accounts` (L1351) | ✅ | ✅ | data/AuthRepo.accounts |
| 103 | `get_account_rows` (L1359) | ✅ | ✅ | data/AuthRepo.accounts + label |
| 104 | `set_account_skin` (L1376) | ✅ | ✅ | data/AuthRepo.setSkin + SkinRepo.save |
| 105 | `get_account_skin` (L1413) | ✅ | ✅ | data/SkinRepo.load |
| 106 | `remove_account` (L1427) | ✅ | ✅ | data/AuthRepo.remove / removeAndReelect |
| 107 | `set_active_account` (L1431) | ✅ | ✅ | data/AuthRepo.activate |
| 108 | `add_offline_account` (L1436) | ✅ | ✅ | data/AuthRepo.addOffline |
| 109 | `start_authlib_login` (L1443) | ✅ | ✅ | data/AuthRepo.loginAuthlib |
| 110 | `get_version_settings` (L1446) | ✅ | ✅ | data/VersionSettings.load |
| 111 | `save_version_settings` (L1450) | ✅ | ✅ | data/VersionSettings.save |
| 112 | `repair_version` (L1456) | ✅ | ✅ | vm/AppViewModel.repairVersion + VersionOps.missingFiles |
| 113 | `preflight_launch` (L1459) | ✅ | ✅ | data/Preflight.check（目录可写 / 磁盘 / 版本 json / 缺文件 / mods 解压与原版带 jar / Java 大版本 / 可用内存，同桌面 preflight.py 口径，缺文件按安卓自愈只报 warn）+ vm/AppViewModel.runPreflight；ui/LaunchScreen「启动前体检」按钮 + ui/LaunchChecks.PreflightCard 每条带「去修」：下载页 / 修复任务 / Java 页 / 内存滑到建议值 / 实例页（t-714） |
| 114 | `apply_crash_action` (L1472) | ✅ | ✅ | data/CrashActions.build/apply（桌面 build_actions 七个动作 id 原样 + 安卓 trim_memory；停用模组 / 清 JVM 参数就地执行，内存 / 修复 / Java / mods / 崩溃文件回 route）+ vm/AppViewModel.applyCrashAction；ui/LaunchChecks.CrashCard 崩溃卡下「建议操作」按钮排，崩溃报告在弹窗里看 / 复制（t-714） |
| 115 | `export_modpack` (L1557) | ✅ | ✅ | data/ModpackExport.export（mods 按 sha1 问 Modrinth 进 files、其余与 config/resourcepacks/shaderpacks/datapacks 进 overrides，索引字段同桌面 export_pack.py）+ vm/AppViewModel.exportModpack → exports/<实例>.mrpack；入口 ui/ModpackScreen「导出为 .mrpack」、ui/InstancesScreen「导出」（t-715） |
| 116 | `check_mod_updates` (L1560) | ✅ | ✅ | vm/AppViewModel.checkModUpdates + ModUpdates.check |
| 117 | `start_mod_updates` (L1564) | ✅ | ✅ | data/ModUpdates |
| 118 | `apply_mod_update` (L1567) | ✅ | ✅ | vm/AppViewModel.applyModUpdate |
| 119 | `cleaner_preview` (L1573) | ✅ | ✅ | data/Cleaner.preview + ui/CleanerCard（9/18 t-712） |
| 120 | `cleaner_apply` (L1577) | ✅ | ✅ | data/Cleaner.apply，按勾选的 kinds 删（9/18 t-712） |
| 121 | `check_update` (L1581) | ✅ | ✅ | data/UpdateCheck.check / evaluate（清单地址 update_url、12 s、版本比较与 SHA-256 拒签同 updater.py）+ checkOnStartupAsync（PyMclApp，auto_check_update 开关）+ 设置页「检查更新」按钮 / 上次检查行 / 打开下载页（9/18 t-710） |
| 122 | `start_self_update` (L1585) | ✅ | — | 安卓自更新 = 下载 APK 安装，属另一套流程 |
| 123 | `fetch_news` (L1588) | ✅ | ✅ | data/NewsRepo.fetch + vm.reloadNews + 启动页资讯卡（t-713） |
| 124 | `cached_news` (L1592) | ✅ | ✅ | data/NewsRepo.loadCached（cache/news.json，与桌面同一份）（t-713） |
| 125 | `skin_urls` (L1596) | ✅ | ✅ | data/SkinRepo.avatarUrl / bodyUrl |
| 126 | `lan_hint` (L1604) | ✅ | ✅ | data/Lan.hint |
| 127 | `local_ips` (L1608) | ✅ | ✅ | data/Lan.localIps |
| 128 | `authlib_presets` (L1612) | ✅ | ✅ | data/AuthRepo.presetApi |
| 129 | `open_global_mods` (L1616) | ✅ | ✅ | 全局模组页列出共享池绝对路径 + SAF「放入 jar」+ GlobalMods.consumers 写明对哪些版本生效（t-711，安卓拉不起外部文件管理器，为能力等价） |
| 130 | `get_version_list` (L1628) | ✅ | ✅ | data/ManifestRepo.fetch / latest |
| 131 | `fetch_version_list` (L1636) | ✅ | ✅ | data/ManifestRepo.fetch(fresh) |
| 132 | `get_installed_versions` (L1659) | ✅ | ✅ | data/InstanceStore.installedVersions |
| 133 | `game_root_name` (L1667) | ✅ | ✅ | data/Paths.instanceDir |
| 134 | `game_root_path` (L1672) | ✅ | ✅ | data/Paths.instanceDir |
| 135 | `get_instances` (L1675) | ✅ | ✅ | data/InstanceStore.list |
| 136 | `loader_of` (L1721) | ✅ | ✅ | data/VersionOps.loaderOf |
| 137 | `get_version_rows` (L1728) | ✅ | ✅ | data/VersionOps.cards |
| 138 | `get_version_isolation` (L1772) | ✅ | ✅ | data/VersionSettings.isolatedMods / isolatedSaves |
| 139 | `set_version_isolation` (L1776) | ✅ | ✅ | data/VersionSettings.setIsolation + seedFromShared |
| 140 | `toggle_version_isolation` (L1783) | ✅ | ✅ | vm/AppViewModel.toggleIsolation / setIsolationMode |
| 141 | `search_modpacks` (L1830) | ✅ | ✅ | data/CatalogRepo.searchKind(modpack) |
| 142 | `search_mods` (L1926) | ✅ | ✅ | data/CatalogRepo.searchMods |
| 143 | `search_shaders` (L2029) | ✅ | ✅ | data/CatalogRepo.searchKind(shader) |
| 144 | `search_resourcepacks` (L2032) | ✅ | ✅ | data/CatalogRepo.searchKind(resourcepack) |
| 145 | `search_datapacks` (L2035) | ✅ | ✅ | data/CatalogRepo.searchKind(datapack) |
| 146 | `get_java_list` (L2038) | ✅ | ✅ | data/JavaRuntime.scanInstalled |
| 147 | `normalize_java_pref` (L2049) | ✅ | ✅ | data/JavaRuntime.resolvePreferred |
| 148 | `get_instance_java` (L2060) | ✅ | ✅ | data/JavaRuntime.instanceJava |
| 149 | `set_instance_java` (L2063) | ✅ | ✅ | data/JavaRuntime.setInstanceJava |
| 150 | `java_combo_options` (L2066) | ✅ | ✅ | ui/JavaScreen 自己拼下拉项 |
| 151 | `java_combo_label_for` (L2080) | ✅ | ✅ | ui/JavaScreen |
| 152 | `instance_java_label` (L2087) | ✅ | ✅ | data/JavaRuntime.vendorLabel |
| 153 | `list_servers` (L2596) | ✅ | ✅ | data/Servers.list |
| 154 | `add_server` (L2601) | ✅ | ✅ | vm/AppViewModel.addServer |
| 155 | `update_server` (L2607) | ✅ | ✅ | vm/AppViewModel.updateServer |
| 156 | `delete_server` (L2612) | ✅ | ✅ | vm/AppViewModel.deleteServer |
| 157 | `import_servers` (L2617) | ✅ | ✅ | vm/AppViewModel.importServers |
| 158 | `export_servers` (L2632) | ✅ | ✅ | vm/AppViewModel.exportServers |
| 159 | `get_playtime` (L2641) | ✅ | ✅ | data/Playtime.get |
| 160 | `get_all_playtime` (L2646) | ✅ | ✅ | data/Playtime.load |
| 161 | `get_total_playtime` (L2650) | ✅ | ✅ | data/Playtime.totalOf |
| 162 | `format_playtime` (L2654) | ✅ | ✅ | vm/AppViewModel.formatPlaytime |
| 163 | `clear_playtime` (L2658) | ✅ | ✅ | vm/AppViewModel.clearPlaytime |
| 164 | `thumb_path` (L2666) | ✅ | ✅ | data/Thumbnails.thumbPath：cache/thumbs/<sha1 前 24 位><图片后缀>，与桌面 thumbnails.py 同一口径（t-715） |
| 165 | `ensure_thumb` (L2670) | ✅ | ✅ | data/Thumbnails.ensureThumb：7 天缓存、10 分钟失败冷却（上限 512 条）、batchEnsure/clearCache/cachedSize；ui/ThumbnailTile 接到下载页搜索结果图标（CatalogHit.iconUrl）与账号页头像（t-715） |
| 166 | `java_vendor_list` (L2678) | ✅ | ✅ | data/JavaRuntime.vendorKeys = adoptium / zulu / microsoft，与 Qt JAVA_VENDORS 三家原样（Qt 并没有 graal/oracle）；ui/JavaScreen 发行版行可选，RuntimeInstaller.ensureDownloaded 按所选发行版下（t-715） |
| 167 | `java_vendor_label` (L2682) | ✅ | ✅ | data/JavaRuntime.vendorLabel：显示名「Adoptium Temurin / Azul Zulu / Microsoft OpenJDK」与大小写、兜底规则同桌面 java_vendor_label（t-715） |
| 168 | `install_java` (L2686) | ✅ | ✅ | data/RuntimeInstaller.installJava |
| 169 | `get_language` (L2704) | ✅ | ✅ | data/I18n.setLanguage/current + SettingsKeys.LANGUAGE（t-647，9/18 已验收） |
| 170 | `set_language` (L2708) | ✅ | ✅ | data/I18n.setLanguage + 设置页语言卡 + 整树重建（t-647，9/18 已验收） |
| 171 | `available_languages` (L2713) | ✅ | ✅ | data/I18n.LANGUAGES（t-647，9/18 已验收） |
| 172 | `translate` (L2717) | ✅ | ✅ | 顶层 t(zh) + 叠层词表 en.android.json / zh_CN.android.json（t-647，9/18 已验收） |
| 173 | `list_themes` (L2725) | ✅ | ✅ | data/ThemeStore.list |
| 174 | `save_theme` (L2729) | ✅ | ✅ | data/ThemeStore.save |
| 175 | `load_theme` (L2733) | ✅ | ✅ | data/ThemeStore.load |
| 176 | `delete_theme` (L2740) | ✅ | ✅ | data/ThemeStore.delete |
| 177 | `import_theme` (L2744) | ✅ | ✅ | data/ThemeStore.importFrom |
| 178 | `export_theme` (L2748) | ✅ | ✅ | data/ThemeStore.exportTo |
| 179 | `get_layout` (L2759) | ✅ | ✅ | data/LayoutStore.activeDoc / profiles / defaultDoc |
| 180 | `save_layout` (L2770) | ✅ | ✅ | data/LayoutStore.saveActive |
| 181 | `save_layout_profile` (L2782) | ✅ | ✅ | data/LayoutStore.saveProfile |
| 182 | `activate_layout_profile` (L2797) | ✅ | ✅ | data/LayoutStore.activateProfile |
| 183 | `delete_layout_profile` (L2803) | ✅ | ✅ | data/LayoutStore.deleteProfile |
| 184 | `reset_layout` (L2809) | ✅ | ✅ | data/LayoutStore.resetToDefault |
| 185 | `import_layout` (L2814) | ✅ | ✅ | data/LayoutStore.importFrom + ui/LayoutSettingsScreen 已接 |
| 186 | `detect_official_launcher` (L2827) | ✅ | — | PC 官方启动器迁移 |
| 187 | `official_launcher_dir` (L2831) | ✅ | — | 同上 |
| 188 | `scan_official_versions` (L2836) | ✅ | — | 同上 |
| 189 | `migrate_official_launcher` (L2843) | ✅ | — | 同上 |
| 190 | `is_game_running` (L2881) | ✅ | ✅ | data/GameRuntime.beginSession / endSession |
| 191 | `allow_multi_instance` (L2886) | ✅ | — | 安卓一次只跑一个游戏进程 |
| 192 | `set_multi_instance` (L2889) | ✅ | — | 同上 |
| 193 | `submit_crash_report` (L2897) | ✅ | ✅ | data/FeedbackRepo.submitCrash |
| 194 | `get_launch_command` (L2909) | ✅ | ✅ | data/LaunchArgs.build |
| 195 | `get_smart_recommendation` (L2951) | ✅ | ✅ | data/SmartRecommendation.of/probe（四档 + 75% 保险，与 sysinfo 同值）+ 设置页内存卡「查看推荐 / 应用推荐」（t-877） |

