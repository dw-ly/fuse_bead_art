# fuse_bead_art · 照片转拼豆图纸

把照片转换成拼豆（MIDI beads）图纸：**能分辨图片内容，豆量可控（上限 60×60）**。

## 快速开始

**浏览器 UI（推荐，无需安装）**：双击打开 `ui/pindou.html`，拖入照片 → 选主题预设 → 自动生成 → 一键下载 ZIP 素材包（预览图 + 施工图 + 用量清单）。

**桌面 EXE（可选）**：双击 `dist/FuseBeadArt.exe` → 自动打开浏览器使用 UI，完成后点控制窗口【退出】关闭。重新打包见下方「打包成 EXE」。

**Python CLI**：

```bash
pip install -r requirements.txt
python scripts/photo2beads.py 照片.jpg -N 60              # 默认 MARD 291 色板 + kmeans 主色聚类
python scripts/photo2beads.py 照片.jpg -N 49 -p hama -m nearest -L
python scripts/photo2beads.py 照片.jpg -N 60 --preset 花   # 按照片主题自动增强
```

**主题预设**（`--preset`，按主体自动优化）：

| 预设 | 处理 |
|---|---|
| `人像` | 人脸居中裁剪（OpenCV）+ 背景柔化 + 肤色自然 |
| `花` | 强背景柔化 + 饱和提升 + 锐化 |
| `动物` | 背景柔化 + 适度增强 |
| `风景` | 轻降噪 + 饱和提升（不柔化） |
| `插画` | 轻锐化 + 提饱和（适合已扁平的图） |
| `人像转插画` | 卡通化：压平 + 颜色分级 + 勾轮廓线 |
| `通用` | 直接转换，不做增强 |

## 生成内容

| 文件 | 说明 |
|---|---|
| `*_preview.png` | 圆角豆粒成品预览（`-L` 可标注色号） |
| `*_spec.png` | 带色号标注 + 坐标刻度的施工图（可打印对照） |
| `*_usage.csv` | 各色号用量清单（配豆对账用） |

## 核心特性

- **CIELAB + ΔE76 色差量化**——不是 RGB 最近色，符合人眼感知
- **6 个品牌共 1094 个真实色号**（MARD 291 / Artkal / Perler / Hama…），色号表可配置
- 两种量化：**k-means 主色聚类**（照片推荐）/ **直接最近色**
- **色号子集筛选**：只用你实际拥有的豆子颜色（`--only A1,B2`）
- 浏览器端**零后端**：图片不上传服务器，纯本地处理，可离线使用

## 目录

```
scripts/    Python 工具（CLI + 色号解析）
ui/         浏览器 UI（纯 HTML/JS，零依赖，含手写 ZIP 打包）
data/       色号库（6 品牌 1094 色，JSON）
docs/       调研与实现方案文档
```

## 打包成 EXE

```bash
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name FuseBeadArt --add-data "ui;ui" run_app.py
```

生成 `dist/FuseBeadArt.exe`（约 10MB）。EXE 内嵌 `ui/`，启动时在本地起服务器并自动打开浏览器，全流程（传图→预设→图纸→下载 ZIP）均在浏览器完成，无需安装 Python。

## 技术细节

算法管线与分辨率/豆量的权衡分析见 [docs/拼豆像素图生成方案.md](docs/拼豆像素图生成方案.md)。
