package com.pymcl.mobile.data

import com.pymcl.mobile.model.ModEntry
import java.io.File

/**
 * 全局（共享）模组池，对齐桌面 `mclauncher/global_mods.py` 与「全局 Mod」对话框。
 *
 * 桌面把 jar 攒在启动器根的 `shared/mods`，每次启动前再链进当前版本的 mods；安卓这边
 * 隔离档位本来就分两档，**没开「隔离 Mod」的版本直接读实例根的 mods**，所以共享池就是
 * [Mods.dirFor] 不带版本的那一份，不需要再链一次——链接在应用私有目录里也未必建得出来。
 *
 * 启禁与删除沿用 [Mods] 那套 `.disabled` 改名约定，这里只钉死「版本恒为空」这一点，
 * 免得页面被内容库上的「安装目标」带跑，以及补上桌面没有的 [consumers]。
 */
object GlobalMods {
    fun dir(instDir: File): File = Mods.dirFor(instDir)

    fun list(instDir: File): List<ModEntry> = Mods.list(instDir)

    fun setEnabled(instDir: File, filename: String, enabled: Boolean): File =
        Mods.setEnabled(instDir, filename, enabled)

    fun delete(instDir: File, filename: String) = Mods.delete(instDir, filename)

    fun install(instDir: File, src: File): ModEntry = Mods.install(instDir, src)

    /**
     * 会吃到这一份的已装版本：没开「隔离 Mod」的那些。
     *
     * 桌面那句「启用的 jar 会在每次启动前链到当前版本的 mods」在安卓这边不成立——
     * 开了隔离的版本各用各的，页面得把范围说清楚，否则用户会以为对谁都生效。
     */
    fun consumers(instDir: File): List<String> =
        InstanceStore.installedVersionsIn(instDir).filterNot {
            VersionSettings.isolatedMods(VersionSettings.load(instDir, it))
        }
}
