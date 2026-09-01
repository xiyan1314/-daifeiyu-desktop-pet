# 🐟 DaFeiYu Desktop Pet (大肥鱼桌宠)

> A spoiled, greedy, easily-startled desktop pet fish that calls you "Proxy" (绳匠)~
> Catchphrase: **What I like, I never let go~**

A Windows desktop pet built with **PySide6 (Qt6) + Python 3.10**, MIT licensed.
Transparent frameless window, always-on-top, draggable, feedable, chatty — perfect coding companion.

中文介绍见 [README.md](README.md)。

## ✨ Features

- 🖼️ **Two forms with frame animation**: Normal + Full (round belly); 10-frame idle + 7-frame eating animation
- 😠 **Poke chain**: poke → puzzled, poke again within 2.5s → angry, again → hissing threat
- 🍰 **Feeding**: dried fish / cake / diamond; click to launch it flying into her mouth, or drag & drop
- 💬 **AI chat**: DeepSeek API, replies in short cute Chinese (≤25 chars) with short-term memory
- 🐍 **Xixifu-style personality** (Zenless Zone Zero's Cissia, aka "啥子蛇"): self-proclaimed "villain" who follows only her instincts — cold-tongued but soft-hearted, calls herself "本专员" (this commissioner) and wraps her gluttony in fake case investigations, sometimes hisses "嘶~"
- 💰 **Balance widget** (optional): DeepSeek API balance + today's usage, rolling numbers, auto-refresh every 60s
- 🔐 **Key security**: API Key encrypted with Windows DPAPI, never stored in plaintext
- 🎵 **Sounds**: press / release / feed (winsound-first chain, fallback-safe)
- 😴 **Idle life**: falls asleep after 60s, occasional mischievous grins, blushes when praised
- 📌 Single instance, tray icon, follow mouse / wander, wheel resize, edge snapping

## 🚀 Quick Start

**Option 1: Portable build (recommended, no Python needed)**

Download `daifeiyu-desktop-pet.zip` from [Releases](../../releases) → extract → double-click `启动桌宠.vbs`.
(Uses Microsoft-signed pythonw.exe + bundled runtime; no self-extracting exe that antivirus flags.)

**Option 2: Run from source**

```bash
pip install -r requirements.txt
python 桌宠.py
```

## 🎮 Controls

- Left-drag to move; hold for a squishy Q-bounce effect
- Right-click menu: resize / always-on-top / sound / feed / food tray / form switch / follow mouse / wander / AI chat / set & clear API Key / balance widget / check balance / weather / system status / about / quit
- Poke 3 times in a row for the full emotion chain; praise her to make her blush
- Full form digests back to normal after ~12 seconds

## 🧠 AI Chat & Balance (optional)

1. Right-click → "设置DeepSeek API Key" and paste your key (sk-...)
2. Right-click → "和它说话" to chat; enable "余额挂件" for the balance widget
3. Before sharing, right-click → "清除DeepSeek API Key" to wipe key/ledger/logs

> All network calls use HTTPS with timeouts; the key is DPAPI-encrypted and bound to your Windows account.

## 🛡️ Antivirus note

Unsigned PyInstaller exes get false-flagged by AV/ML engines (we saw Defender report `Wacapew.C!ml`),
so this project ships a **portable build** (pythonw.exe + source) by default — nothing for AV to flag.
All source code is public for review.

## 📁 Structure

```
desktop-pet/
├── 桌宠.py              # main app (window / interactions / AI / balance)
├── pet_anim.py          # frame animation module
├── pet_mood.py          # mood state machine
├── pet_audio.py         # sound module (winsound-first, 3-level fallback)
├── assets/              # frames / expressions / sounds (256px)
├── 去背景.py            # background removal tool
├── 生成占位角色.py      # placeholder generator
├── 启动桌宠.bat         # source-run launcher
├── 大肥鱼桌宠.spec      # PyInstaller spec (optional exe build)
└── docs/                # design docs
```

## 📜 License

[MIT](LICENSE) © DaFeiYu Desktop Pet Project