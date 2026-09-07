#!/usr/bin/env bash
# ============================================================
#  PyMCL 打包脚本（Linux / macOS）
#  用法: bash build_exe.sh
#  输出: dist/PyMCL (GUI) 与 dist/PyMCL-CLI (命令行)
#  说明: 若想自定义图标，Linux 用 .png（PyInstaller 会自动转换），
#        macOS 需要 icon.icns；把文件放到本目录并命名为 icon.png/icon.icns
# ============================================================
set -e
cd "$(dirname "$0")"

echo "[1/4] 安装/更新 PyInstaller..."
python3 -m pip install --upgrade pyinstaller

ICON=()
if [ -f icon.icns ]; then
    ICON=(--icon icon.icns)
elif [ -f icon.png ]; then
    ICON=(--icon icon.png)
fi

echo "[2/4] 打包图形界面版..."
python3 -m PyInstaller --noconfirm --clean --onefile --windowed --name PyMCL "${ICON[@]}" main.py

echo "[3/4] 打包命令行版..."
python3 -m PyInstaller --noconfirm --clean --onefile --console --name PyMCL-CLI "${ICON[@]}" main.py

echo "[4/4] 完成！输出在 dist/ 目录："
ls -lh dist/
echo "把可执行文件放到任意可写目录即可使用（数据保存在可执行文件旁边，便携）。"
