# -*- coding: utf-8 -*-
"""Qt 控件存活检查：异步回调不得打到已销毁 / 已关闭的对话框。"""


def widget_alive(widget) -> bool:
    if widget is None:
        return False
    try:
        from shiboken6 import isValid
        if not isValid(widget):
            return False
    except Exception:
        pass
    if bool(getattr(widget, "_dismissed", False)):
        return False
    try:
        widget.objectName()
    except RuntimeError:
        return False
    return True


def guard(widget, fn):
    """包装 call_async 回调：控件已毁或对话框已关则丢弃结果。"""

    def wrapped(*args, **kwargs):
        if not widget_alive(widget):
            return None
        return fn(*args, **kwargs)

    return wrapped


def drop_if_gone(fn):
    """异步回调的收尾护栏：结果回来时控件已经析构了，就当这次调用没发生过。

    `guard(widget, fn)` 是先问再做，前提是调用方手里正好有那个控件；这一层
    是事后兜底 —— 回调多半是个闭包，碰的控件不止一个，事先问不过来。两者
    不冲突，能先问的还是该先问。

    不兜底的下场是这样的：后台线程回来时发起调用的那一页早被关掉 / 重建掉，
    回调里随便碰一下控件就抛 `RuntimeError: Internal C++ object already
    deleted`；它是从 Qt 事件循环里冒出来的，调用栈上没有任何人接得住，
    只能进错误日志 —— pymcl-error.log 里那一批就是这么来的。

    只咽下 shiboken 那句「C++ 对象已销毁」。别的 RuntimeError 照常往上抛：
    一起吃掉的话，真正的 bug 就再没人看得见了。
    """

    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RuntimeError as exc:
            if "already deleted" not in str(exc):
                raise
            from mclauncher.utils import log
            log.debug("异步回调的控件已销毁，丢弃这次结果: %s", exc)
            return None

    return wrapped
