# Review: 自动网格建议 + 卡通化改进

> 日期：2026-09-08　分支：`feat/auto-grid-cartoon`

## 落地内容

1. **M2 网格建议**：`photo2beads.suggest_grid` + CLI `--suggest-grid` / `--apply-suggest`；UI「推荐网格」；主体 floor + avgΔE≤15 规则。
2. **缩小策略**：`resize_for_beads` 大图 BOX/AREA，放大 LANCZOS。
3. **卡通重写**：Python `edgePreservingFilter`→LAB k-means→描边上色→提饱和；JS 多重边缘保持盒滤波 + RGB k-means + 描边上色对齐。
4. **人像转插画默认 outline**（CLI `outline=None` 自动开；UI 预设切换勾选）。
5. 文档：方案 M2 标完成、卡通 CV vs AI 对比、README 用法。

## 方案取舍

- 未引入 SD/风格迁移（体积/GPU/色块不可控）；真动漫角色需外挂模型。
- JS 无 OpenCV：用边缘保持盒滤波近似 bilateral + RGB k-means（非 LAB），与 Python 观感接近但不像素级一致。
- 候选网格固定常见板规格；自定义 N 仍可手选。

## 风险 / 残差

- Haar 人脸在合成肤色椭圆上可能误检（生产照依赖肤色+质心一致性校验）。
- 卡通 k-means 对复杂照片可能仍偏“色块海报”而非二次元；需 generative 模型才能再进一步。
- UI 扫描在大图+多档时主线程可能短暂卡顿（未 WebWorker）。
- `examples/` gitignore，合成样例需本地跑测试生成。

## 建议后续

- 可选 WebWorker 跑 suggest 扫描
- 若用户强需“角色插画”，提供导出增强图到外部 SD 的说明，再量化回豆
