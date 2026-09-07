# PyMCL Android（B 线）独立骨架

**当前状态：UI / 数据层骨架（0.1.0-skeleton），不是完整启动器。**
可编译的独立 Kotlin 应用，不依赖外部 `FoldCraftLauncher` / `:FCLauncher`。
Compose 底栏与仓库类已就位；**不能**像 PCL / 桌面 PyMCL 一样完整装版、启动游戏（GL/JNI / classpath 真启动在后续里程碑）。

> 对标说明：相对 PCL2 桌面端，Android 端属于「占位产品」，请勿按完整启动器宣传。

## 包与色

- applicationId: `com.pymcl.mobile`
- 版本：`0.1.0-skeleton`
- 绿 `#2E9B6B` 白底，底栏 6 项：启动 / 实例 / 联机 / 下载 / AI / 设置

## 模块结构

```
app/src/main/java/com/pymcl/mobile/
├── PyMclApp.kt          Application，初始化 data 层
├── MainActivity.kt      Compose 主壳 + 底栏导航
├── GameActivity.kt      运行时占位（提示后续接入）
├── model/Models.kt      共享数据类型
├── data/
│   ├── Paths.kt         数据根路径
│   ├── Http.kt          OkHttp 客户端与 API 常量
│   ├── ManifestRepo.kt  版本清单拉取/缓存
│   ├── InstanceStore.kt 实例与 config/accounts 读写
│   ├── AuthRepo.kt      账号（离线/设备码占位）
│   ├── CatalogRepo.kt   Modrinth 搜索
│   ├── AiRepo.kt        AI 对话占位
│   └── LaunchPlanner.kt 启动计划与下载任务占位
└── ui/                  各 Screen 占位
```

## 数据根

`context.filesDir/pymcl/` ≡ 桌面 `PYMCL_HOME`

```
pymcl/config.json
pymcl/accounts.json
pymcl/cache/version_manifest.json
pymcl/.minecraft/<instance>/.instance.json
```

## 网络源（已实现常量，部分逻辑为 stub）

- 清单：`https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json`（官方 URL 垫底）
- 社区：`https://mod.mcimirror.top/modrinth/v2`
- UA：`PyMCL/1.0.1 (android; +minecraft launcher)`

## 编译

```powershell
cd android
.\gradlew :app:compileDebugKotlin
```

Gradle 仅 `include(":app")`；已移除 `project(":FCLauncher")`、FCL aar 与 jreAssets 合并逻辑。

## 后续里程碑

1. 链接 FCL / FoldCraftLauncher 模块与 native 库
2. `GameActivity` 接入 GL 表面与 JNI 启动链
3. `LaunchPlanner` 补齐 classpath 安装与真启动
4. `AuthRepo` 设备码 OAuth 流程
5. 下载页客户端/资源安装器（原 `Installer.kt`）

## 并行开发约定（不变）

1. `ui/` 页面与主题（不含 data）
2. `data/Http.kt` `ManifestRepo.kt` `Installer.kt`
3. `data/InstanceStore.kt` `AuthRepo.kt` `Paths.kt`
4. `data/CatalogRepo.kt` `AiRepo.kt` 对应 UI 绑定
5. `data/LaunchPlanner.kt` 测试与 `scripts/`

不要改别人正在写的文件；共享类型只放 `model/Models.kt`。
