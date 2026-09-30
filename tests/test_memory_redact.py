# -*- coding: utf-8 -*-
"""P1-6 对话记忆持久化 + P2-1 日志脱敏的纯函数回归。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import 桌宠 as main  # noqa: E402


# ---------------- P2-1：_redact 脱敏 ----------------
SECRET = "abcdef1234567890"


def _masked(out):
    """脱敏语义断言：秘密值不再出现，且被打码符替代。"""
    assert SECRET not in out
    assert "***" in out


def test_redact_api_key_field_forms():
    _masked(main._redact("api_key=sk-" + SECRET))
    _masked(main._redact("apiKey: sk-" + SECRET))
    _masked(main._redact("apikey=sk-" + SECRET))
    _masked(main._redact("?api_key=sk-" + SECRET + "&x=1"))
    assert "&x=1" in main._redact("?api_key=sk-" + SECRET + "&x=1")


def test_redact_non_sk_api_key_form():
    # 无 sk- 前缀的 api_key 值形态：字段正则直接命中
    assert main._redact("API_KEY = " + SECRET) == "API_KEY = ***"


def test_redact_bare_query_key_form():
    # P2-1：裸 ?key= / &key= 查询参数形态也脱敏
    _masked(main._redact("?key=" + SECRET + "&next=1"))
    _masked(main._redact("https://x.test/api?a=1&key=" + SECRET))


def test_redact_url_encoded_value():
    _masked(main._redact("api_key=abc%2F" + SECRET[:8] + "xyz"))


def test_redact_short_values():
    # 阈值降为 6 位：6 位 api_key 值也脱敏
    assert main._redact("api_key=abcdef") == "api_key=***"


def test_redact_no_false_positive():
    assert main._redact("monkey=banana") == "monkey=banana"  # 无 api 前缀 / 非查询参数
    assert main._redact("key=abc123") == "key=abc123"  # 无查询标记
    assert main._redact("普通聊天没有敏感信息") == "普通聊天没有敏感信息"


def test_redact_sk_and_bearer_still_work():
    _masked(main._redact("我的 key 是 sk-" + SECRET + "xyz"))
    _masked(main._redact("Authorization: Bearer sk-" + SECRET))


# ---------------- P1-6：记忆读写 ----------------

@pytest.fixture
def mem_path(tmp_path):
    p = str(tmp_path / "memory.json")
    main.MEMORY_PATH = p
    yield p
    main.MEMORY_PATH = os.path.join(main.DATA_DIR, "memory.json")


def test_memory_roundtrip(mem_path):
    hist = [("user", "你好"), ("assistant", "嘶~ 你好呀绳匠")]
    main.save_chat_memory(hist)
    assert main.load_chat_memory() == hist


def test_memory_corrupt_returns_empty(mem_path):
    with open(mem_path, "w", encoding="utf-8") as f:
        f.write("{broken json")
    assert main.load_chat_memory() == []


def test_memory_missing_returns_empty(mem_path):
    assert main.load_chat_memory() == []


def test_memory_skips_malformed_entries(mem_path):
    with open(mem_path, "w", encoding="utf-8") as f:
        f.write('{"history": [["user", "hi"], ["assistant", "yo"], 42, ["user"]]}')
    assert main.load_chat_memory() == [("user", "hi"), ("assistant", "yo")]


def test_memory_truncated_to_max(mem_path):
    hist = [(str(i % 2), "msg%d" % i) for i in range(main._MEMORY_MAX + 50)]
    main.save_chat_memory(hist)
    out = main.load_chat_memory()
    assert len(out) == main._MEMORY_MAX
    # 截断保留末尾 main._MEMORY_MAX 条：第 50 条起（0..49 共 50 条被截掉）
    assert out[0] == ("0", "msg50")

