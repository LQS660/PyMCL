# UI 全量审计笔记 2026-09-19(工作区状态:fix-8items 分支,含未提交修改)

审计范围:app/ 全部 41 个 .py 文件,共 20,173 行。
辅助:两个后台子代理(mclauncher 契约审计 + 静态检查/测试验证)。

## 逐文件通读记录

## 已确认疑点(根目录部分,待最终定级)

1. [P2] main_window.py:924 `_pin_nav` 把 seq 过滤成 `[k for k in seq if k in _TOP_KEYS]` 再写 ui_nav_order,刚固定的子页 key 被丢掉,注释承诺的"落点位置持久"不成立;对照 `_write_sidebar_sequence`(main_window.py:811)才是正确写法。
2. [P2] backend.py:867 `launch_game` 标题 `f"启动游戏 {version}"` 未走 tr(),而 backend.py:327 `is_download_title` 与 main_window.py:1941 `_notify_task` 都拿 `tr("启动游戏")` 做 startswith 前缀匹配 → 非中文界面下启动任务会被计成下载任务(角标虚增)、完成时会弹多余 InfoBar。
3. [P3] backend.py:574/865/877/2126/2299 等多处 `loader: str = tr("无")`、`java: str = tr("自动选择")` 默认参数在模块导入时求值一次,运行时切语言后默认值仍是旧语言。
4. [P3] backend.py:1141 save_settings 里 first_run 缺省 False(get_settings 缺省 True),键不存在时语义不一致;另 :1174 `int(data.get("download_threads") or ...)` 用户填 0/空会被静默吞掉回默认。
5. [P3] main_window.py:977 `self.backend._download_task_count()`、:1914 `self.backend._last_installed` 越界访问 backend 私有成员。
6. [P3] backend.py:843 `_launch_into_server` 里 `(inst.versions_dir()/vid).stat().st_mtime` 若版本目录竞态删除会 FileNotFoundError 未捕获。
7. [P3] widgets.py:205 `pick_color` 用内建 hash(name),Python 进程级哈希随机化导致同一名称每次启动颜色不同(非确定)。
8. [P3] backend.py:2472-2474 强杀游戏(worker._cancelled)后 return None,BadckWorker.run 把 None 兜成"任务完成",提示语义错误。

## pages/ 部分补充发现

9. [P1] ai_page.py AgentThread 退出通道缺失:AgentThread 阻塞在 `_confirm_ev.wait()`(无超时, ai_page.py:209)或 HTTP 轮询里;它 parent 是 AiPage、不在 backend._workers/_bg_threads 里,MainWindow.closeEvent(只调 backend.shutdown/terracotta/feedback)不会 cancel 它 → 关闭启动器时若 AI 正在运行/等确认,线程永远不结束,进程退出被拖住(控制台进程不退出/无响应),QThread 运行中被销毁还有崩溃风险。settings/launch 关闭路径同理。已核实 `_confirm_ev.wait()` 无超时参数。
10. [P2] backend.py:867 `launch_game` 标题 `f"启动游戏 {version}"` 未 tr();已核实 en.json 含 "启动游戏"->"Launch Game" 且 main.py:559 init_language() 会应用英文 → 英文界面下 is_download_title/_notify_task 的 startswith(tr("启动游戏")) 全部落空:启动游戏被计入下载角标、进底部下载条、完成时弹多余 InfoBar。
11. [P3] ai_page.py:1071 `settings["ai_session_id"]=...` 直接改写 backend.get_settings() 的共享缓存字典(污染直到 CONFIG revision 变化)。
12. [P3] ai_page.py:35-44 模块级 `_STOP/_CHIPS/_WELCOME`、catalog_page MOD_SPEC 等 spec 字典、java_page.NOTES、first_run HIGHLIGHTS 经 tr() 在 import 时求值一次;且 AiPage 懒加载构造一次常驻 → 运行时切语言(设置页提示重启才生效)残留旧语言,属设计取舍,但 `_STOP`/`_CHIPS` 属于运行期比对/快捷入口,重启前语义不跟随。
13. [P3] ai_page.py:964 删除对话无确认框,误触即丢整段历史。
14. [P3] launch_page.py:604 `_on_launch` 在 UI 线程同步跑 preflight(会跑 `java -version` 子进程/扫盘),弱机上点启动有可感知卡顿;后台 worker 里还会再跑一遍(重复开销)。
15. [P3] settings_page.py:929-936 `_restart_launcher` 用 `startDetached(sys.executable, sys.argv)`,冻结 exe 下 argv[0] 会被再当参数传一遍(冗余但通常无害)。
16. [P3] servers_page.py:169/187/211/228 等多处 InfoBar 消息漏 tr()(187 还是无占位符的 f-string);settings_page.py:562 主目录标签未 tr()。
17. [P3] backend.py save_settings 的 first_run 缺省 False 与 get_settings 缺省 True 不一致(实际影响小:boot 时必然已物化该键);backend.py 多处 fallback "none" 与出厂 default_isolation="all" 不一致(仅值为空字符串时触发)。已核实 config.py:81 出厂即 "all"。
18. [P3] backend.py:1174/1175 `int(data.get("download_threads") or ...)` 把合法的 0 当 falsy 吞掉(settings 里有下限校验,风险低)。
19. [P3] main_window.py:1908/1913 `loader: str = tr("无")` 默认参数 import 时冻结(i18n 家族问题,同 backend.py:574/865/877)。

## 静态检查子代理结论(已合并)
- 41 文件 py_compile 全过;451 测试可收集;tests/test_ai_think_fold.py 8/8 过。
- P2: backend.py:1566-1579 reset_jvm_args 吞错后仍报"已清空"(版本 settings 读写失败时谎报成功)。
- P3: servers_page.py:187 f-string 无占位符+漏 tr;backend.py:2366 launch_flow 重复导入;layout_model.py 星号导入;22 处未使用 import;pcl_chrome.py:13 直接 import qframelesswindow 未在 requirements 声明(传递依赖);47 处 except-pass 抽查均良性。
- 无裸 except / QThread.terminate / UI线程 time.sleep / waitForFinished / TODO;open() 全部带 encoding 或二进制;PySide6>=6.6 无枚举兼容风险。
