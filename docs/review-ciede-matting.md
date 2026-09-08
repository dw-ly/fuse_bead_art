# Review: CIEDE2000 + 背景抠图

## 完成项

- CIEDE2000 默认；ΔE76 可选（CLI/UI）
- 抠图 auto：corner_flood → grabcut_face → saliency_soft
- 空白格 `-1` / 空白不拼；用量不含透明

## 局限

- GrabCut 需 OpenCV + 人脸；复杂/纹理背景易失败
- JS≈Python（浮点路径一致，数值可能有微小差）
- saliency 软抠可能残留背景

## 建议后续

- 可选手动笔刷修遮罩；复杂场景提示用户关抠图或换图
