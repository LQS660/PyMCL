"""检查还原后的 C# 文件里是否还有残留损坏。

编译器只保证标识符正确，字符串字面量和注释里的错字它一概不管，
而这次损坏恰好会把 run→rue、Text→hext、Path→yath 这类词留在字面量里。
这里把字面量和注释单独抽出来，按「含可疑字母组合的英文词」报出来人工过一遍。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = [
    ROOT / "winui3/PyMCL.WinUI/Pages/AiPage.xaml.cs",
    ROOT / "winui3/PyMCL.WinUI/Pages/InstancePage.xaml.cs",
    ROOT / "winui3/PyMCL.WinUI/Pages/JavaPage.xaml.cs",
]

STRING_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')
COMMENT_RE = re.compile(r"//.*?$|/\*.*?\*/", re.MULTILINE | re.DOTALL)
ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z_]{2,}")

# 损坏后才可能出现的字母组合；正常英文里极少见
SUSPECT = [
    re.compile(r"ee(?![a-z]*(?:n|d\b))"),   # run→rue、open→opee
    re.compile(r"^h[a-z]"),                  # Text→hext、Title→hitle
    re.compile(r"^y[a-z]"),                  # Path→yath、Primary→yrimary
    re.compile(r"eg\b"),                     # -ing→-ieg
]

# 正常出现、不要误报的词
ALLOW = {
    "see", "seen", "been", "free", "three", "green", "need", "needs", "keep",
    "feed", "week", "deep", "speed", "screen", "between", "agree", "queue",
    "deepseek", "here", "there", "where", "these", "the", "then", "they",
    "have", "has", "hide", "hidden", "help", "http", "https", "html", "hash",
    "height", "hover", "handle", "header", "yes", "your",
}


def main():
    total = 0
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        chunks = [(m.start(), m.group(0)) for m in STRING_RE.finditer(text)]
        chunks += [(m.start(), m.group(0)) for m in COMMENT_RE.finditer(text)]
        hits = []
        for pos, chunk in chunks:
            line = text.count("\n", 0, pos) + 1
            for word in ASCII_WORD_RE.findall(chunk):
                if word.lower() in ALLOW:
                    continue
                if any(rx.search(word) for rx in SUSPECT):
                    hits.append((line, word, chunk.strip()[:90]))
        print(f"\n=== {path.name} ===")
        if not hits:
            print("  未发现可疑残留")
        for line, word, ctx in sorted(set(hits)):
            print(f"  行 {line}: [{word}]  {ctx}")
            total += 1
    print(f"\n合计可疑 {total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
