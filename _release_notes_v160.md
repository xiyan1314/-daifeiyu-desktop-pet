# 🐟 大肥鱼桌宠 v1.6.0 —— P0-1 拆分 PetWindow 上帝类

## 🏗️ 架构重构（行为逐像素等价）
- 从 3700+ 行的 PetWindow 抽出 **12 个新模块**：
  - 5 个服务：`pet_balance`（余额/记账/预警）、`pet_weather`（天气）、`pet_chat`（AI 对话+记忆+人设+表情）、`pet_wander`（跟随/散步几何）、`pet_menu`（右键菜单 47 项结构原样）
  - 7 个支持模块：`pet_screen` / `pet_config` / `pet_lines` / `pet_widgets`（气泡/挂件/托盘/程序化表情）/ `pet_main`（单实例/清理/内存自测）/ `pet_ai` / `pet_actions`
- 服务全部**构造注入、零 import 桌宠**，可在无 QApplication 环境 import 与单测
- 关键模块级名字（config/日志/记忆/脱敏等 41 个）AST+runtime 双检保留，tests/v13 全部无需改动

## 📏 数字（如实汇报）
- 桌宠.py：**3743 → 2105 行（-44%）**；PetWindow：**128 → 91 方法（-29%）**
- 清单的 <1200 行/<60 方法目标未完全达成：渲染/精灵装配/变换/戳戳拖动/喂食/睡觉/表情/气泡/挂件/托盘/穿透/关于/退出约 1500 行、63 方法按「行为逐像素等价」约束不可外移——可移部分已全部抽走，剩的是窗口本体的必要实现

## 🎁 随附：P1-手感物理核心（批次 D 提前落地）
- 新增 `pet_physics.py` **纯函数模块**（轨迹估速/软上限/重力反弹/地面摩擦/落地 Q 弹曲线，参数与清单一致）+ `tests/test_physics.py` **15 例**
- 开关接入（右键「甩抛物理」+ 拖拽飞行）随批次 D 发布；本期仅落地无副作用的纯逻辑

## ✅ 回归护栏
- pytest 累计 **102 例**（含 physics 15 例）；`_verify_v13.py` 135 项；绿色版检测 0 FAILS
- 重构过程中修复 3 个自建 bug（QCursor 归属/回调未调用/WidgetAction 导入），全部被护栏当场抓住

---

**下载**：下方附件 `daifeiyu-desktop-pet.zip`（绿色版，解压后双击 `启动桌宠.vbs`）
**完整功能**见 [v1.4.0](https://github.com/xiyan1314/daifeiyu-desktop-pet/releases/tag/v1.4.0)
