# -*- coding: utf-8 -*-
"""v2.0 语音系统：事件音频片段 + AI 声音合成（API / 本地 SAPI），默认关闭。

- 事件片段：用户自行导入 wav/mp3，按事件（reply/feed/poke/sleep/wake）播放。
- AI 合成：两种后端——
  * sapi：Windows 内置语音（System.Speech，无需网络/Key），失败给出明确原因；
  * api：OpenAI 兼容 /audio/speech（地址/模型/声音名可配），受限时明确提示（密钥无效/
    额度不足/地区限制/服务不可用/接口不存在），绝不静默失败。
- 默认关闭：cfg["voice"]["enabled"]=False，行为与旧版一致。
不 import 桌宠（避免循环）；回调注入。
"""
import hashlib
import json
import os
import subprocess
import sys
import threading

import pet_log
import requests

# 事件名（片段注册表 voice.json 的键）
VOICE_EVENTS = ("reply", "feed", "poke", "sleep", "wake")

# API 错误 → 中文原因（界面直接提示，不隐藏问题）
TTS_API_ERRORS = {
    401: "密钥无效",
    402: "额度不足",
    403: "地区限制或服务不可用",
    404: "当前接口不支持语音合成（服务商无 /audio/speech）",
    429: "请求太频繁，稍后再试",
}


def explain_tts_error(status_code):
    """API 状态码 → 中文原因（纯函数，可测）。未知码返回通用原因。"""
    return TTS_API_ERRORS.get(status_code, "服务不可用（HTTP %d）" % status_code)


class VoiceService:
    """语音服务：片段注册 + TTS（API/SAPI） + 缓存。主线程调用（内部线程化网络/合成）。"""

    def __init__(self, data_dir, cfg_getter, play_clip, log=None):
        self._dir = os.path.join(data_dir, "voice")
        self._index = os.path.join(data_dir, "voice.json")
        self._cfg = cfg_getter
        self._play_clip = play_clip  # 播放 wav/mp3 的回调（由桌宠注入 pet_audio.preview_file 类）
        self._log = log or pet_log.log_error
        self._clips = {}  # {event: 文件名}
        self._cache_dir = os.path.join(self._dir, "tts_cache")
        self._busy = False
        self._load()

    # ---------- 片段注册表 ----------
    def _load(self):
        try:
            with open(self._index, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._clips = {k: str(v) for k, v in data.items()
                               if k in VOICE_EVENTS and str(v).lower().endswith((".wav", ".mp3"))}
        except Exception:
            self._clips = {}  # 首次使用/损坏：空表（有意静默，首次运行常态）

    def _save(self):
        try:
            os.makedirs(self._dir, exist_ok=True)
            tmp = self._index + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._clips, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._index)
        except Exception as e:
            self._log("voice index save failed: %r" % (e,))

    def clip(self, event):
        """事件片段的绝对路径；未配置返回 None。"""
        fname = self._clips.get(event)
        if not fname:
            return None
        p = os.path.join(self._dir, fname)
        return p if os.path.isfile(p) else None

    def set_clip(self, event, src_path=None):
        """导入/清除事件片段。src_path 为音频文件路径（复制进 voice/ 目录）；None=清除。
        返回 (ok, err)。"""
        if event not in VOICE_EVENTS:
            return False, "未知事件"
        try:
            os.makedirs(self._dir, exist_ok=True)
        except Exception as e:
            return False, "语音目录创建失败：%s" % e
        if src_path is None:
            old = self._clips.pop(event, None)
            self._save()
            if old:
                try:
                    p = os.path.join(self._dir, old)
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：旧片段清理尽力而为
            return True, ""
        try:
            if not os.path.isfile(src_path):
                return False, "音频文件不存在"
            ext = os.path.splitext(src_path)[1].lower()
            if ext not in (".wav", ".mp3"):
                return False, "仅支持 wav/mp3"
            fname = "%s_%s%s" % (event, hashlib.md5(src_path.encode("utf-8")).hexdigest()[:8], ext)
            dest = os.path.join(self._dir, fname)
            with open(src_path, "rb") as fin, open(dest, "wb") as fout:
                fout.write(fin.read())
            old = self._clips.get(event)
            self._clips[event] = fname
            self._save()
            if old and old != fname:  # 覆盖导入：清理被替换的旧片段（孤儿防累积）
                try:
                    p = os.path.join(self._dir, old)
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：旧片段清理尽力而为
            return True, ""
        except Exception as e:
            return False, "导入失败：%s" % e

    # ---------- 事件播放 ----------
    def play_event(self, event):
        """事件触发：仅播放事件片段（无片段/未配置则静默——事件不合成朗读，
        合成仅用于 AI 回复 speak()）；语音关闭则静默。"""
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        if not vcfg.get("enabled"):
            return
        p = self.clip(event)
        if p is not None:
            try:
                self._play_clip(p)
            except Exception as e:
                self._log("voice clip play failed: %r" % (e,))
            return

    def speak(self, text, on_error=None):
        """合成并播放一句话（AI 回复用）。语音关闭/空文本/正在合成直接返回（防叠音）。

        on_error(reason)：受限/失败时的明确提示回调（调用方传入线程安全投递，如
        signals.voice_error.emit——不直调 Qt 控件）。
        """
        if self._busy:
            return  # 并发互斥：上一句还在合成/播放，本次丢弃
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        if not vcfg.get("enabled"):
            return
        text = (text or "").strip()
        if not text:
            return
        mode = vcfg.get("tts_mode", "off")
        if mode == "off":
            return
        self._busy = True
        threading.Thread(target=self._speak_worker, args=(text, mode, vcfg, cfg, on_error),
                         daemon=True).start()

    def _speak_worker(self, text, mode, vcfg, cfg, on_error):
        try:
            wav = None
            if mode == "api":
                wav, err = self._tts_api(text, vcfg, cfg)
            elif mode == "sapi":
                wav, err = self._tts_sapi(text, vcfg)
            else:
                return
            if wav and os.path.isfile(wav):
                self._play_clip(wav)
            elif err and on_error:
                on_error(err)
        except Exception as e:
            self._log("voice speak failed: %r" % (e,))
            if on_error:
                on_error("语音合成失败：%s" % e)
        finally:
            self._busy = False

    # ---------- API 合成 ----------
    def _tts_api(self, text, vcfg, cfg):
        base = (cfg.get("ai_base_url") or "").strip().rstrip("/")
        if not base:
            return None, "未配置 AI 接口地址，无法语音合成（在 AI设置 填 OpenAI 兼容地址）"
        url = base + "/audio/speech"
        key = cfg.get("api_key", "")
        if not key:
            return None, "未配置 API Key，无法语音合成"
        out = self._cache_path(text, mode="api", vcfg=vcfg)
        if self._cache_ok(out):
            return out, None  # 命中缓存：同文本同声音/模型不重复请求
        try:
            resp = requests.post(
                url,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": vcfg.get("tts_model") or "tts-1",
                      "input": text,
                      "voice": vcfg.get("tts_voice") or "alloy"},
                timeout=30,
            )
        except requests.exceptions.Timeout:
            return None, "语音合成超时（网络或服务商响应慢）"
        except requests.exceptions.ConnectionError:
            return None, "无法连接语音接口（网络或地址不对）"
        except Exception as e:
            return None, "语音合成失败：%s" % e
        if resp.status_code != 200:
            return None, "语音合成受限：%s" % explain_tts_error(resp.status_code)
        if not resp.content:
            return None, "语音合成返回空内容（服务商异常）"
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            tmp = out + ".tmp"
            with open(tmp, "wb") as f:
                f.write(resp.content)
            os.replace(tmp, out)  # 原子写：半截文件不会被当作缓存命中
            return out, None
        except Exception as e:
            return None, "语音文件保存失败：%s" % e

    # ---------- 本地 SAPI 合成 ----------
    def _tts_sapi(self, text, vcfg):
        """Windows 内置语音（System.Speech）：离线合成，失败给出明确原因。"""
        out = self._cache_path(text, mode="sapi", vcfg=vcfg)
        if self._cache_ok(out):
            return out, None  # 命中缓存（校验大小，防半截残留被误用）
        voice = vcfg.get("tts_voice") or ""
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
        except Exception as e:
            return None, "缓存目录创建失败：%s" % e
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        )
        if voice:
            ps += "try { $s.SelectVoice('%s') } catch {}; " % voice.replace("'", "''")
        ps += "$s.SetOutputToWaveFile('%s'); $s.Speak('%s'); $s.Dispose();" % (
            out.replace("'", "''"), text.replace("'", "''"))
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, timeout=60,
            )
        except FileNotFoundError:
            return None, "系统没有 PowerShell，本地语音不可用"
        except subprocess.TimeoutExpired:
            try:
                if os.path.isfile(out):
                    os.remove(out)  # 超时残留半截 wav：清掉防下次误当缓存
            except Exception:
                pass  # 有意忽略：清理尽力而为
            return None, "本地语音合成超时"
        if proc.returncode != 0 or not self._cache_ok(out):
            try:
                if os.path.isfile(out):
                    os.remove(out)
            except Exception:
                pass  # 有意忽略：失败产物清理尽力而为
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            return None, "本地语音不可用（%s）——可在语音设置改用 API 合成" % (
                err[:80] or "系统没有可用语音包")
        return out, None

    def _cache_ok(self, path):
        """缓存命中校验：存在且大小足够（>44B WAV 头），防半截/空文件。"""
        try:
            return os.path.isfile(path) and os.path.getsize(path) > 44
        except Exception:
            return False

    def _cache_path(self, text, mode="sapi", vcfg=None):
        # 缓存键含声音/模型：换配置不命中旧缓存；api 合成内容多为 mp3，扩展名按模式
        vcfg = vcfg or {}
        extra = "%s|%s" % (vcfg.get("tts_voice") or "", vcfg.get("tts_model") or "")
        h = hashlib.md5(("%s|%s|%s" % (mode, text, extra)).encode("utf-8")).hexdigest()[:16]
        ext = "mp3" if mode == "api" else "wav"
        return os.path.join(self._cache_dir, "%s.%s" % (h, ext))


def _to_bool(v):
    """与 pet_config._to_bool 同口径：字符串 "false"/"0" 判 False（手改配置不误开）。"""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def normalize_voice(v):
    """voice 配置归一化（纯函数）：enabled/tts_mode 白名单，字符串字段 trim。

    始终返回新 dict（默认值单一来源 DEFAULT_VOICE）。"""
    if not isinstance(v, dict):
        v = {}
    return {
        "enabled": _to_bool(v.get("enabled")),
        "tts_mode": v.get("tts_mode") if v.get("tts_mode") in ("off", "sapi", "api") else "off",
        "tts_model": str(v.get("tts_model") or "").strip(),
        "tts_voice": str(v.get("tts_voice") or "").strip(),
    }


DEFAULT_VOICE = normalize_voice(None)
