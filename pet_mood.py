# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 情绪状态机（阶段 2）
MIT License

职责：管理「戳戳情绪链 / 食物情绪 / 调皮事件」三条情绪线，
把结果一律通过信号发射出去，自身不碰任何控件：
- state(str)  ：要求主程序展示某状态图（puzzled/angry/hiss/drool/cry/smug）。
- bubble(str) ：台词气泡。
- emote(str)  ：头顶表情符号（heart/sparkle/tear/anger/exclaim/question/zzz/note/drool，
                 已有绘制器由主程序 _show_emote 提供）。

设计要点：
- 仅依赖 PySide6.QtCore（QObject / QTimer / Signal）与标准库 time/random；
  不 import QApplication/QPixmap，模块可在无 GUI 环境被 import。
- 戳链：距上次 poke 超过 2.5 秒则重置计数为 1，否则 +1；
  计数 1→puzzled、2→angry、>=3→hiss。
- 食物：food_shown 发射馋嘴并启动 8 秒单次定时器，超时触发 _withhold（cry）；
  food_hidden / fed 停掉该定时器。
- 调皮：选型 A——PetWindow 用外部周期定时器调用 tick()，内部按 45~90 秒
  随机间隔节流，到点发射 smug + 得意台词 + sparkle。

Python 3.8 兼容。
"""

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal


# ---------------- 台词库（中文，每组 3~5 条） ----------------
LINES_PUZZLED = [
    "咦？绳匠在戳我？",
    "干嘛呀……人家在睡觉呢。",
    "唔？你碰到我啦？",
    "咦咦咦？发生什么了？",
]
LINES_ANGRY = [
    "又戳！我要生气啦！",
    "再戳我咬你哦！",
    "哼！别闹了啦！",
    "我、我真的会生气的！",
    "你戳上瘾了是不是！",
]
LINES_HISS = [
    "哈——！别过来！",
    "咝——我要翻脸啦！",
    "再戳我，我就躲进水里不出来了！",
    "哼，喜欢的东西我可是会咬住不放的！",
]
LINES_DROOL = [
    "绳匠，小鱼干在哪里！",
    "好香呀……口水都要流下来啦！",
    "就吃一口，就一口嘛~",
    "我闻到了零食的味道！",
    "那个看起来好好吃……",
]
LINES_CRY = [
    "呜……绳匠都不给我吃……",
    "人家等了好久好久……",
    "QAQ 好委屈，我要哭给你看！",
    "肚子咕咕叫，你却不管我……",
    "哼……不理你了……",
]
LINES_SMUG = [
    "嘿嘿，是我干的~",
    "略略略，绳匠抓不到我~",
    "又干了一件坏事，开心！",
    "喜欢的，就咬住不放~",
    "嘿嘿嘿，谁让你没看见呢~",
]
LINES_BLUSH = [
    "诶？绳匠夸我了……",
    "才、才没有很开心呢！",
    "被绳匠夸了……嘿嘿~",
    "别一直夸啦，脸都红了……",
    "绳匠觉得我可爱吗？",
]


class Mood(QObject):
    """情绪状态机：戳链 / 食物 / 调皮 三条情绪线，全部经信号输出。"""

    # 信号：状态图名 / 气泡台词 / 头顶表情符号
    state = Signal(str)
    bubble = Signal(str)
    emote = Signal(str)

    # 常量
    POKE_RESET_SECONDS = 2.5    # 距上次戳超过该秒数即重置戳链计数
    FOOD_WAIT_MS = 8000         # 托盘打开后多久不给吃 → 委屈哭泣（毫秒）
    MISCHIEF_MIN_S = 45.0       # 调皮事件最短间隔（秒）
    MISCHIEF_MAX_S = 90.0       # 调皮事件最长间隔（秒）

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- 戳链状态 ----
        self._last_poke = 0.0
        self._poke_count = 0

        # ---- 食物情绪 ----
        # 8 秒单次定时器：托盘打开一直不给吃，超时触发 _withhold（cry）
        self._food_timer = QTimer(self)
        self._food_timer.setSingleShot(True)
        self._food_timer.setInterval(self.FOOD_WAIT_MS)
        self._food_timer.timeout.connect(self._withhold)

        # ---- 调皮事件（选型 A：外部周期定时器驱动 tick()）----
        # 首次 tick() 立即触发一次（作为首个随机间隔的起点），
        # 之后每次触发后重新随机 45~90 秒的下一次间隔。
        self._next_mischief = 0.0

    def prime_mischief(self):
        """把下一次调皮事件推迟到随机 45~90 秒后（启动时调用，避免刚启动就坏笑）。"""
        self._next_mischief = time.monotonic() + random.uniform(self.MISCHIEF_MIN_S, self.MISCHIEF_MAX_S)

    # ================= 戳链 =================
    def poke(self):
        """戳一下：距上次超过 2.5s 重置计数为 1，否则 +1，按计数晋级情绪。"""
        now = time.monotonic()
        if self._poke_count == 0 or now - self._last_poke > self.POKE_RESET_SECONDS:
            self._poke_count = 1
        else:
            self._poke_count += 1
        self._last_poke = now

        if self._poke_count == 1:
            self.state.emit("puzzled")
            self.bubble.emit(random.choice(LINES_PUZZLED))
            self.emote.emit("question")
        elif self._poke_count == 2:
            self.state.emit("angry")
            self.bubble.emit(random.choice(LINES_ANGRY))
            self.emote.emit("anger")
        else:  # >= 3
            self.state.emit("hiss")
            self.bubble.emit(random.choice(LINES_HISS))
            self.emote.emit("anger")

    # ================= 食物情绪 =================
    def food_shown(self):
        """食物托盘打开 → 馋嘴；并启动 8 秒定时器，超时不给吃就委屈。"""
        self.state.emit("drool")
        self.bubble.emit(random.choice(LINES_DROOL))
        self.emote.emit("drool")
        self._food_timer.start()  # 重复调用会重启 8 秒窗口

    def food_hidden(self):
        """托盘关闭 → 停掉 8 秒定时器（不再进入委屈）。"""
        self._food_timer.stop()

    def _withhold(self):
        """8 秒没吃到 → 委屈哭泣（私有，由食物定时器超时触发）。"""
        self.state.emit("cry")
        self.bubble.emit(random.choice(LINES_CRY))
        self.emote.emit("tear")

    def fed(self):
        """已喂食：只停掉 8 秒定时器，不 emit（吃完展示由外部决定）。"""
        self._food_timer.stop()

    def blush(self):
        """被夸 → 害羞脸红。"""
        self.state.emit("blush")
        self.bubble.emit(random.choice(LINES_BLUSH))
        self.emote.emit("heart")

    def stop_all(self):
        """停止全部内部定时器（退出清理用）。"""
        self._food_timer.stop()

    # ================= 调皮事件 =================
    def tick(self):
        """调皮事件调度（选型 A：由外部周期定时器调用，如 PetWindow 每 1s 调一次）。

        内部用「随机间隔」节流：距上次调皮不足当前随机间隔时直接返回；
        到点则发射 smug + 得意台词 + sparkle，并重新随机下一次 45~90 秒间隔。
        """
        now = time.monotonic()
        if now < self._next_mischief:
            return
        self._do_mischief()
        self._next_mischief = now + random.uniform(self.MISCHIEF_MIN_S, self.MISCHIEF_MAX_S)

    def _do_mischief(self):
        """实际发射「做坏事得意」情绪（由 tick() 调用，也供冒烟测试直接验证）。"""
        self.state.emit("smug")
        self.bubble.emit(random.choice(LINES_SMUG))
        self.emote.emit("sparkle")


if __name__ == "__main__":
    # 冒烟测试：只需 QCoreApplication（模块顶层无 GUI import），
    # 用 QTimer 分步异步驱动，避免同步连续调用受 2.5s 戳链阈值干扰。
    import sys

    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)

    mood = Mood()

    states, bubbles, emotes = [], [], []
    mood.state.connect(states.append)
    mood.bubble.connect(bubbles.append)
    mood.emote.connect(emotes.append)

    def step0():
        mood.poke()  # 计数 1 → puzzled
        QTimer.singleShot(100, step1)

    def step1():
        mood.poke()  # 计数 2 → angry（距上次 100ms < 2.5s）
        QTimer.singleShot(100, step2)

    def step2():
        mood.poke()  # 计数 3 → hiss
        QTimer.singleShot(100, step3)

    def step3():
        mood.food_shown()  # → drool + 启动 8s 定时器
        QTimer.singleShot(50, step4)

    def step4():
        mood._withhold()  # 手动触发超时逻辑 → cry
        QTimer.singleShot(50, step5)

    def step5():
        mood.tick()  # 首次 tick() 立即触发一次 → smug
        QTimer.singleShot(50, finish)

    def finish():
        # 断言戳链：puzzled → angry → hiss
        assert states[:3] == ["puzzled", "angry", "hiss"], states
        # 断言食物情绪与调皮事件
        assert "drool" in states, states
        assert "cry" in states, states
        assert "smug" in states, states
        assert states.count("smug") == 1, states
        # 断言表情符号
        assert emotes[:3] == ["question", "anger", "anger"], emotes
        assert "drool" in emotes, emotes
        assert "tear" in emotes, emotes
        assert "sparkle" in emotes, emotes
        # 断言台词气泡：每个情绪各一次，共 6 条
        assert len(bubbles) == 6, bubbles
        print("MOOD SMOKE OK")
        app.quit()

    QTimer.singleShot(0, step0)
    sys.exit(app.exec())
