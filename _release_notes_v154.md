# 🐟 大肥鱼桌宠 v1.5.4 —— 仓库卫生 + 文档对齐 + 依赖锁定

按优化清单 **P2-2 / P2-3 / P2-7** 三个小项打包落地（本批无运行时功能变化）。

## 📦 P2-2 仓库卫生
- 新增根目录 **CHANGELOG.md**（逐版变更摘要 + 工程备注）；11 个历史版本说明归档至 `docs/release-notes/`
- 删除根目录与 assets/ 重复的 4 张 character*.png（保留 assets/ 版；根目录同名文件仍可覆盖替换）
- 验证素材 `_verify_assets/`（约 80KB）确认保留：CI 与自检依赖，已在 CHANGELOG 注明

## 📚 P2-3 文档与代码对齐
- `docs/阶段计划.md` R3-2 改为实际行为（优雅退出 `QApplication.quit()`，非 `os._exit(0)`）
- 补「当前状态」小节：R1~R3 各条目如实映射到测试/自检，**未覆盖项明确标注**

## 🔒 P2-7 依赖锁定
- 新增 **requirements-lock.txt**：**最小依赖集**精确锁定（运行时 PySide6 6.11.2 全套 + requests 2.34.2 + psutil 7.2.2；打包 PyInstaller 6.22.2；脚本 Pillow 12.1.1；测试 pytest 9.1.1），不含开发机无关包
- 全新环境 `pip install -r requirements-lock.txt` 参考复现；requirements.txt 宽松区间保留作打包参考

---

**下载**：下方附件 `daifeiyu-desktop-pet.zip`（绿色版，解压后双击 `启动桌宠.vbs`）
**完整功能**（多形态/开机自启/帧动画/记账等）见 [v1.4.0](https://github.com/xiyan1314/-daifeiyu-desktop-pet/releases/tag/v1.4.0)
