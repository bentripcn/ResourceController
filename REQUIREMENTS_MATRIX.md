# 需求实现与验收矩阵

| 需求域 | 当前实现 | 验证入口 |
| --- | --- | --- |
| 根目录扫描 | `Library.scan()` 只扫描原始根、目标库和已登记分类目录；文件夹资源不递归 | `test_library.py` 原子文件夹测试 |
| 原始库与目标库 | 可分别选择；已分类时切换目标库会事务化迁移顶级分类，冲突时拒绝覆盖且可撤销 | `Library.configure()`、目标库迁移回归测试 |
| 分类层级 | `create_category`、`rename_category`、`delete_category`；父分类可同时拥有资源和子分类，浏览父分类会递归显示 | `library.py`、Qt 分类拖放测试 |
| 文件命名 | `A_`/`B_`/`C_` 前缀与扁平 `[标签]` 后缀统一由 `build_name` 重建 | `test_library.py` 命名与批量操作测试 |
| 标签管理 | 新增、删除、重命名、合并；变更批量同步文件名 | `Library.change_tag()`、标签管理界面 |
| 缩略图与封面 | 图片、视频抽帧、文件夹内部首张图片；缓存位于程序数据目录 | `rc_app/ui/thumbnails.py`、封面操作 |
| 预览播放 | 图片预览、视频播放、幻灯片、全屏、系统应用打开；文件夹双击打开资源管理器 | `rc_app/ui/player.py` |
| 视频控制 | 时间轴、左右键 ±3 秒边界夹紧、右键长按 3 倍速、当前帧封面 | `test_qt_ui.py` 视频控制回归 |
| 筛选浏览 | 分类、收件箱、待删区、等级、标签、类型卡片多选、关键词、排序 | `LibraryController.query()`、Qt 筛选回归 |
| 去重 | SHA-256 完全重复；图片/视频感知候选；文件夹默认黑盒 | `Library.duplicates()`、`test_duplicates.py` |
| 高级展开 | 只允许已索引文件夹；临时结果不进 SQLite，界面显示警告并禁用修改 | `expand_folder` 回归测试 |
| 可逆操作 | 文件移动、复制、重命名、分级、标签、封面、分类和待删区均进入操作日志并支持撤销 | `Library._transaction()`、`undo()`、`test_copy.py` |
| 导入导出 | JSON 导出分类、标签和可选资源元数据；导入支持合并或可撤销替换，替换可应用资源元数据并将未包含资源移入待删区 | `export_data()` / `import_data()` |
| 安全与发布 | 不覆盖目标、不直接删除、批量操作备份；内置 FFmpeg；PyInstaller one-folder 构建 | `build_windows.ps1`、`dist/ResourceController` |

## 运行验证

```powershell
python -m unittest discover -q
```

当前回归套件覆盖库、Qt 和去重行为，包括目标库迁移、分类递归浏览和网格筛选。设计 token 和页面结构见
`DESIGN_SPEC.md` 与 `figma_handoff.json`；当前环境没有 Figma 云端写入连接器。
