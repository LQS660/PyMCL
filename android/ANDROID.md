# PyMCL Android（B 线）

**当前状态：`0.2.0-runtime`（versionCode 2）—— 已具备真实启动链，不再是 skeleton。**
底栏 6 项、29 个 Compose 页面、83 个 data 层模块、843 个 JVM 单测（46 个测试文件）。

> 本文此前长期停留在 `0.1.0-skeleton` 的描述，与代码严重不符（文档 mtime 2026-08-23，
> 而启动链、JRE 解包、联机、AI 等模块在 09-19 之后陆续落地）。2026-09-30 按实际代码重写。
>
> 对标说明：相对 PCL2 桌面端，Android 端功能面仍有明显缺口（见「尚未具备」一节），
> 但**可以真启动游戏**，不应再按「占位产品」宣传。

## 包与色

- applicationId: `com.pymcl.mobile`（debug 后缀 `.debug`）
- 版本：`versionCode 2` / `versionName 0.2.0-runtime`
- 绿 `#2E9B6B` 白底
- 底栏 6 项（`ui/MainTab.kt:59`）：启动 / 实例 / 联机 / 下载 / AI / 我的
  - 前四项下标被硬编码依赖（`MainTab` 的 `index` 字段），**换序会跳错页**
  - 「我的」下挂二级页（`ui/MainTab.kt:89`）：账号 / Java / 设置 / 主题 / 布局 / 反馈 / 全局 Mod

## 构建形态

- 只出 **`arm64-v8a`**（`app/build.gradle.kts:35`）。理由：JRE 与 LWJGL 的 `.so` 一套几百 MB，
  多打一个 ABI 等于 APK 翻倍。
- `minSdk` / `compileSdk` / `targetSdk` 见 `gradle/libs.versions.toml`；Java 17 编译目标。
- 产物名：`PyMCL-<buildType>-<versionName>-arm64-v8a.apk`。
- JRE 只打包 **17 / 21** 两套（`filterJreAssets` 排除 `jre8` / `jre25` 与非 arm 变体），
  LWJGL natives 在 assets 合并后按 ABI 目录清理。

## 依赖 FoldCraftLauncher 源码（重要）

本模块**不是独立可编译的**：`settings.gradle.kts` 通过源码依赖引入 4 个外部子工程。

```
include(":FCLauncher")     ← FCL 的 JNI / LWJGL / GL 桥
include(":Terracotta")     ← 陶瓦联机（EasyTier / VpnService）
include(":FCLCore")        ← 上游安装器（Forge / NeoForge / Fabric / Quilt /
                              OptiFine / LiteLoader / Cleanroom + 五种整合包格式）
include(":ZipFileSystem")  ← FCLCore 的依赖，必须一起 include
```

定位规则是「先相对、再绝对」：

1. 先找 `../FoldCraftLauncher/<子工程>/build.gradle.kts`
2. 找不到则回退写死的 `D:/pymcl-work/FoldCraftLauncher/<子工程>`

换机器时改 `settings.gradle.kts` 末尾那几个常量（`app/build.gradle.kts` 顶部的
`fclRoot` / `fclLibs` / `fclAssets` / `fclJreAssets` 用的是同一套退路，也要一起改）。

> 去 FCL 化（把 4 个子工程源码迁入 `android/`、6 个 aar 收进 `app/libs/`、包名
> `com.tungsten.*` → `com.pymcl.*`）是一份独立任务书的目标，见仓库外层的
> `GOAL-android-vkboard-defcl.md`，**尚未执行**。

## 模块结构（实际）

```
app/src/main/java/com/pymcl/mobile/
├── PyMclApp.kt          Application，初始化 data 层
├── MainActivity.kt      Compose 主壳 + 底栏导航
├── GameActivity.kt      真启动：TextureView + FCLBridge JNI 链
├── JvmHostActivity.kt   第二 JVM 宿主（加载器安装器 / Jar 执行器）
├── model/Models.kt      共享数据类型
├── data/                83 个模块（见下）
└── ui/                  29 个 Screen + 主题 + 壁纸层
```

`data/` 的主要模块分组（83 个，此处列关键项）：

| 分组 | 模块 |
|---|---|
| 启动链 | `McLaunch.kt`（prepare/启动）、`LaunchPlanner.kt`（classpath 与缺失文件规划）、`LaunchArgs.kt`、`GameRuntime.kt`、`JavaRuntime.kt`、`RuntimeInstaller.kt`（解 tar.xz JRE / `unpack200` / `patchJava`，支持联网下载）、`JvmHost.kt`、`Preflight.kt` |
| 安装 | `Installer.kt`、`LoaderInstall.kt`、`ForgeProcessors.kt`、`ModpackInstall.kt`、`ModpackIndex.kt`、`ContentInstall.kt`、`HttpPackDownloader.kt`、`FclCoreCatalog.kt` |
| 实例与配置 | `Paths.kt`、`InstanceStore.kt`、`Settings.kt`、`VersionSettings.kt`、`VersionOps.kt`、`LayoutStore.kt`、`ThemeStore.kt`、`WallpaperStore.kt` |
| 内容 | `Mods.kt`、`ModUpdates.kt`、`CatalogRepo.kt`、`CatalogFiles.kt`、`Saves.kt`、`Nbt.kt`、`Servers.kt`、`ServerPing.kt`、`Cleaner.kt` |
| 账号与皮肤 | `AuthRepo.kt`、`AuthlibInjector.kt`、`SkinRepo.kt`、`SkinFile.kt`、`SkinServer.kt`、`YggdrasilRoutes.kt` |
| 联机 | `Terracotta.kt`、`TerracottaCore.kt`、`TerracottaRepo.kt`、`TerracottaVpnService.kt`、`TerracottaVpnGate.kt`、`TerracottaVpnCoordinator.kt`、`Lan.kt` |
| AI | `AiAgent.kt`（独立 agent 循环）、`AiTools.kt`、`AiToolsAndroid.kt`、`AiRepo.kt`、`AiStore.kt`、`AiConflict.kt`、`AiDiagnose.kt` |
| 其它 | `Http.kt`、`ManifestRepo.kt`、`I18n.kt`、`SysInfo.kt`、`CrashReporter.kt`、`CrashRules.kt`、`CrashActions.kt`、`Playtime.kt`、`TaskCenter.kt`、`DownloadDock.kt`、`UpdateCheck.kt`、`HelpContent.kt`、`FeedbackRepo.kt` |

## 启动链（真启动，非占位）

`data/McLaunch.kt` 的 `prepare()` 是完整路径：

1. `LaunchPlanner.resolveJson` / `plan` 算 classpath 与缺失文件
2. `JavaRuntime.javaMajor` 选 JRE → `RuntimeInstaller.ensure` 解包内置 JRE
3. `LaunchArgs.build` 拼 JVM 参数
4. `Renderer("Holy-GL4ES", ...)`
5. `FCLauncher.launchMinecraft(config)`

`GameActivity` 拿 `FCLBridge` 起 JNI 会话：`bridge.execute(Surface, this)` +
`pushEventWindow` / `pushEventKey`，回调线程切 `runOnUiThread`；退出时
`GameRuntime.endSession()` 记游玩时长、`recordExit` 做崩溃归因（保留日志尾 400 行）。

**硬限制**：`McLaunch.kt:37` 明确拒绝需要 `jre8` / `jre25` 的版本
（`当前包只带 JRE 17/21`）。所以 ≤1.16 的远古版本与最新的 Java 25 版本**跑不了**。

## 数据根

`context.filesDir/pymcl/` ≡ 桌面 `PYMCL_HOME`

```
pymcl/config.json
pymcl/accounts.json
pymcl/cache/version_manifest.json
pymcl/.minecraft/<instance>/.instance.json
```

## 网络源

- 清单：`https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json`（官方 URL 垫底）
- 社区：`https://mod.mcimirror.top/modrinth/v2`
- UA：`PyMCL/1.0.1 (android; +minecraft launcher)`

## 编译

```powershell
cd android
.\gradlew :app:compileDebugKotlin
```

辅助脚本（`android/scripts/`）：

- `build-runtime.ps1` —— robocopy 到 D 盘 + 独立 gradle 8.13 构建
- `device_regression.ps1` —— adb 真机点击 + 截图回归（**硬编码序列号 `AHSPUT2107006254`，换设备要改**）

测试：

```powershell
.\gradlew :app:testDebugUnitTest      # 843 个 @Test，跑在 JVM 上
.\gradlew :app:connectedDebugAndroidTest   # 仅 1 个 Compose 冒烟（4 例）
```

## 尚未具备（与桌面端的实际差距）

1. **没有文字输入 / 虚拟键盘** —— 全工程 `pushEventChar` / `InputConnection` /
   `ImeBridge` / `showSoftInput` 命中数为 **0**。游戏内聊天、命令、告示牌、命名都打不了字。
   这是当前最大的用户可见缺口，对应任务书 `GOAL-android-vkboard-defcl.md`（未执行）。
2. **AI 工具集落后**：Android 19 个 vs 桌面 36 个（`scripts/check_tool_parity.py` 实测，
   报告见 `docs/audit/tool-parity-latest.json`）。缺失含 `ask_user`（选择题弹窗）、
   全部 `install_*` 写入类工具、`read_artifact`、`get_latest_log` 等。
   Android 侧**无写入路径**（`AiToolsAndroid.kt` 明确写「写入类工具要过 WriteGate，本轮没有实现放行」）。
3. **i18n 词表偏小**：`assets/locales/` 约 1037 / 1027 条，桌面端为 2161 条。
4. **只支持 arm64-v8a**，且需要 JRE 17/21 的版本。
5. 无标准 Gradle 全量构建验证记录：`docs/STATUS.md` 记录标准 Gradle 曾阻塞于 AAPT2，
   现走 `build-runtime.ps1` 的 robocopy + 独立 gradle 路径绕开。

## 并行开发约定

1. `ui/` 页面与主题（不含 data）
2. `data/Http.kt` `ManifestRepo.kt` `Installer.kt`
3. `data/InstanceStore.kt` `AuthRepo.kt` `Paths.kt`
4. `data/CatalogRepo.kt` `AiRepo.kt` 对应 UI 绑定
5. `data/LaunchPlanner.kt` 测试与 `scripts/`

不要改别人正在写的文件；共享类型只放 `model/Models.kt`。
