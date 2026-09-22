# 资源整理器 1.0.0

这是一个面向 Windows 分发的本地资源库桌面应用。每个资源库的资源索引、缩略图、备份和待删区保存在对应目标库目录下的隐藏 `.resource-controller-data` 中；标签目录、最近使用路径和全局操作记录保存在程序级数据库中。启动时不选择资源库则只使用内存状态，不会为资源库在程序目录创建索引，也不会向原始资源目录写入额外媒体文件。分类文件夹使用 `{分类名}` 标记，用户直接查看纯文件夹时仍能识别分类边界。

## 运行

```powershell
python -m pip install -r requirements.txt
python qt_app.py
```

开发版使用 `qt_app.py`，基于 PySide6 提供现代无边框桌面界面；`app.py` 和 `run_windows.bat` 均已指向 Qt 入口。代码按 `rc_app/ui` 的 jobs、models、thumbnails、widgets、player、window 模块维护，`qt_app.py` 保留旧集成所需的兼容导出。使用 `build_windows.ps1` 可生成可交付的 Windows 程序目录。

视频缩略图运行时可通过 `.\install_runtime.ps1` 安装到项目的 `.runtime` 目录，脚本会下载并保存 imageio-ffmpeg 自带的 `ffmpeg.exe`，不会修改系统 PATH。

启动后分别选择“原始库”和“目标库”（可选择同一目录，也可以先选目标库再选原始库），点击“扫描/同步”。目标库用于存放用户创建的分类文件夹；打开已有目标库时，程序会直接读取该目录自己的 `.resource-controller-data`，切换资源库不会混用索引。资源文件名遵循 `A_原名 [标签1][标签2].扩展名` 规则。可通过多选资源执行分级、标签、原名重命名和移动分类；双击文件夹会在系统文件管理器中打开，图片和视频则进入应用内预览。

当前版本覆盖：根目录扫描、图片/视频/文件夹识别、原子文件夹资源、分类层级、A/B/C 分级、扁平多标签、批量改名/移动、待删区、操作日志与撤销、完全重复哈希检测、图片与视频代表帧相似度检测、元数据 JSON 导入导出、关键词/分级/类型/标签筛选、缩略图网格、图片欣赏、视频当前帧封面和文件夹封面引用。

去重默认把文件夹当作黑盒；后端 `duplicates(..., expand_folder=...)` 提供一次性高级展开，结果只存在内存中并明确标记为临时资源，不能传入修改接口。

去重结果中，双击资源或点击“对比本组资源”可连续查看同组候选；勾选框仅用于选择待淘汰资源。播放器支持在鼠标位置滚轮缩放图片和视频（每格约 10%，缩小至适应窗口，最大放大 8 倍），切换资源会重置缩放。上下方向键切换资源，左右方向键对视频跳转 3 秒，空格播放/暂停；全屏时移到最底边显示控制栏，Esc 退出全屏。主界面“隐藏筛选 / 显示筛选”可收起筛选区，已选条件保持生效。

设计交付物见 [`DESIGN_SPEC.md`](DESIGN_SPEC.md) 和 [`figma_handoff.json`](figma_handoff.json)。它们提供颜色、间距、组件状态及页面结构，便于在 Figma 中继续绘制；当前环境未提供 Figma 云端写入接口，因此不会伪造在线文件链接。

维护和验收对应关系见 [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md)。

当前版本为 `1.0.0`。执行 `build_windows.ps1` 会生成 Windows one-folder 程序；将整个 `dist/ResourceController` 文件夹复制到目标电脑后，双击其中的 `ResourceController.exe` 即可运行，不需要安装 Python、PySide6 或 FFmpeg。
