# PyMCL Android（B 线）dev-1

独立手机启动器。第一版目标：真机可装、可拉版本清单、可下客户端、可管实例、可搜模组、可设备码登录。启动链路把 classpath 备齐；Android GL/JNI 运行时在后续里程碑接入。

## 包与色

- applicationId: `com.pymcl.mobile`
- 绿 `#2E9B6B` 白底，底栏 6 项：启动 / 实例 / 联机 / 下载 / AI / 设置；下载内横条含任务。

## 数据根

`context.filesDir/pymcl/` ≡ 桌面 `PYMCL_HOME`

```
pymcl/config.json
pymcl/accounts.json
pymcl/cache/version_manifest.json
pymcl/.minecraft/<instance>/.instance.json
```

## 源

- 清单：`https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json` 官方垫底
- 社区：`https://mod.mcimirror.top/modrinth/v2`
- UA：`PyMCL/1.0.1 (android; +minecraft launcher)`

## 文件所有权（并行）

1. `ui/` 页面与主题（不含 data）
2. `data/Http.kt` `ManifestRepo.kt` `Installer.kt`
3. `data/InstanceStore.kt` `AuthRepo.kt` `Paths.kt`
4. `data/CatalogRepo.kt` `AiRepo.kt` 对应 UI 绑定
5. `data/LaunchPlanner.kt` 测试与 `scripts/`

不要改别人正在写的文件；共享类型只放 `model/Models.kt`。
