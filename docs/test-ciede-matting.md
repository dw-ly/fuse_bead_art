# Test: CIEDE2000 + 背景抠图

## 用例

1. **CIEDE2000 相同 Lab** → ΔE ≈ 0
2. **已知色对** → ΔE2000 落在公开球区（如蓝对红 ~ 数十）
3. **肤色 vs 绿** → e2000 ≠ e76
4. **合成抠图**：红底 + 蓝圆 → 中心保留、四角透明/空
5. **回归**：`test_auto_grid_cartoon.py` 全过

## 运行

```bash
python scripts/test_ciede_matting.py
python scripts/test_auto_grid_cartoon.py
```
