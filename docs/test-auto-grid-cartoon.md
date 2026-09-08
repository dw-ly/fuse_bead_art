# Test: 自动网格建议 + 卡通化改进

> 日期：2026-09-08　分支：`feat/auto-grid-cartoon`

## 环境

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 自动化（合成图）

```bash
.venv/bin/python scripts/test_auto_grid_cartoon.py
```

覆盖：
- `resize_for_beads`：大图 BOX 缩小 / 小图 LANCZOS 放大
- `suggest_grid`：人像 floor=49，返回合法候选 N 与推荐值
- `cartoon`：输出同尺寸；有深色轮廓像素；整体亮度不过暗（非 AND 挖空）
- `outline_strength=0` 可关闭描边
- `apply_preset('人像转插画')` 得到方形图

产物写到 `examples/_synth/`（目录在 `.gitignore` 内，本地可再生成）。

## CLI 冒烟

```bash
.venv/bin/python scripts/photo2beads.py examples/_synth/portrait_synth.png --suggest-grid --preset 人像
.venv/bin/python scripts/photo2beads.py examples/_synth/portrait_synth.png --apply-suggest --preset 人像转插画 -o /tmp/beads_out
```

预期：打印对比表；推荐 N≥49；人像转插画自动带「卡通描边」后处理。

## UI 手工

1. 打开 `ui/pindou.html`，上传照片
2. 选预设「人像」→ 点「推荐网格」→ metrics 出现表格，网格下拉变为推荐 N，并自动生成
3. 选「人像转插画」→ 「卡通描边」应自动勾选；预览为扁平色块 + 深色轮廓（非泥状挖空）

## JS 语法

```bash
node --check ui/enhance.js && node --check ui/app.js && node --check ui/core.js
```

## 结果（本次执行）

| 项 | 结果 |
|---|---|
| `test_auto_grid_cartoon.py` | 全部通过；推荐 49；cartoon dark_px=1035, mean_lum≈188 |
| CLI `--suggest-grid` | 表正常，推荐 49×49 |
| CLI `--apply-suggest` + 人像转插画 | N=49，自动 outline，avgΔE≈14.3 |
| `node --check` | OK |
