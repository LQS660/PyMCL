# -*- coding: utf-8 -*-
"""扫一遍 app/：Qt 控件的 parent 有没有漏给。

两类漏传，症状完全不是一回事：

- **当场崩**：`MessageBoxBase` 一系的 `MaskDialogBase.__init__` 要照着 parent 的尺寸
  铺遮罩，那句 `parent.width()` 碰上 None 直接抛 AttributeError，用户点的动作断在
  半路；`StateToolTip.getSuitablePos()` 里的 `self.parent().width()` 同理。
- **不崩但看不见**：`InfoBarManager.add()` 看见 parent 为 None 就直接 return，
  提示条既不排队也不定位，飘成一个没人管的顶层窗口——只有肉眼能发现。

两种都不挑运行时机、不写日志，只有点到那个按钮的人才撞得上，所以在提交前静态兜一遍。

**`TeachingTip` 和 `Flyout` 故意不在名单里。** 它们靠 `target` 定位、parent 只是可选的
归属窗口，库里对 parent 的引用都带着判空（`teaching_tip.py:202` 那句
`if self.parent() and …`），不给也照样正常弹。把它们也判成错，这道卡口很快就会被
当成噪音绕过去。

纯标准库，不导入 Qt，pre-commit / CI 里都能直接跑：

    python scripts/check_qt_parent.py [根目录]

有漏传时退出码为 1，并逐条打出 `文件:行号`。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[1]

# 框架自带的对话框基类：本地类继承到它们（或继承到这样的本地类）就算对话框。
DIALOG_BASES = {"MessageBoxBase", "MaskDialogBase", "MessageBox", "Dialog"}
# 直接用的框架对话框，parent 排第几个位置参（不含 self）：MessageBox(title, content, parent)
EXTERNAL_DIALOGS = {"MessageBox": 2, "Dialog": 2}
# 非对话框、但同样会崩在 parent 上的：StateToolTip(title, content, parent)
CRASHY_WIDGETS = {"StateToolTip": 2}
# InfoBar.成功/失败/… 的 parent 位置：(title, content, orient, isClosable, duration, position, parent)
INFOBAR_METHODS = {"success": 6, "info": 6, "warning": 6, "error": 6, "new": 7}
# InfoBar 直接实例化时前面多一个 icon
INFOBAR_CTOR_SLOT = 7


class Violation(NamedTuple):
    path: Path
    line: int
    name: str
    kind: str  # "dialog" | "infobar"

    def render(self, root: Path) -> str:
        try:
            where = self.path.relative_to(root)
        except ValueError:
            where = self.path
        return f"{where}:{self.line}  {self.name}(...)  missing parent"


def parse_tree(path: Path) -> ast.Module:
    # utf-8-sig 而不是 utf-8：带 BOM 的文件读成 utf-8 会在开头留下 U+FEFF，
    # ast.parse 当场 SyntaxError——卡口本该报漏传，结果糊一脸 traceback。
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def load_trees(root: Path) -> dict[Path, ast.Module]:
    return {p: parse_tree(p) for p in sorted(root.rglob("*.py"))}


def _parent_slot(cls: ast.ClassDef):
    """这个类的 `__init__` 把 parent 放在第几个位置参（不含 self）。

    返回 `(位置, 自己写了没)`。只能按关键字给的（keyword-only）位置记 None。
    """
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name != "__init__":
            continue
        names = [a.arg for a in fn.args.args]
        if "parent" in names:
            return names.index("parent") - 1, True
        if "parent" in [a.arg for a in fn.args.kwonlyargs]:
            return None, True
        return None, False
    return None, False


def collect_dialogs(trees: dict[Path, ast.Module]) -> dict[str, int | None]:
    """本地所有对话框类 → parent 的位置。反复扫到不再有新类为止（吃得下多层继承）。"""
    found: dict[str, int | None] = {}
    while True:
        grew = False
        for tree in trees.values():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or node.name in found:
                    continue
                bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
                bases |= {b.attr for b in node.bases if isinstance(b, ast.Attribute)}
                if not (bases & DIALOG_BASES or bases & set(found)):
                    continue
                slot, own = _parent_slot(node)
                if not own:
                    # 自己没写 __init__，就跟基类同一套；框架基类是 (self, parent)
                    inherited = [found[b] for b in bases if b in found]
                    slot = inherited[0] if inherited else 0
                found[node.name] = slot
                grew = True
        if not grew:
            return found


def _given(node: ast.Call, slot: int | None) -> bool:
    """这一处调用到底给没给 parent。看不出来的（*args / **kwargs）一律算给了。"""
    if any(k.arg == "parent" for k in node.keywords):
        return True
    if slot is not None and len(node.args) > slot:
        return True
    if any(k.arg is None for k in node.keywords):
        return True
    return any(isinstance(a, ast.Starred) for a in node.args)


def _lookup(func: ast.expr, dialogs: dict[str, int | None]):
    """这个被调用的名字归不归我们管 → (显示名, parent 位置, 类别)，不管就 None。"""
    if isinstance(func, ast.Name):
        name = func.id
        if name in dialogs:
            return name, dialogs[name], "dialog"
        if name in EXTERNAL_DIALOGS:
            return name, EXTERNAL_DIALOGS[name], "dialog"
        if name in CRASHY_WIDGETS:
            return name, CRASHY_WIDGETS[name], "widget"
        if name == "InfoBar":
            return name, INFOBAR_CTOR_SLOT, "infobar"
        return None
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id == "InfoBar" and func.attr in INFOBAR_METHODS):
        return f"InfoBar.{func.attr}", INFOBAR_METHODS[func.attr], "infobar"
    return None


def scan_calls(path: Path, tree: ast.Module, dialogs: dict[str, int | None]) -> list[Violation]:
    """这棵树里所有没给 parent 的构造点。"""
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        hit = _lookup(node.func, dialogs)
        if hit is None:
            continue
        name, slot, kind = hit
        if not _given(node, slot):
            bad.append(Violation(path, node.lineno, name, kind))
    return bad


def scan(root: Path) -> tuple[list[Violation], dict[str, int | None], int]:
    """扫整棵目录树 → (漏传清单, 认出来的对话框类, 检查过的构造点总数)。"""
    trees = load_trees(root)
    dialogs = collect_dialogs(trees)
    bad, total = [], 0
    for path, tree in trees.items():
        bad += scan_calls(path, tree, dialogs)
        total += sum(1 for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and _lookup(n.func, dialogs) is not None)
    return sorted(bad, key=lambda v: (str(v.path), v.line)), dialogs, total


def main(argv: list[str]) -> int:
    # 打出去的字一律 ASCII。pre-commit 把钩子输出当 UTF-8 字节原样转写，而这个项目的
    # 用户多半开着 GBK 控制台（requirements.txt 顶上那条注释就是为这个留的），中文到
    # 那儿是一屏乱码——偏偏这几行正是用来告诉人哪个文件第几行的。
    root = Path(argv[1]).resolve() if len(argv) > 1 else REPO / "app"
    if not root.is_dir():
        print(f"no such directory: {root}", file=sys.stderr)
        return 2
    try:
        bad, dialogs, total = scan(root)
    except SyntaxError as e:
        # 改到一半的文件也会走到这儿。给一行能直接跳过去的位置，别甩 traceback。
        print(f"{e.filename}:{e.lineno}: cannot parse: {e.msg}", file=sys.stderr)
        return 2
    print(f"scanned {root}: {len(dialogs)} dialog classes, {total} construction sites")
    if not bad:
        print("OK - every one of them passes a parent")
        return 0
    print(f"\n{len(bad)} widget(s) constructed without a parent:", file=sys.stderr)
    for v in bad:
        print("  " + v.render(root.parent), file=sys.stderr)
    print("\nDialogs and StateToolTip crash outright in parent.width(); InfoBar does not "
          "crash\nbut is never queued or positioned. Fix: pass parent=self.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
