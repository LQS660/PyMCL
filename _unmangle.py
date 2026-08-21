"""把被 n->e / T->h 字符替换损坏的 C# 文件还原回去。

损坏只动了两个 ASCII 字母，缩进 / 中文 / 注释 / 标点全部完好，
所以按「标识符词」逐个反解即可：对每个含 e 或 h 的词枚举所有还原候选，
用项目里未损坏的 C# 文件建出来的词表挑唯一命中的那个。
"""
import collections
import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WINUI = ROOT / "winui3" / "PyMCL.WinUI"
BROKEN = {"InstancePage.xaml.cs", "JavaPage.xaml.cs", "AiPage.xaml.cs"}

CSHARP_KEYWORDS = """
abstract as base bool break byte case catch char checked class const continue decimal default
delegate do double else enum event explicit extern false finally fixed float for foreach goto if
implicit in int interface internal is lock long namespace new null object operator out override
params private protected public readonly ref return sbyte sealed short sizeof stackalloc static
string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual
void volatile while var async await dynamic get set value when where yield nameof partial record
init global not and or with file required scoped
""".split()

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# 每个受损文件被替换掉的字母对不一样（取决于当时那条命令里被误当成字符的字符串），
# 实测有 n→e、T→h、P→y 三组。统一按并集反解：多给的自由度由词表兜住。
SUBS = {"e": "n", "h": "T", "y": "P"}


DLL = WINUI / "bin" / "Debug" / "net8.0-windows10.0.19041.0" / "win-x64" / "PyMCL.WinUI.dll"


def build_vocab():
    """收集可信标识符及频次。

    三个来源：未损坏的 .cs、XAML（`Orientation.Horizontal` 这类只在 XAML 出现的名字），
    以及最后一次成功编译产出的 DLL —— 它的元数据里就有这三个损坏文件自己定义的成员名
    （`AddBubble` / `BuildNewCard` / `IconBtn` …）和 RPC 方法名字符串，别处找不到。
    """
    freq = collections.Counter()
    for path in WINUI.rglob("*.cs"):
        if any(part in ("obj", "bin") for part in path.parts):
            continue
        if path.name in BROKEN:
            continue
        freq.update(TOKEN_RE.findall(path.read_text(encoding="utf-8", errors="replace")))

    for path in WINUI.rglob("*.xaml"):
        if any(part in ("obj", "bin") for part in path.parts):
            continue
        freq.update(TOKEN_RE.findall(path.read_text(encoding="utf-8", errors="replace")))

    # 后端 RPC 方法名是 snake_case 字符串字面量（"get_java_list" 之类），
    # C# 侧只出现在这些损坏文件里，权威定义在 Python 桥接层。
    for py in (ROOT / "bridge" / "api.py", ROOT / "bridge" / "server.py"):
        if py.exists():
            freq.update(TOKEN_RE.findall(py.read_text(encoding="utf-8", errors="replace")))

    if DLL.exists():
        blob = DLL.read_bytes()
        # 元数据串按 UTF-8 存放，UTF-16 的用户字符串串堆按 \x00 交错，两种都捞一遍
        for decoded in (blob.decode("utf-8", "ignore"),
                        blob.decode("utf-16-le", "ignore")):
            for tok in TOKEN_RE.findall(decoded):
                if len(tok) >= 2:
                    freq[tok] += 1

    for kw in CSHARP_KEYWORDS:
        freq[kw] += 100000
    return freq


def recorrupt(text):
    """把文本重新打回损坏原态。

    损坏是确定性的字符替换，所以对「已部分修好」的文本再打一次，结果与当初那份
    损坏文件一致。据此可以丢掉上一轮的半成品、每次都从同一个起点干净重跑。
    """
    for dst, src in SUBS.items():
        text = text.replace(src, dst)
    return text


def candidates(word):
    """枚举该词所有可能的还原结果：每个 e/h/y 都可能是被替换掉的 n/T/P。"""
    slots = [i for i, ch in enumerate(word) if ch in SUBS]
    if len(slots) > 14:          # 组合爆炸保护，这种超长词交给人工
        return [word]
    out = []
    for picks in itertools.product([False, True], repeat=len(slots)):
        chars = list(word)
        for idx, restore in zip(slots, picks):
            if restore:
                chars[idx] = SUBS[word[idx]]
        out.append("".join(chars))
    return out


def unmangle(text, freq):
    ambiguous, unresolved = [], []

    def fix(match):
        word = match.group(0)
        if "e" not in word and "h" not in word:
            return word
        scored = [(freq[c], c) for c in candidates(word) if freq[c] > 0]
        if not scored:
            unresolved.append(word)
            return word
        scored.sort(key=lambda x: (-x[0], x[1] != word))
        best_count, best = scored[0]
        tied = [c for n, c in scored if n == best_count]
        if len(tied) > 1:
            ambiguous.append((word, tied))
            # 并列时优先取「有还原动作」的那个，原样保留通常是巧合命中
            best = next((c for c in tied if c != word), best)
        return best

    return TOKEN_RE.sub(fix, text), ambiguous, unresolved


def main():
    freq = build_vocab()
    print(f"词表规模: {len(freq)} 个标识符\n")
    for name in sorted(BROKEN):
        path = next(WINUI.rglob(name))
        original = recorrupt(path.read_text(encoding="utf-8", errors="replace"))
        fixed, ambiguous, unresolved = unmangle(original, freq)
        changed = sum(1 for a, b in zip(original, fixed) if a != b)
        path.write_text(fixed, encoding="utf-8")
        print(f"{name}: 改回 {changed} 个字符")
        if ambiguous:
            print(f"  歧义 {len(ambiguous)} 处: {ambiguous[:12]}")
        if unresolved:
            print(f"  词表未命中 {len(unresolved)} 处: {sorted(set(unresolved))[:20]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
