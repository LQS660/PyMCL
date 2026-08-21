# -*- coding: utf-8 -*-
"""把 app/ 下的中文界面字面量批量包成 tr("...")，并抽出待翻译词条。

为什么用 tr 而不是常见的 _：`_` 在本项目里有 40 处被当丢弃变量用
（`path, _ = QFileDialog...` / `lambda _: ...` / `for _ in ...`），
一旦 `_` 是 i18n 函数就会被局部赋值遮蔽，后面再调用直接 TypeError。

安全前提：语言包以**中文原文本身**作为 key，zh_CN 是恒等映射，
所以在中文（默认语言）下 tr(s) == s，包装不改变任何现有行为。

用法：
    python _i18n_wrap.py --dry-run   # 只报告，不写文件
    python _i18n_wrap.py             # 实际改写
    python _i18n_wrap.py --dump-keys keys.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")
TARGET_DIR = Path("app")
IMPORT_LINE = "from mclauncher.i18n import tr"
# 这些调用的实参是内部标识/样式表，不是给人看的
SKIP_CALLS = {"setObjectName", "setStyleSheet", "setProperty", "findChild"}


class Collector(ast.NodeVisitor):
    def __init__(self):
        self.targets: list[ast.Constant] = []
        self._skip: set[int] = set()

    def _mark_subtree(self, node):
        for child in ast.walk(node):
            if isinstance(child, ast.Constant):
                self._skip.add(id(child))

    def visit_JoinedStr(self, node):
        # f-string 的字面量片段不能单独包，整段留给人工处理
        self._mark_subtree(node)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = ""
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        if name in SKIP_CALLS:
            for arg in node.args:
                self._mark_subtree(arg)
        elif name == "tr":
            self._mark_subtree(node)
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and CJK.search(node.value) and id(node) not in self._skip:
            self.targets.append(node)
        self.generic_visit(node)


def _docstring_nodes(tree) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            out.add(id(body[0].value))
    return out


def _line_starts(data: bytes) -> list[int]:
    """行首的字节偏移。ast 的 col_offset 是 UTF-8 字节偏移，不是字符下标，
    中文行按字符切会整体错位，所以整个改写都在 bytes 上做。"""
    starts, pos = [0], 0
    for line in data.splitlines(keepends=True):
        pos += len(line)
        starts.append(pos)
    return starts


def _import_insert_line(tree) -> int:
    """返回插入 import 的行号（0 基）。放在最后一个顶层 import 之后。"""
    last = None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node
    if last is not None:
        return last.end_lineno
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
        return tree.body[0].end_lineno
    return 0


def process(path: Path, write: bool) -> tuple[int, set[str]]:
    raw = path.read_bytes()
    tree = ast.parse(raw)
    collector = Collector()
    collector.visit(tree)
    skip_docs = _docstring_nodes(tree)
    targets = [n for n in collector.targets if id(n) not in skip_docs]
    if not targets:
        return 0, set()

    starts = _line_starts(raw)
    spans = []
    phrases = set()
    for node in targets:
        begin = starts[node.lineno - 1] + node.col_offset
        end = starts[node.end_lineno - 1] + node.end_col_offset
        spans.append((begin, end))
        phrases.add(node.value)

    out = raw
    for begin, end in sorted(spans, reverse=True):
        out = out[:begin] + b"tr(" + out[begin:end] + b")" + out[end:]

    if IMPORT_LINE.encode() not in out:
        lines = out.splitlines(keepends=True)
        at = _import_insert_line(ast.parse(out))
        lines.insert(at, IMPORT_LINE.encode() + b"\n")
        out = b"".join(lines)

    ast.parse(out)  # 语法自检，改坏就直接抛
    if write:
        path.write_bytes(out)
    return len(spans), phrases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dump-keys")
    args = ap.parse_args()

    total = 0
    all_phrases: set[str] = set()
    for path in sorted(TARGET_DIR.rglob("*.py")):
        try:
            n, phrases = process(path, write=not args.dry_run)
        except SyntaxError as exc:
            print(f"[跳过] {path}: {exc}")
            continue
        if n:
            total += n
            all_phrases |= phrases
            print(f"{n:5d}  {path}")
    print("---")
    print(f"包装 {total} 处，去重词条 {len(all_phrases)} 条"
          + ("（dry-run，未写文件）" if args.dry_run else ""))
    if args.dump_keys:
        Path(args.dump_keys).write_text(
            json.dumps(sorted(all_phrases), ensure_ascii=False, indent=2), "utf-8")
        print(f"词条已导出到 {args.dump_keys}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
