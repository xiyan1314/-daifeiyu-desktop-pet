# -*- coding: utf-8 -*-
"""
AI 对话线程 + 对话记忆持久化（P1-6 / P1-10 / P3-3）。

独立模块：不 import 桌宠.py。signals / cfg / 人设构造 / 表情解析 / 记忆读写全部注入；
_py/_chat_history/_history_lock/_mem_epoch 等守卫状态仍归属 PetWindow（语义不变）。
"""
import json
import os
import threading

import requests


# ---------------- P1-6：对话记忆持久化（全量落盘，上下文只取最近 N 轮） ----------------
def read_memory(path, max_entries, log=None):
    """读取 memory.json 对话历史 [(role, content), ...]；缺失/损坏返回 []。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            out = []
            for item in data["history"]:
                # 跳过畸形条目（非二元组/非字符串），不让一条坏数据毁掉整段记忆
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    r, c = item
                    if isinstance(r, str) and isinstance(c, str):
                        out.append((r, c))
            return out[-max_entries:]
    except Exception as e:
        if log is not None:
            log("load_chat_memory 读取失败（从空记忆开始）: %r" % (e,))
    return []


def write_memory(path, hist, max_entries, log=None):
    """原子落盘对话记忆；失败进日志（不再静默）。"""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"history": list(hist)[-max_entries:]}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        if log is not None:
            log("save_chat_memory 写盘失败: %r" % (e,))


class ChatService:
    """AI 对话线程：请求 / 人设 / 记忆 / 表情标记解析（P3-3 先剥标记再截断）。

    pet 提供（守卫语义与旧版一致）：_ai_inflight、_chat_history、_history_lock、_mem_epoch。
    """

    def __init__(self, pet, signals, cfg_getter, prompt_builder, parse_emote,
                 memory_loader, memory_saver, play_sound, log, default_reply_len):
        self.pet = pet
        self.signals = signals
        self._cfg = cfg_getter
        self._prompt = prompt_builder
        self._parse_emote = parse_emote
        self._load_memory = memory_loader
        self._save_memory = memory_saver
        self._play = play_sound
        self._log = log
        self._default_reply_len = default_reply_len

    def inflight(self):
        return self.pet._ai_inflight

    def ask(self, msg):
        self.pet._ai_inflight = True
        threading.Thread(target=self._worker, args=(msg, self._cfg().get("api_key", "")), daemon=True).start()

    def on_reply_ok(self):
        """AI 回复成功（主线程）：播任务完成音（借参考插件概念）。"""
        if self._cfg().get("sound", True):
            self._play("reply")

    def on_ai_emote(self, mode, kind):
        """P3-3：AI 回复带出的表情（主线程播放，data 驱动）。busy/睡眠中跳过，避免打断动作。"""
        pet = self.pet
        if pet.busy or pet._sleeping or pet._petting:
            return
        if mode == "state":
            pet._show_state(kind, 2600)
        else:
            pet._show_emote(kind)

    def _worker(self, msg, key):
        # P1-10：接口/模型/人设/长度全部配置驱动（OpenAI 兼容，支持本地 Ollama）
        # 配置读取与转换全部在 try 内：任何异常都走统一的"网络不好"回复，绝不卡死 _ai_inflight
        pet = self.pet
        try:
            cfg = self._cfg()
            base_url = (cfg.get("ai_base_url") or "").strip().rstrip("/")
            url = (base_url + "/chat/completions") if base_url else "https://api.deepseek.com/chat/completions"
            model = (cfg.get("ai_model") or "").strip() or "deepseek-chat"
            # P1-10+：人设预设（default/sheshe/tsundere）或用户自定义（custom → ai_system_prompt）
            sys_prompt = self._prompt(cfg)
            max_tokens = int(cfg.get("ai_max_tokens", 60) or 60)
            reply_len = int(cfg.get("ai_reply_len", self._default_reply_len) or self._default_reply_len)
            rounds = int(cfg.get("chat_memory_rounds", 3) or 3)
            mem_epoch = pet._mem_epoch  # 记录清记忆代次：清理动作发生在请求在途时，本次回复不入记忆
            with pet._history_lock:
                history = list(pet._chat_history[-(rounds * 2):]) if rounds > 0 else []
            messages = [{"role": "system", "content": sys_prompt}]
            messages += [{"role": r, "content": c} for r, c in history]
            messages.append({"role": "user", "content": msg})
            resp = requests.post(
                url,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 1.0,
                },
                timeout=20,
            )
            if resp.status_code == 401:
                self.signals.reply.emit("API Key 不对，查一下？")
                return
            if resp.status_code == 402:
                self.signals.reply.emit("DeepSeek 余额不足，去平台充点~")
                return
            if resp.status_code == 429:
                self.signals.reply.emit("问太多次啦，歇会儿再来~")
                return
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip().replace("\n", " ")
            # P3-3：先剥表情标记再截断——截断永远不会切进标记；标记剥除后才展示/入记忆
            mode, kind, text = self._parse_emote(text)
            if mode:
                self.signals.ai_emote.emit(mode, kind)
            if len(text) > reply_len:
                text = text[:reply_len]
            if not text:
                text = "…"  # 纯表情回复：气泡兜底
            with pet._history_lock:
                # Key 已被清除 / 记忆被清理（代次变化）时丢弃本次对话记忆，
                # 清除语义不可被在途请求撤销。
                # 注：_history_lock 只互斥 _chat_history 的 append/clear；cfg["api_key"]
                # 字段本身由 GIL 保证单条赋值原子性，不在此锁覆盖范围。
                if cfg.get("api_key") and pet._mem_epoch == mem_epoch:
                    pet._chat_history.append(("user", msg))
                    pet._chat_history.append(("assistant", text))
                    snapshot = list(pet._chat_history)
                else:
                    snapshot = None
            if snapshot is not None:
                self._save_memory(snapshot)  # P1-6：锁外落盘，原子写不阻塞其他线程
            self.signals.reply_ok.emit()  # 回复成功：由主线程播任务完成音（线程安全）
            self.signals.reply.emit(text)
        except Exception as e:
            self._log("ai_worker: %r" % (e,))
            self.signals.reply.emit("网络不好，听不清啦……")
        finally:
            self.signals.ai_done.emit()
