# 资源整理器

![Version](https://img.shields.io/badge/version-1.0.0-3478F6)
![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D4)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![UI](https://img.shields.io/badge/UI-PySide6%20%7C%20Qt-41CD52)

资源整理器是一款面向 Windows 的本地图片、视频和文件夹资源管理工具。它以真实文件夹作为分类，以文件名前缀记录 A/B/C 分级，以 `[标签]` 后缀记录主题标签。即使不打开程序，也能从目录结构和文件名理解整理结果。

应用全程在本地运行，不上传媒体文件，不自动生成分类，也不会直接删除资源。

## 下载

[下载最新版本](https://github.com/bentripcn/ResourceController/releases/latest) · [直接下载 Windows x64 便携包](https://github.com/bentripcn/ResourceController/releases/download/v1.0.0/ResourceController-1.0.0-windows-x64.zip)

下载 `ResourceController-1.0.0-windows-x64.zip` 后完整解压，双击 `ResourceController.exe` 即可运行。发布包已经包含 Qt、Pillow 和 FFmpeg，目标电脑无需安装 Python 或其他运行环境。

> 支持 Windows 10/11 x64。请勿只复制单独的 EXE，程序需要同目录中的运行组件。

## 核心功能

- 自由创建多级分类，分类与真实文件夹结构保持一致。
- 使用 `A_`、`B_`、`C_` 文件名前缀记录分级。
- 一个资源可添加多个扁平标签，标签以 `[标签]` 写入文件名。
- 支持图片、视频和原子文件夹资源；默认不会递归修改文件夹内部内容。
- 支持缩略图网格、列表视图、详情查看、图片预览和视频播放。
- 支持多选、拖放、批量分级、批量标签、批量移动和批量重命名。
- 支持按分类、分级、标签、资源类型和关键词组合筛选。
- 支持 SHA-256 完全重复检测及图片、视频相似重复检测。
- 可从收件箱资源出发，在整个资源库中查找重复项。
- 删除操作会将资源移至待删区；移动、重命名和批量操作均记录日志并支持撤销。
- 支持分类、标签和资源元数据的 JSON 导入与导出。

## 文件与分类规则

资源文件名采用以下格式：

```text
[分级]_[原名] [标签1][标签2].[扩展名]
```

例如：

```text
A_日落 [旅行][海边].jpg
B_街拍 [旅行][街景].jpg
C_旅行视频 [旅行].mp4
```

分类目录在磁盘上使用 `{分类名}` 标记，程序可据此区分分类目录和作为完整资源管理的普通文件夹。文件夹资源始终作为黑盒处理，移动、分级、打标签和重命名只作用于文件夹本身。

## 快速开始

1. 打开程序，在“资源库设置”中选择原始库和目标库。
2. 点击“同步”，建立当前资源库索引和缩略图。
3. 在左侧创建分类，或先在收件箱中为资源设置分级和标签。
4. 将资源拖放或批量移动到目标分类。
5. 使用筛选器浏览资源，或打开“重复资源检查”进行人工择优。

原始库和目标库可以选择同一目录。每个目标库的数据独立保存在其 `.resource-controller-data` 目录中，切换目标库时会读取对应资源库的数据，不会混用索引。

## 播放器操作

| 操作 | 功能 |
| --- | --- |
| 空格 | 播放或暂停视频 |
| 左/右方向键 | 视频后退/前进 3 秒；图片切换上一项/下一项 |
| 上/下方向键 | 切换上一项/下一项 |
| 鼠标滚轮 | 以鼠标位置为中心缩放图片或视频 |
| 放大后按住左键拖动 | 移动画面 |
| `Esc` | 退出全屏 |
| `F11` | 进入或退出全屏 |

开启自动播放后，播放至最后一项会回到第一项继续播放。全屏时将鼠标移到屏幕最底边可显示控制栏。

## 数据与隐私

- 所有媒体分析和索引均在本机完成。
- 缩略图、数据库、备份和待删区保存在目标库的 `.resource-controller-data` 中。
- 缩略图和封面默认不会写入原始媒体目录。
- 文件夹封面只保存引用，不修改文件夹内部图片。
- 去重结果由用户确认，程序不会自动删除重复资源。
- 全局标签、最近路径和全局操作记录保存在应用级数据库中。

## 从源码运行

需要 Python 3.10 或更高版本。

```powershell
git clone https://github.com/bentripcn/ResourceController.git
cd ResourceController
python -m pip install -r requirements.txt
python qt_app.py
```

## 测试

```powershell
python -m unittest discover -q
```

测试覆盖资源扫描、分类与标签、文件操作与撤销、导入导出、重复检测、Qt 交互和播放器行为。测试与功能的对应关系见 [需求实现与验收矩阵](REQUIREMENTS_MATRIX.md)。

## Windows 构建

生成自包含的 Windows 程序目录：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

生成程序目录并打包为版本 ZIP：

```powershell
powershell -ExecutionPolicy Bypass -File .\package_windows.ps1
```

构建结果：

```text
dist/ResourceController/ResourceController.exe
release/ResourceController-1.0.0-windows-x64.zip
```

## 项目结构

```text
ResourceController/
├─ library.py                 # 索引、文件事务、撤销、去重和导入导出
├─ media_tools.py             # FFmpeg 探测、视频抽帧和封面处理
├─ qt_app.py                  # Qt 桌面应用入口
├─ rc_app/
│  ├─ controller.py           # 查询与界面无关的控制层
│  ├─ models.py               # 筛选和资源视图模型
│  └─ ui/                     # 主窗口、播放器、缩略图和交互组件
├─ build_windows.ps1          # Windows 自包含构建脚本
└─ package_windows.ps1        # v1.0.0 发布包脚本
```

更完整的模块说明见 [ARCHITECTURE.md](ARCHITECTURE.md)，后端接口见 [BACKEND_API.md](BACKEND_API.md)。

## 版本

当前稳定版本为 `1.0.0`，对应 Git 标签 [`v1.0.0`](https://github.com/bentripcn/ResourceController/releases/tag/v1.0.0)。
