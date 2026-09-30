# 🐟 大肥鱼桌宠 v1.5.1 —— 配置升级：自动迁移、只存改动、坏值会提醒

按优化清单 **P1-3 配置加版本、迁移、只存 diff** 落地。

## 🗂️ config.json 只存改动项（diff 存储）
- 从「整份覆盖读写」改为**只落盘与默认值不同的键**（api_key 恒存，保证清除 Key 能持久）
- 好处：配置一眼看清改了什么；新增配置键不再污染文件；默认值变化对老用户自动生效

## 🔁 schema 版本 + 自动迁移
- 新增 `schema_version`（当前 v2），迁移函数链 `migrate_config` 为将来字段重命名留位
- **老版本配置首启自动迁移**并立即按新格式重存，全部设置项原样保留（含 DPAPI 密文 Key）
- 读到未来版本的配置时按兼容模式只取认识的键，不回写、不崩

## 🩹 坏值会明确提醒（不再静默改写）
- 启动时检测被自动修正的字段（越界 scale、非法轮数、坏颜色等），**气泡提示一次**并重存修正值
- 修正前后值一并展示，下次启动不再重复提示

## ✅ 回归护栏
- 新增 tests/test_config.py **10 例**（diff 存取 / v1 迁移 / 未来版本兼容 / 坏值修正 / DPAPI 轮转 / 清 Key 持久）
- `_verify_v13.py` 扩到 **132 项**检查；pytest 累计 **48 例**

---

**下载**：下方附件 `daifeiyu-desktop-pet.zip`（绿色版，解压后双击 `启动桌宠.vbs`）
**完整功能**（多形态/开机自启/帧动画/记账等）见 [v1.4.0](https://github.com/xiyan1314/-daifeiyu-desktop-pet/releases/tag/v1.4.0)；v1.5.0 批次见 [v1.5.0](https://github.com/xiyan1314/-daifeiyu-desktop-pet/releases/tag/v1.5.0)
