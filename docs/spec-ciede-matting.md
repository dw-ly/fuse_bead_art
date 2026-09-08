# Spec: CIEDE2000 色差 + 背景抠图

> 分支：`feat/auto-grid-cartoon`　日期：2026-09-08

## 目标

1. **CIEDE2000**：量化 / avgΔE / 网格建议默认用 ΔE2000（更符合人眼）；保留 ΔE76 做 A/B。
2. **背景抠图**：本地、无强制 GPU；透明格记为「空白不拼」(`-1`)，豆量不计。

## 方案评估（简）

| 方案 | 结论 |
|---|---|
| A. CIEDE2000 向量化 pairwise（像素×色板） | **采用**；k-means 簇内仍用欧氏，簇→色板用 ΔE |
| B. 仅换 ΔE76→加权欧氏 | 不足，不采用 |
| C. corner_flood / GrabCut+脸 / saliency 自动选 | **采用**（本地经典 CV） |
| D. rembg / 深度学习抠图 | 需重模型，本项目不强制 |

## 管线顺序

`matting → preset enhance → resize → quantize`

## Checklist

- [x] Python `delta_e2000` + CLI `--delta {e76,e2000}` 默认 e2000
- [x] JS `core.js` 同公式；UI 色差选择
- [x] `scripts/matting.py` + `ui/matting.js`；CLI `--matting` / `--matting-mode`
- [x] 透明格 `-1`；预览棋盘格；用量不计空白
- [x] 测试 + README 一行 + review 文档
