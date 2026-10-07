# -*- coding: utf-8 -*-
"""跨桥账号令牌兼容（审计 2026-09-28 P0-3）的判别测试。

缺陷背景：
  · Python 侧 `mclauncher/auth.py` 的 `seal_secret` 把 `access_token` /
    `refresh_token` 用 Windows DPAPI 密封成 `dpapi:<b64>` 落盘；
  · C 侧 `native/src/auth.c` / `launcher.c` 此前**直接取 `access_token` 当令牌用**，
    全目录 `rg -i "dpapi|CryptProtect"` 零命中；
  · 于是正版账号在两个桥之间**不可交替使用**：C 桥把密文当合法令牌塞进
    `--accessToken` 交给游戏，表现是「登录态无效 / 进不了正版服务器」，很难归因。

本用例编译真 C 代码（`auth.c` 链路）真跑，守四件事：
  1. Python `seal_secret` 写的 `dpapi:` 密文，C 侧 `accounts_load` +
     `account_launch_props` 必须解出**明文**（修复前会原样拿到密文）；
  2. C 侧 `accounts_save` 写下的令牌必须是 `dpapi:<b64>`，且 Python `open_secret`
     能解开（反向兼容）；
  3. 读改写回对 C 侧解不开的引用（`keyring:`）**无损**——不能被 C 写成空串或
     `unavailable:`，否则 Python 那边就再也取不回令牌了；
  4. 解不开的令牌绝不能被当成启动令牌传出去（`unavailable:` → `"0"`，不是原串）。
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
sys.path.insert(0, str(ROOT))

from mclauncher import auth  # noqa: E402

DPAPI_OK = hasattr(auth, "_dpapi_protect")


def _find_gcc() -> str | None:
    gcc = shutil.which("gcc")
    if gcc:
        return gcc
    for cand in (r"C:\msys64\mingw64\bin\gcc.exe", r"C:\msys64\ucrt64\bin\gcc.exe"):
        if Path(cand).is_file():
            return cand
    return None


# harness 直接走 C 桥启动链上那两个函数：accounts_load → account_launch_props
# （launcher.c:386-390 就是从这里取 token 拼 --accessToken / --uuid / --session）。
#
# 令牌从 UTF-8 文件读，不走 argv：MinGW 的 main(argc, argv) 按 ANSI 代码页解 argv，
# 非 ASCII 令牌（真实 MSA 令牌是 ASCII，但测试要覆盖 UTF-8 口径）会被进程边界弄坏。
# 真实桥收的是 JSON-RPC 的 UTF-8 body，读文件与它同一条编码路径。
HARNESS = r'''
#include "pymcl.h"
#include <stdio.h>

static cJSON *first_account(cJSON *root) {
    cJSON *arr = cJSON_GetObjectItemCaseSensitive(root, "accounts");
    return cJSON_IsArray(arr) && cJSON_GetArraySize(arr) > 0 ? cJSON_GetArrayItem(arr, 0) : NULL;
}

static void print_secret(const char *label, cJSON *acc, const char *key) {
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(acc, key));
    printf("%s=%s\n", label, v ? v : "<null>");
}

/* 逐行读 UTF-8 文本：第 1 行 access_token，第 2 行 refresh_token */
static void chomp(char *s) {
    size_t n = strlen(s);
    while (n > 0 && (s[n - 1] == '\r' || s[n - 1] == '\n')) s[--n] = 0;
}
static int read_pair(const char *path, char *a, size_t na, char *r, size_t nr) {
    char *buf = NULL;
    size_t len = 0;
    if (pymcl_read_file(path, &buf, &len) != 0 || !buf) return -1;
    buf[len] = 0;
    char *nl = strchr(buf, '\n');
    if (!nl) { free(buf); return -1; }
    *nl = 0;
    char *second = nl + 1;
    char *nl2 = strchr(second, '\n');
    if (nl2) *nl2 = 0;
    chomp(buf);
    chomp(second);
    snprintf(a, na, "%s", buf);
    snprintf(r, nr, "%s", second);
    free(buf);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: harness.exe <root> read|save|touch-active [args]\n"); return 2; }
    const char *mode = argv[2];
    pymcl_set_root(argv[1]);
    config_init();
    i18n_init(NULL);

    if (strcmp(mode, "read") == 0) {
        cJSON *root = accounts_load();
        cJSON *acc = first_account(root);
        if (!acc) { printf("ERROR=no-account\n"); cJSON_Delete(root); return 1; }
        print_secret("TOKEN", acc, "access_token");
        print_secret("REFRESH", acc, "refresh_token");
        cJSON *props = account_launch_props(acc);
        print_secret("PROPS_TOKEN", props, "token");
        cJSON_Delete(props);
        cJSON_Delete(root);
        return 0;
    }

    if (strcmp(mode, "save") == 0) {
        /* argv[3] = 放 <access>\n<refresh> 的 UTF-8 文件 */
        if (argc < 4) { fprintf(stderr, "save needs <pair-file>\n"); return 2; }
        char access[1024], refresh[1024];
        if (read_pair(argv[3], access, sizeof(access), refresh, sizeof(refresh)) != 0) {
            fprintf(stderr, "cannot read pair file\n");
            return 2;
        }
        cJSON *root = cJSON_CreateObject();
        cJSON *arr = cJSON_CreateArray();
        cJSON_AddItemToObject(root, "accounts", arr);
        cJSON *acc = cJSON_CreateObject();
        cJSON_AddStringToObject(acc, "type", "microsoft");
        cJSON_AddStringToObject(acc, "name", "MSA");
        cJSON_AddStringToObject(acc, "uuid", "069a79f4-44e9-4726-a5be-fca90e38aaf5");
        cJSON_AddStringToObject(acc, "access_token", access);
        cJSON_AddStringToObject(acc, "refresh_token", refresh);
        cJSON_AddNumberToObject(acc, "expires_at", 1.0);
        cJSON_AddItemToArray(arr, acc);
        cJSON_AddStringToObject(root, "active", "MSA");
        accounts_save(root);
        cJSON_Delete(root);
        printf("SAVED=1\n");
        return 0;
    }

    if (strcmp(mode, "touch-active") == 0) {
        /* 读 → 改一个无关的键 → 写回：这是 set_active_account 的形态 */
        cJSON *root = accounts_load();
        cJSON_ReplaceItemInObjectCaseSensitive(root, "active", cJSON_CreateString(argc > 3 ? argv[3] : "MSA"));
        accounts_save(root);
        cJSON_Delete(root);
        printf("TOUCHED=1\n");
        return 0;
    }

    fprintf(stderr, "unknown mode %s\n", mode);
    return 2;
}
'''


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


@unittest.skipUnless(_find_gcc(), "没有 gcc，跳过 C 侧编译真跑")
@unittest.skipUnless(DPAPI_OK, "非 Windows，跳过 DPAPI 跨桥测试")
class CrossBridgeAccountSecretTests(unittest.TestCase):
    """编译 auth.c 链路真跑：Python 密封 ↔ C 解封，两个方向都验。"""

    ACCESS = "MSA-ACCESS-TOKEN-1a2b3c4d5e6f-跨桥"   # 带非 ASCII，顺带验 UTF-8 口径
    REFRESH = "M.R3_BAY.refresh-9f8e7d6c"

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pymcl-xbridge-"))
        src = cls.tmp / "harness.c"
        src.write_text(HARNESS, encoding="utf-8")
        exe = cls.tmp / "harness.exe"
        cmd = [
            _find_gcc(), "-O0", "-std=c11", "-DWIN32_LEAN_AND_MEAN",
            "-I", str(NATIVE / "include"), "-I", str(NATIVE / "vendor"),
            "-o", str(exe), str(src),
            str(NATIVE / "src" / "auth.c"), str(NATIVE / "src" / "util.c"),
            str(NATIVE / "src" / "config.c"), str(NATIVE / "src" / "http.c"),
            str(NATIVE / "src" / "i18n.c"), str(NATIVE / "vendor" / "cJSON.c"),
            "-lz", "-lbcrypt", "-lcrypt32", "-lws2_32", "-lwinhttp",
            "-lpthread", "-lole32", "-lshell32",
        ]
        build = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=300)
        if build.returncode != 0:
            raise AssertionError(f"harness 编译失败：\n{build.stderr[-2000:]}")
        cls.exe = exe

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---------------- 工具 ----------------
    def _root(self, name: str) -> Path:
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _run(self, root: Path, *args: str) -> dict[str, str]:
        proc = subprocess.run([str(self.exe), str(root), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"harness 失败 rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
        return _parse_kv(proc.stdout)

    def _save(self, root: Path, access: str, refresh: str) -> dict[str, str]:
        """让 C 侧 accounts_save 落一份账号（令牌经 UTF-8 文件进 C，同真实 JSON 路径）。"""
        pair = root / "_pair.txt"
        pair.write_text(access + "\n" + refresh + "\n", encoding="utf-8")
        return self._run(root, "save", str(pair))

    def _write_python_accounts(self, root: Path, access: str, refresh: str) -> None:
        """用 Python 侧**公开** seal_secret 落盘，模拟 Python 桥登录后的磁盘状态。"""
        (root / "accounts.json").write_text(json.dumps({
            "active": "MSA",
            "accounts": [{
                "type": "microsoft", "name": "MSA",
                "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
                "access_token": auth.seal_secret(access),
                "refresh_token": auth.seal_secret(refresh),
                "expires_at": 1.0,
            }],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _raw_accounts(self, root: Path) -> dict:
        return json.loads((root / "accounts.json").read_text(encoding="utf-8"))

    # ---------------- 1. Python 写 → C 读 ----------------
    def test_c_bridge_reads_python_sealed_token(self):
        """P0-3 主断言：Python 密封的令牌，C 桥必须解出明文（修复前拿到的是密文）。"""
        root = self._root("py_to_c")
        self._write_python_accounts(root, self.ACCESS, self.REFRESH)

        # 前提：盘上确实是 dpapi: 形态（否则这条测试没在测该测的东西）
        stored = self._raw_accounts(root)["accounts"][0]["access_token"]
        self.assertTrue(stored.startswith("dpapi:"), f"落盘形态不是 dpapi: —— {stored[:32]!r}")

        got = self._run(root, "read")
        self.assertEqual(got.get("TOKEN"), self.ACCESS,
                         "C 桥没解开 Python 密封的 access_token（P0-3：会把密文当令牌用）")
        self.assertEqual(got.get("REFRESH"), self.REFRESH,
                         "C 桥没解开 Python 密封的 refresh_token")
        self.assertEqual(got.get("PROPS_TOKEN"), self.ACCESS,
                         "account_launch_props 给的 token 不是明文 —— 游戏会拿到密文")

    def test_c_launch_props_never_emits_ciphertext(self):
        """启动参数里的令牌不能是 dpapi:/unavailable: 这种引用串。"""
        root = self._root("cipher")
        (root / "accounts.json").write_text(json.dumps({
            "active": "MSA",
            "accounts": [{
                "type": "microsoft", "name": "MSA",
                "access_token": "unavailable:",          # DPAPI 失败时的哨兵
                "refresh_token": "keyring:token-deadbeef",  # C 侧读不到系统凭据库
                "expires_at": 1.0,
            }],
        }), encoding="utf-8")
        got = self._run(root, "read")
        self.assertEqual(got.get("PROPS_TOKEN"), "0",
                         "解不开的令牌被当成启动令牌传出去了（Python 侧应回落到 \"0\"）")
        self.assertNotIn("unavailable:", got.get("PROPS_TOKEN", ""))
        self.assertNotIn("keyring:", got.get("PROPS_TOKEN", ""))

    # ---------------- 2. C 写 → Python 读 ----------------
    def test_python_reads_c_sealed_token(self):
        """反向兼容：C 桥写下的令牌必须是 dpapi: 形态，且 Python 能解开。"""
        root = self._root("c_to_py")
        got = self._save(root, self.ACCESS, self.REFRESH)
        self.assertEqual(got.get("SAVED"), "1")

        stored = self._raw_accounts(root)["accounts"][0]
        self.assertTrue(stored["access_token"].startswith("dpapi:"),
                        f"C 桥没把令牌密封落盘：{stored['access_token'][:32]!r}")
        self.assertTrue(stored["refresh_token"].startswith("dpapi:"),
                        f"C 桥没把刷新令牌密封落盘：{stored['refresh_token'][:32]!r}")

        # Python 侧按自己的口径解封，必须拿到原文
        self.assertEqual(auth.open_secret(stored["access_token"]), self.ACCESS,
                         "Python 解不开 C 桥密封的 access_token —— 两桥不能交替读写")
        self.assertEqual(auth.open_secret(stored["refresh_token"]), self.REFRESH,
                         "Python 解不开 C 桥密封的 refresh_token")

        # 再走一遍 Python 的 AccountManager.load()，这是前端真正读账号的路径
        from mclauncher.auth import AccountManager
        mgr = AccountManager.__new__(AccountManager)   # 不碰真实 accounts.json
        mgr.accounts = [auth.open_account(a) for a in self._raw_accounts(root)["accounts"]]
        self.assertEqual(mgr.accounts[0]["access_token"], self.ACCESS)

    def test_c_sealed_blob_is_plain_dpapi_blob(self):
        """C 写的是「DPAPI 密文的标准 base64」，不是自造格式：Python 自己解一遍。"""
        root = self._root("blob_shape")
        self._save(root, self.ACCESS, self.REFRESH)
        b64 = self._raw_accounts(root)["accounts"][0]["access_token"][len("dpapi:"):]
        raw = base64.b64decode(b64)                      # 标准字母表，validate 通过
        self.assertEqual(auth._dpapi_unprotect(raw).decode("utf-8"), self.ACCESS)

    # ---------------- 3. 读改写回无损 ----------------
    def test_read_modify_write_preserves_keyring_reference(self):
        """C 侧解不开的 keyring: 引用，读改写回时必须原样留着（不能抹成空串）。"""
        root = self._root("keyring")
        (root / "accounts.json").write_text(json.dumps({
            "active": "MSA",
            "accounts": [{
                "type": "microsoft", "name": "MSA",
                "access_token": auth.seal_secret(self.ACCESS),
                "refresh_token": "keyring:token-abc123",
                "expires_at": 1.0,
            }],
        }), encoding="utf-8")
        self._run(root, "touch-active", "MSA")           # 读 → 改 active → 写回
        after = self._raw_accounts(root)["accounts"][0]
        self.assertEqual(after["refresh_token"], "keyring:token-abc123",
                         "C 的读改写回把 Python 的 keyring 引用弄丢了（令牌不可恢复）")
        self.assertEqual(auth.open_secret(after["access_token"]), self.ACCESS,
                         "读改写回之后 Python 解不开 access_token 了")

    def test_read_modify_write_is_idempotent_for_sealed_values(self):
        """反复读改写回：dpapi: 不能被二次密封成 Python 解不开的垃圾。"""
        root = self._root("idempotent")
        self._write_python_accounts(root, self.ACCESS, self.REFRESH)
        for i in range(3):
            self._run(root, "touch-active", f"MSA{i}")
            after = self._raw_accounts(root)["accounts"][0]
            self.assertEqual(auth.open_secret(after["access_token"]), self.ACCESS,
                             f"第 {i + 1} 轮读改写回后令牌解不开了")
            self.assertEqual(after["access_token"].count("dpapi:"), 1,
                             "出现了 dpapi:dpapi:… 二次密封")

    # ---------------- 4. 明文历史记录 ----------------
    def test_legacy_plaintext_record_is_read_and_migrated(self):
        """旧版明文记录：C 侧照用（向后兼容），落盘时顺手迁到 dpapi:。"""
        root = self._root("legacy")
        (root / "accounts.json").write_text(json.dumps({
            "active": "MSA",
            "accounts": [{
                "type": "microsoft", "name": "MSA",
                "access_token": "legacy-plaintext-token",
                "refresh_token": "legacy-plaintext-refresh",
                "expires_at": 1.0,
            }],
        }), encoding="utf-8")
        got = self._run(root, "read")
        self.assertEqual(got.get("TOKEN"), "legacy-plaintext-token",
                         "C 桥把历史明文记录也读错了")

        self._run(root, "touch-active", "MSA")
        after = self._raw_accounts(root)["accounts"][0]
        self.assertTrue(after["access_token"].startswith("dpapi:"),
                        "明文记录没被迁移到 dpapi:（下次 Python 读取仍能看到明文）")
        self.assertEqual(auth.open_secret(after["access_token"]), "legacy-plaintext-token")


if __name__ == "__main__":
    unittest.main()
