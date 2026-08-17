# 图标目录（Phase 1 Week 1 占位）

Tauri 打包需要应用图标。当前 `tauri.conf.json` 中 `bundle.active = false`，
开发模式（`npm run tauri dev`）不依赖图标即可运行。

打包（`npm run tauri build`）前需准备：

1. 生成 32x32 / 128x128 / 256x256 PNG 图标（可先用占位图）
2. 运行 `npx @tauri-apps/cli icon <source.png>` 生成全平台图标集
3. 将 `bundle.icon` 指向生成的图标文件，并把 `bundle.active` 改为 `true`

（文档 §12.2：托盘图标按 8 状态 × 4 尺寸 16/24/32/48 设计，Phase 3 实现）
