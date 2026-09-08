# Spec: 自动网格建议 + 卡通化改进

> 分支：`feat/auto-grid-cartoon`　日期：2026-09-08

## 目标

1. **M2 网格建议**：扫描候选网格，按 avgΔE + 主体下限推荐最小可用 N，CLI/UI 均可。
2. **卡通化重写**：扁平动漫色块 + 描边上色（非 bitwise_and），Python/JS 对齐。

## 方案评估（简）

| 方案 | 结论 |
|---|---|
| A. 四档并排扫 avgΔE，最小 N≥floor 且 ΔE≤15 | **采用**（本地、可解释） |
| B. 感知哈希/SSIM 选网格 | 过重，不采用 |
| C. 经典 CV 卡通（edgePreserving + LAB k-means + 描边上色） | **采用** |
| D. SD/风格迁移生成卡通 | 需重模型，本项目保持本地经典 CV |

## 计划 Checklist

- [x] `suggest_grid`：候选 [29,39,49,59,60] 过滤 max-grid；主体 floor；推荐规则
- [x] CLI：`--suggest-grid` / `--apply-suggest`
- [x] 缩小：照片路径大图用 BOX/AREA，放大仍 LANCZOS
- [x] `cartoon` 重写（edgePreserving→k-means→描边上色→饱和）
- [x] JS `enhance.js` 对齐（无 OpenCV 近似）
- [x] 预设「人像转插画」默认开启 outline 后处理（CLI 自动 / UI 勾选）
- [x] UI「推荐网格」按钮 + metrics 对比表
- [x] 更新方案文档 M2 + 卡通对比；README
- [x] 合成图单测 + `examples/_synth/`
- [x] `docs/test-*.md` / `docs/review-*.md`

## 验收

- `--suggest-grid` 打印表并给出推荐 N；`--apply-suggest` 用该 N 出图
- cartoon 输出尺寸不变；轮廓为深色像素叠加（非挖空）
- UI 可一键推荐并写入网格下拉
