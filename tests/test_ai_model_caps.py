# -*- coding: utf-8 -*-
"""模型能力表（多模态自动适配）测试。

覆盖 ZCode 规则语义的三条关键性质：
1. modelMatch 是全匹配 + 大小写不敏感；
2. 规则按序 overlay，后者覆盖前者，且嵌套字段逐字段合并（不整体替换）；
3. 兜底规则生效（没命中任何规则时 200k / 不支持图片）。
另外覆盖：用户覆盖表、client 层门控、图片编码、消息体构造与剥离。
"""

import io
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mclauncher.ai import modelcaps as mc


@pytest.fixture(autouse=True)
def _fresh_cache():
    mc.reset_cache()
    yield
    mc.reset_cache()


# ---------------------------------------------------------------- 能力判定

class TestResolve:
    def test_vision_models_detected(self):
        """内置表里标了 supportsImage 的模型必须判成支持图片。"""
        for model in ("glm-4.6v", "glm-4.6v-flash", "glm-5v-turbo",
                      "glm-4v-flash", "gpt-5.4", "claude-sonnet-5",
                      "kimi-k3", "qwen3-vl-plus", "mimo-v2-omni"):
            assert mc.supports_image(model), f"{model} 应该支持图片"

    def test_text_only_models_detected(self):
        for model in ("deepseek-v4-flash", "deepseek-v4-pro", "glm-4.6",
                      "glm-5.3", "qwen3-max", "MiniMax-M2"):
            assert not mc.supports_image(model), f"{model} 不该支持图片"

    def test_unknown_model_falls_back_to_no_image(self):
        """兜底规则：没命中任何规则 → 不支持图片（安全侧）。"""
        assert not mc.supports_image("totally-unknown-model-xyz")

    def test_fallback_context_window(self):
        assert mc.resolve("totally-unknown-model-xyz")["contextWindow"] == 200000

    def test_match_is_case_insensitive(self):
        """ZCode 的 vWt(...,true) 带 "i" flag。"""
        assert mc.supports_image("GLM-4.6V")
        assert mc.supports_image("Glm-4.6v-Flash")

    def test_match_is_fullmatch_not_search(self):
        """ZCode 把 modelMatch 包成 ^(?:...)$，子串不该命中。"""
        # 模型名里包含 "glm-4.6v" 但整体不是它 → 不该命中该条，落到兜底（不支持图片）
        assert mc.resolve("xxglm-4.6vxx")["inputFormat"]["supportsImage"] is False

    def test_version_suffix_still_matches(self):
        """规则尾部 (?:[.\\-:/\\[].*)? 允许版本后缀。"""
        assert mc.supports_image("glm-4.6v-20250101")
        assert mc.supports_image("glm-4.6v:latest")

    def test_overlay_does_not_wipe_siblings(self):
        """只声明 supportsImage 的规则不能把 supportsText 抹掉（overlayConfig 语义）。"""
        fmt = mc.resolve("glm-4.6v")["inputFormat"]
        assert fmt["supportsText"] is True
        assert fmt["supportsImage"] is True
        # 其余布尔项也应存在（来自兜底规则），而不是缺失
        for key in ("supportsVideo", "supportsAudio", "supportsPdf"):
            assert key in fmt

    def test_context_window_from_rules(self):
        assert mc.context_window("glm-4.6v") == 131072
        assert mc.context_window("deepseek-v4-flash") == 1000000

    def test_context_window_fallback_arg(self):
        # 表里不认识的模型：用户配置值说了算
        assert mc.context_window("nope", fallback=65536) == 65536
        # 非法 fallback 回落到表内兜底
        assert mc.context_window("nope", fallback="bad") == 200000
        # 表里认识的模型：精确值优先于用户通用配置
        assert mc.context_window("glm-4.6v", fallback=65536) == 131072
        assert mc.context_window("deepseek-v4-flash", fallback=8192) == 1000000

    def test_later_rule_overrides_earlier(self):
        """glm-5.3 先被 .*glm-5 命中(200k)，再被更具体的 glm-5.3 覆盖成 1M。"""
        assert mc.resolve("glm-5.3")["contextWindow"] == 1000000
        assert mc.resolve("glm-5.3-flash")["contextWindow"] == 1000000
        assert mc.resolve("glm-5")["contextWindow"] == 200000


# ---------------------------------------------------------------- 用户覆盖

class TestOverrides:
    def test_user_can_enable_image(self):
        s = {"ai_model_caps_overrides": {
            "my-private-vlm": {"inputFormat": {"supportsImage": True}}}}
        assert mc.supports_image("my-private-vlm", settings=s)
        assert not mc.supports_image("my-private-vlm")

    def test_user_can_disable_image(self):
        s = {"ai_model_caps_overrides": {
            "glm-4.6v": {"inputFormat": {"supportsImage": False}}}}
        assert not mc.supports_image("glm-4.6v", settings=s)
        assert mc.supports_image("glm-4.6v")

    def test_override_keeps_siblings(self):
        s = {"ai_model_caps_overrides": {
            "glm-4.6v": {"contextWindow": 32000}}}
        cfg = mc.resolve("glm-4.6v", settings=s)
        assert cfg["contextWindow"] == 32000
        assert cfg["inputFormat"]["supportsImage"] is True, "覆盖窗口不该动图片能力"

    def test_override_regex_key(self):
        s = {"ai_model_caps_overrides": {
            r"my-vlm-.*": {"inputFormat": {"supportsImage": True}}}}
        assert mc.supports_image("my-vlm-7b", settings=s)
        assert not mc.supports_image("other-7b", settings=s)

    def test_bad_override_ignored(self):
        s = {"ai_model_caps_overrides": {"[": {"inputFormat": {"supportsImage": True}}}}
        assert not mc.supports_image("[")  # 非法正则不炸，按未覆盖处理


# ---------------------------------------------------------------- api_type

class TestApiType:
    def test_pymcl_api_type_is_chat_completions(self):
        assert mc.api_type_for_mode("custom") == "openai-chat-completions"
        assert mc.api_type_for_mode("public") == "openai-chat-completions"

    def test_api_scoped_rule_only_applies_with_matching_api(self):
        """modelApiRules 里那条 supportsMidConversationSystem 只在 anthropic 下生效，
        不该污染 openai 通道的判定；而 modelRules 的图片能力与 api 无关。"""
        cfg = mc.resolve("claude-opus-5", api_type="openai-chat-completions")
        assert cfg["inputFormat"]["supportsImage"] is True
        # claude-opus-4.8 不在表里（表里只有 opus-5），按兜底处理
        assert mc.supports_image("claude-opus-4.8") is False


# ---------------------------------------------------------------- describe

class TestDescribe:
    def test_describe_mentions_image(self):
        assert "图片 ✓" in mc.describe("glm-4.6v")
        assert "图片 ✗" in mc.describe("deepseek-v4-flash")

    def test_context_formatting(self):
        assert "1M" in mc.describe("deepseek-v4-flash")
        assert "131K" in mc.describe("glm-4.6v")
        # 1048576 不该显示成 1048K
        assert "1048K" not in mc.describe("kimi-k3")

    def test_image_models_nonempty(self):
        names = mc.image_models(5)
        assert names, "至少应该能列出几个支持图片的模型"
        assert all(isinstance(n, str) and n for n in names)
        assert not any("|" in n for n in names), "不该出现正则残片"


# ---------------------------------------------------------------- 图片编码

class TestImageEncoding:
    def _png(self, size=(64, 64), mode="RGB"):
        from PIL import Image
        buf = io.BytesIO()
        Image.new(mode, size, (10, 120, 200) if mode == "RGB" else (0, 0, 0, 0)).save(buf, "PNG")
        return buf.getvalue()

    def test_small_image_roundtrip(self):
        from mclauncher.ai import images
        url = images.encode_bytes(self._png())
        assert url.startswith("data:image/png;base64,")

    def test_large_image_shrunk(self):
        from PIL import Image
        from mclauncher.ai import images
        url = images.encode_bytes(self._png((4000, 3000)))
        import base64
        raw = base64.b64decode(url.split(",", 1)[1])
        assert max(Image.open(io.BytesIO(raw)).size) <= images.MAX_EDGE

    def test_transparent_stays_png(self):
        from mclauncher.ai import images
        url = images.encode_bytes(self._png((900, 900), mode="RGBA"))
        assert url.startswith("data:image/png;base64,")

    def test_reject_non_image(self):
        from mclauncher.ai import images
        with pytest.raises(images.ImageError):
            images.encode_bytes(b"definitely not an image")

    def test_build_user_content_passthrough(self):
        from mclauncher.ai import images
        assert images.build_user_content("hi", []) == "hi"
        assert images.build_user_content("hi", None) == "hi"

    def test_build_user_content_blocks(self):
        from mclauncher.ai import images
        blocks = images.build_user_content("hi", ["data:image/png;base64,AAA"])
        assert [b["type"] for b in blocks] == ["text", "image_url"]
        assert blocks[1]["image_url"]["url"].startswith("data:image/png")

    def test_strip_images(self):
        from mclauncher.ai import images
        blocks = images.build_user_content("hi", ["data:image/png;base64,AAA"])
        out = images.strip_images(blocks)
        assert "hi" in out
        assert "1 张图片" in out
        assert "base64" not in out

    def test_strip_message_drops_paths(self):
        from mclauncher.ai import images
        out = images.strip_message({"role": "user", "content": "hi",
                                    "images": ["/a.png", "/b.png"]})
        assert "images" not in out
        assert "2 张图片" in out["content"]


# ---------------------------------------------------------------- client 门控

class TestClientGating:
    def test_supports_image_reads_settings(self):
        from mclauncher.ai import client
        assert client.supports_image({"ai_mode": "custom", "ai_model": "glm-4.6v"})
        assert not client.supports_image({"ai_mode": "custom",
                                          "ai_model": "deepseek-v4-flash"})

    def test_current_model_public_uses_builtin(self):
        from mclauncher.ai import client
        assert client.current_model({"ai_mode": "public"})

    def test_prepare_messages_passthrough_without_images(self):
        from mclauncher.ai import client
        msgs = [{"role": "user", "content": "hi"}]
        assert client._prepare_messages({"ai_mode": "custom"}, msgs) is msgs

    def test_prepare_messages_encodes_for_vision_model(self):
        from mclauncher.ai import client
        from PIL import Image
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "a.png")
        Image.new("RGB", (40, 40), (1, 2, 3)).save(path, "PNG")
        msgs = [{"role": "user", "content": "看下", "images": [path]}]
        out = client._prepare_messages(
            {"ai_mode": "custom", "ai_model": "glm-4.6v"}, msgs)
        blocks = out[0]["content"]
        assert [b["type"] for b in blocks] == ["text", "image_url"]
        assert "images" not in out[0]
        assert "images" in msgs[0], "不该就地改调用方的消息"

    def test_prepare_messages_strips_for_text_model(self):
        from mclauncher.ai import client
        from PIL import Image
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "a.png")
        Image.new("RGB", (40, 40), (1, 2, 3)).save(path, "PNG")
        msgs = [{"role": "user", "content": "看下", "images": [path]}]
        out = client._prepare_messages(
            {"ai_mode": "custom", "ai_model": "deepseek-v4-flash"}, msgs)
        assert isinstance(out[0]["content"], str)
        assert "不支持" in out[0]["content"]
        assert "base64" not in out[0]["content"]

    def test_prepare_messages_reports_missing_file(self):
        from mclauncher.ai import client
        msgs = [{"role": "user", "content": "看", "images": ["/no/such/file.png"]}]
        out = client._prepare_messages(
            {"ai_mode": "custom", "ai_model": "glm-4.6v"}, msgs)
        content = out[0]["content"]
        text = content if isinstance(content, str) else json.dumps(content)
        assert "没能附上" in text

    def test_image_cap_enforced(self):
        from mclauncher.ai import client, images
        from PIL import Image
        tmp = tempfile.mkdtemp()
        paths = []
        for i in range(images.MAX_PER_TURN + 3):
            p = os.path.join(tmp, f"{i}.png")
            Image.new("RGB", (20, 20), (i, i, i)).save(p, "PNG")
            paths.append(p)
        msgs = [{"role": "user", "content": "看图", "images": paths}]
        out = client._prepare_messages(
            {"ai_mode": "custom", "ai_model": "glm-4.6v"}, msgs)
        assert images.count_images(out[0]["content"]) == images.MAX_PER_TURN


# ---------------------------------------------------------------- agent / store

class TestAgentStore:
    def test_summary_input_strips_images(self):
        from mclauncher.ai import agent
        text = agent._summary_input([
            {"role": "user", "content": "hi", "images": ["/x.png", "/y.png"]}])
        assert "base64" not in text
        assert "2 张图片" in text

    def test_api_messages_keeps_images(self):
        from mclauncher.ai import store
        out = store.api_messages([
            {"role": "user", "content": "hi", "images": ["/x.png"]}])
        assert out[0]["images"] == ["/x.png"]

    def test_api_messages_without_images_has_no_key(self):
        from mclauncher.ai import store
        out = store.api_messages([{"role": "user", "content": "hi"}])
        assert "images" not in out[0]

    def test_store_keeps_images_field(self):
        from mclauncher.ai import store
        m = store._load_message({"role": "user", "content": "hi",
                                 "images": ["/x.png"]})
        assert m["images"] == ["/x.png"]

    def test_run_agent_accepts_images_param(self):
        import inspect

        from mclauncher.ai import agent
        params = inspect.signature(agent.run_agent).parameters
        assert "images_list" in params
        assert params["images_list"].default is None


# ---------------------------------------------------------------- 规则数据完整性

class TestRuleData:
    def test_rules_file_loads(self):
        rules = mc._load()
        assert len(rules) > 100, "规则表应该完整搬过来了"

    def test_all_patterns_compile(self):
        import re
        path = mc._rules_path()
        data = json.loads(path.read_text("utf-8"))
        count = 0
        for layer in ("modelRules", "modelApiRules", "providerSiteRules"):
            for rule in data.get(layer) or []:
                for key in ("modelMatch", "apiTypeMatch", "baseUrlMatch"):
                    pat = rule.get(key)
                    if pat is None:
                        continue
                    re.compile(pat)  # 抛错即失败
                    count += 1
        assert count > 200

    def test_rules_file_exists(self):
        assert mc._rules_path().is_file()

    def test_vision_rule_count_matches_source(self):
        """源表 revision 30 里有 45 条带 supportsImage=true 的 modelRules。"""
        rules = mc._load()
        vision = [r for r in rules
                  if r["layer"] == "modelRules"
                  and (r["props"].get("inputFormat") or {}).get("supportsImage")]
        assert len(vision) == 45
