# -*- coding: utf-8 -*-
"""从现有录屏剪一条 PyMCL 宣传片。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FF = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FP = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
PY = ROOT / "tools" / "venv" / "Scripts" / "python.exe"
QQ = ROOT / "raw" / "qq.mp4"
WORK = ROOT / "out" / "_work"
OUT = ROOT / "out" / "pymcl-promo.mp4"
FONT = Path(r"C:\Windows\Fonts\msyh.ttc")
FONTB = Path(r"C:\Windows\Fonts\msyhbd.ttc")
if not FONTB.exists():
    FONTB = FONT
BRAND = "0x2E9B6B"
SCALE = (
    "scale=1920:1080:force_original_aspect_ratio=increase,"
    "crop=1920:1080,fps=30,format=yuv420p"
)
ENC = [
    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
]


def run(cmd, **kw):
    print("+", " ".join(str(x) for x in cmd[:8]), "...", flush=True)
    subprocess.check_call(cmd, **kw)


def ff(*args):
    run([str(FF), "-y", "-hide_banner", "-loglevel", "error", *args])


def draw(text: str, size=42, y="h-96"):
    t = (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
    font = str(FONTB).replace("\\", "/").replace(":", "\\:")
    return (
        f"drawtext=fontfile='{font}':text='{t}':fontsize={size}:"
        f"fontcolor=white:borderw=2:bordercolor=0x1E7A52:"
        f"x=(w-text_w)/2:y={y}:shadowcolor=black@0.35:shadowx=0:shadowy=2"
    )


def tts(text: str, dest: Path, rate="+8%"):
    run([
        str(PY), "-m", "edge_tts",
        "--voice", "zh-CN-YunxiNeural",
        "--rate", rate,
        "--text", text,
        "--write-media", str(dest),
    ])


def title(path: Path, dur: float, main: str, sub: str):
    font = str(FONTB).replace("\\", "/").replace(":", "\\:")
    vf = (
        f"color=c={BRAND}:s=1920x1080:d={dur}:r=30,"
        f"drawtext=fontfile='{font}':text='{main}':fontsize=96:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-40,"
        f"drawtext=fontfile='{font}':text='{sub}':fontsize=40:fontcolor=white@0.92:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+70,format=yuv420p"
    )
    ff(
        "-f", "lavfi", "-i", vf,
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", str(dur),
        *ENC,
        "-shortest",
        str(path),
    )


def cut_qq(start: float, end: float, cap: str, dest: Path):
    vf = f"{SCALE},{draw(cap)}"
    ff(
        "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(QQ),
        "-vf", vf,
        "-af", "volume=0.12,aformat=sample_rates=48000:channel_layouts=stereo",
        *ENC,
        str(dest),
    )


def dur(path: Path) -> float:
    out = subprocess.check_output([
        str(FP), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nokey=1:noprint_wrappers=1", str(path),
    ], text=True)
    return float(out.strip())


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    if not QQ.is_file():
        raise SystemExit(f"missing {QQ}")
    if not FF.is_file():
        raise SystemExit(f"missing {FF}")

    lines = [
        ("vo1.mp3", "不会点菜单，直接说人话。"),
        ("vo2.mp3", "装钠和光影，它自己搜。"),
        ("vo3.mp3", "列出选项，先让你点确认。"),
        ("vo4.mp3", "勾上就能下。"),
        ("vo5.mp3", "任务已经在跑了。"),
        ("vo6.mp3", "PyMCL，你说话，它替你点完那些菜单。"),
    ]
    for name, text in lines:
        dest = WORK / name
        if dest.is_file() and dest.stat().st_size > 1000:
            print("skip tts", name, flush=True)
            continue
        tts(text, dest)

    title(WORK / "t0.mp4", 2.4, "PyMCL", "用嘴装游戏")
    cut_qq(0.45, 8.90, "说一句：装钠和光影", WORK / "c1.mp4")
    cut_qq(13.40, 21.20, "自己搜，自己读启动器状态", WORK / "c2.mp4")
    cut_qq(27.60, 36.20, "写操作，先让你点确认", WORK / "c3.mp4")
    # 38s 还停在确认框；41s 才出现钠/光影勾选
    cut_qq(41.00, 46.40, "勾选钠和光影，下载已经开始", WORK / "c4.mp4")
    cut_qq(46.60, 52.00, "去下载任务看进度", WORK / "c5.mp4")
    title(WORK / "t1.mp4", 2.8, "你说话", "它替你点完那些菜单")

    clips = ["t0.mp4", "c1.mp4", "c2.mp4", "c3.mp4", "c4.mp4", "c5.mp4", "t1.mp4"]
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in clips), encoding="utf-8")
    body = WORK / "body.mp4"
    ff(
        "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c", "copy",
        str(body),
    )

    starts = []
    acc = 0.0
    for name in clips:
        starts.append(acc)
        acc += dur(WORK / name)
    body_d = dur(body)
    print("starts", [round(x, 2) for x in starts], "body", round(body_d, 2), flush=True)

    # VO 贴在对应镜头开头：c1,c2,c3,c4,c5,t1
    vo_at = [starts[1], starts[2], starts[3], starts[4], starts[5], starts[6]]
    vo_files = [WORK / f"vo{i}.mp3" for i in range(1, 7)]
    for i, p in enumerate(vo_files):
        print(f"vo{i+1}={dur(p):.2f}s @{vo_at[i]:.2f}s", flush=True)

    n = 1 + len(vo_files)
    inputs = ["-i", str(body)]
    for p in vo_files:
        inputs += ["-i", str(p)]

    fc = []
    mix_labels = []
    for i, delay in enumerate(vo_at):
        ms = int(round(delay * 1000))
        src = i + 1
        lab = f"v{i}"
        fc.append(f"[{src}:a]adelay={ms}|{ms},apad[a{i}]")
        mix_labels.append(f"[a{i}]")
    joined = "".join(mix_labels)
    fc.append(
        f"{joined}amix=inputs={len(vo_files)}:dropout_transition=0:normalize=0[vo]"
    )
    fc.append(
        "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        "volume=0.16[ui]"
    )
    fc.append(
        f"[ui][vo]amix=inputs=2:duration=first:dropout_transition=0,"
        f"loudnorm=I=-16:LRA=11:TP=-1.5,aresample=48000[a]"
    )

    ff(
        *inputs,
        "-filter_complex", ";".join(fc),
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{body_d:.3f}",
        str(OUT),
    )
    print("OUT", OUT, OUT.stat().st_size, "dur", dur(OUT), flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print("FAIL", e, file=sys.stderr)
        sys.exit(e.returncode)
