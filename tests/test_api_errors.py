# -*- coding: utf-8 -*-
"""v2.0.4 其他模型 API 回归：错误归类（密钥/额度/地区/不可用/限流）/
服务商预设 / 连通性测试（含本地 HTTP 服务端真实 401 响应）。

纯逻辑 + 本地回环 HTTP，无外网依赖。
"""
import http.server
import json
import threading

import pet_chat


def test_explain_api_error_basic():
    assert "密钥" in pet_chat.explain_api_error(401)
    assert "额度" in pet_chat.explain_api_error(402)
    assert "地区" in pet_chat.explain_api_error(403, "country is not supported")
    assert "额度" in pet_chat.explain_api_error(403, "your quota is exceeded")
    assert "权限" in pet_chat.explain_api_error(403, "forbidden")
    assert "模型名" in pet_chat.explain_api_error(404)
    assert "400" in pet_chat.explain_api_error(400) and "422" in pet_chat.explain_api_error(422)
    assert "限流" in pet_chat.explain_api_error(429)
    assert "开小差" in pet_chat.explain_api_error(500)
    assert "503" in pet_chat.explain_api_error(503)
    assert "418" in pet_chat.explain_api_error(418)  # 未知状态给通用原因


def test_explain_api_error_body_sniffing():
    """服务商文案各异：响应体关键词嗅探兜底（状态码可能非标准）。"""
    assert "密钥" in pet_chat.explain_api_error(200, "invalid_api_key")
    assert "额度" in pet_chat.explain_api_error(200, '{"error":"insufficient_quota"}')
    assert "限流" in pet_chat.explain_api_error(200, "rate limit exceeded")
    assert "模型名" in pet_chat.explain_api_error(200, "model not found")
    assert "地区" in pet_chat.explain_api_error(403, "banned in your region")


def test_ai_providers_sane():
    for pid in ("deepseek", "kimi", "doubao", "qwen", "zhipu", "hunyuan",
                "spark", "qianfan", "openai", "groq", "openrouter",
                "minimax", "siliconflow", "ollama", "custom"):
        p = pet_chat.AI_PROVIDERS.get(pid)
        assert p is not None and p.get("name"), pid
    # 除 custom 外都要有可用 base_url 与模型名（预设必须一键可用）
    assert len([p for p in pet_chat.AI_PROVIDERS if p != "custom"]) >= 14
    for pid, p in pet_chat.AI_PROVIDERS.items():
        if pid != "custom":
            assert p.get("base_url") and p.get("model"), pid
            assert p["base_url"].startswith("http"), pid


def test_api_connection_unreachable():
    """连不上的地址 → 归类为「连不上接口地址」，快速失败不抛异常。"""
    ok, msg = pet_chat.test_api_connection("http://127.0.0.1:1", "m", "k", timeout=2)
    # 端口 1 在部分网络环境被防火墙 DROP（表现为超时）而非 REFUSED：两种都属正确归类
    assert not ok and ("连不上" in msg or "超时" in msg), msg


def test_api_connection_401_from_server():
    """本地 HTTP 服务端返回 401 → 归类为密钥无效（真实响应链路）。"""
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802（http.server 命名约定）
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "bad key"}}).encode("utf-8"))

        def log_message(self, *a):
            pass  # 有意忽略：压掉测试服务器的请求日志

    _srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    _port = _srv.server_address[1]
    _t = threading.Thread(target=_srv.serve_forever, daemon=True)
    _t.start()
    try:
        ok, msg = pet_chat.test_api_connection(
            "http://127.0.0.1:%d" % _port, "m", "k", timeout=5)
        assert not ok and "密钥" in msg, msg
    finally:
        _srv.shutdown()
        _srv.server_close()


def test_is_local_base():
    assert pet_chat.is_local_base("http://localhost:11434/v1") is True
    assert pet_chat.is_local_base("http://127.0.0.1:8080") is True
    assert pet_chat.is_local_base("https://api.deepseek.com") is False
    assert pet_chat.is_local_base("") is False


def test_api_connection_403_region_from_server():
    """本地 HTTP 服务端返回 403 + region 文案 → 归类为地区限制（真实响应链路）。"""
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802（http.server 命名约定）
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(
                {"error": {"message": "not supported in your region"}}).encode("utf-8"))

        def log_message(self, *a):
            pass  # 有意忽略：压掉测试服务器的请求日志

    _srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    _port = _srv.server_address[1]
    _t = threading.Thread(target=_srv.serve_forever, daemon=True)
    _t.start()
    try:
        ok, msg = pet_chat.test_api_connection(
            "http://127.0.0.1:%d" % _port, "m", "k", timeout=5)
        assert not ok and "地区" in msg, msg
    finally:
        _srv.shutdown()
        _srv.server_close()


def test_api_connection_ok_from_server():
    """本地 HTTP 服务端返回 200 → 连接成功。"""
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802（http.server 命名约定）
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(
                {"choices": [{"message": {"content": "pong"}}]}).encode("utf-8"))

        def log_message(self, *a):
            pass  # 有意忽略：压掉测试服务器的请求日志

    _srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    _port = _srv.server_address[1]
    _t = threading.Thread(target=_srv.serve_forever, daemon=True)
    _t.start()
    try:
        ok, msg = pet_chat.test_api_connection(
            "http://127.0.0.1:%d" % _port, "m", "k", timeout=5)
        assert ok and "连接成功" in msg, msg
    finally:
        _srv.shutdown()
        _srv.server_close()
