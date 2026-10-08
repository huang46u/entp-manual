# 本地部署

已在 `D:\Code\entp-manual` 部署源码版 2.1.9，使用现有 D 盘 Python 3.12 创建独立 `.venv`。源码基于提交 `e03393eaaa151300c3cb69bbfb96044a2edf3b16`。

## 启动

双击 `start-local.cmd` 或 `启动_ENTP自强手册.bat`。关闭窗口会隐藏到系统托盘；彻底退出请右键托盘图标，选择“退出”。

控制台启动（便于排查问题）：

```bat
cd /d D:\Code\entp-manual
call workspace-env.cmd
.venv\Scripts\python.exe flet_app.py
```

## 存储位置

所有下列路径均相对于当前 workspace：

| 内容 | 路径 |
| --- | --- |
| SQLite 数据库 | `data\entp_manual.db` |
| Markdown 正文及图片附件 | `data\markdown\` |
| 自动备份、默认导出目录 | `data\backups\` |
| 应用错误日志 | `data\logs\` |
| Python 及项目依赖 | `.venv\` |
| pip、Python 字节码、Flet、uv、pub 缓存 | `.cache\` |
| Flet 桌面客户端 | `.runtime\home\.flet\client\` |
| 临时文件、备份解压、客户端 PID 文件 | `.runtime\tmp\` |
| 客户端进程的用户配置目录 | `.runtime\appdata\`、`.runtime\localappdata\` |
| 验证报告、测试数据库和截图 | `.runtime\qa\` |

`workspace-env.cmd` 在创建子进程前设置上述路径；Python 入口也通过 `workspace_runtime.py` 设置路径，确保从源码直接启动时配置仍然生效。环境变量只影响本项目进程，不更改系统级环境变量。运行数据、缓存和虚拟环境已被 Git 忽略。

首次启动保留上游的介绍数据。验证使用独立测试数据库，实际个人数据库不包含验证任务。

## 维护

重新安装依赖或准备客户端：运行 `setup-local.cmd`，要求可用的 Python 3.12 / 3.13 和网络。它将依赖、下载和临时文件保存在 workspace。

源码版关闭安装包升级入口，避免安装版改变存储位置。更新源码时应先退出应用、备份 `data\`，保留这些本地存储配置，再更新依赖。

此启动方式使用 Flet 官方桌面客户端及普通 Markdown 文本编辑器。项目的 Quill 富文本插件需要额外编译自定义 Flutter 客户端；本部署与上游直接从 Python 源码运行的方式一致。

导出备份时默认打开 `data\backups\`；如需保持所有文件在 workspace，请保留该位置。避免把 `--db` 或 `--qa-*` 的输出路径手动设到 workspace 外。外部 Markdown 编辑器会遵循它自己的存储配置。

测试命令（cmd）：

```bat
call workspace-env.cmd
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

## 部署验证

2026-10-08 已通过依赖一致性检查（`pip check`）、120 项单元测试（含存储目录覆盖检查）、19 项桌面端到端场景及 1 项数据契约检查。正常启动截图已人工检查。

桌面验证报告：`.runtime\qa\desktop-e2e-verified.json`；截图：`.runtime\qa\startup.png`。端到端报告也列出了上游尚未提供的功能和需人工操作的系统文件选择对话框。
