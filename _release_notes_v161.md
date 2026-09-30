# 🐟 大肥鱼桌宠 v1.6.1 —— 角色模型自由度升级（P1-7 schema）

## 🎨 角色 schema 扩容：形态各自带动画、带状态图、带渲染参数
- `forms[i]` 新增 `animations`（idle/eat/poke/sleep 各自帧序列）、`states`（生气/脸红/哭泣等 10 种资源状态图）、`anchor`/`scale`/`offset`（渲染参数）、`front`（正面图）、`anim_interval_ms`（帧间隔）
- **非首形态不再永远静态**：每个形态可配自己的待机动画；吃/戳/睡动画全部接线（戳戳状态播 poke 帧、睡眠播 sleep 帧循环，未配置回退原静态展示）
- **状态图优先级（P2-5）**：资源图优先、程序化叠图兜底；吃饱版缺图仍回退常态版同名
- 渲染参数解决多形态切换「跳一下」：锚点/缩放/偏移按形态装配（默认值与旧行为数学等价）

## 🔄 无感迁移
- 旧角色数据自动升级：`frames` → `forms[0].animations.idle`、`file` 保留作 still，老用户加载后行为与升级前一致（迁移回归测试覆盖）
- 旧超大角色素材的全局 scale 补偿路径保留（v2 标记区分新旧装配）

## ✏️ 导入高级选项 + 角色可编辑（P2-6）
- 导入向导新增「高级」折叠区：帧间隔/去背景/裁剪/保留原图（默认关）/anchor/scale/offset
- 角色面板新增「编辑…」：改名/形态调序/换图重跑管线**不换 id**/渲染参数/front/10 种状态图

## ✅ 回归护栏
- 新增 tests/test_role_schema.py **14 例**；pytest 累计 **118 例**；`_verify_v13.py` 135 项（断言零改动）

---

**下载**：下方附件 `daifeiyu-desktop-pet.zip`（绿色版，解压后双击 `启动桌宠.vbs`）
**完整功能**见 [v1.4.0](https://github.com/xiyan1314/daifeiyu-desktop-pet/releases/tag/v1.4.0)
