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
