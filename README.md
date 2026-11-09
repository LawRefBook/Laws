---
draft: true
---

本项目收集各类法律法规、部门规章、案例等，并将其按照章节等信息进行了处理。

## 应用

 - [LawRefBook](https://github.com/RanKKI/LawRefBook) 是原生 iOS 应用，使用 SwiftUI 构建。

## 贡献指南

工具都在 `scripts/` 下，是一个 Python 包，命令行入口是 `laws`。在仓库根目录：

 - `make`（即 `make shell`）：交互菜单，↑↓ 选择、回车确认、Esc 返回上一级，不用记命令；每一项下面显示对应的 `laws` 命令
 - `make lint`、`make lint-fix`：检查格式、自动修复
 - `make db`：更新数据库（先本体，再全部 DLC）
 - `make test`、`make check`：运行测试、检查代码风格
 - `make setup`：安装依赖，第一次使用或 `scripts/pyproject.toml` 变化后运行

装好后可以直接用 `.venv/bin/laws <命令>`（或激活虚拟环境后用 `laws`），`laws --help` 列出全部命令。

### 手动贡献

 - 根据[法律法规模版](法律法规模版.md) 的格式，将法律法规放入 `法律法规` 文件夹下合适的位置
 - 运行 `laws lint` 检查格式（有 error 时退出码为 1）；`--diff` 列出能自动修复的改动，`--fix` 自动修复后再检查
 - 运行 `laws db update`（会自动更新 `sqlite` 内容）
 - 提交更改，并提 pr

### 自动抓取

支持从 [国家法律法规数据库](https://flk.npc.gov.cn)、[国家规章库](https://www.gov.cn/zhengce/xxgk/gjgzk/) 和 [维基文库](https://zh.wikisource.org) 抓取。

 - `laws download-all`（下载尚未收录的法律、行政法规和司法解释，`--limit N` 限制数量）
 - `laws download <名称>`（按名称下载）
 - `laws download-dlc <地区>`（下载地方性法规）
 - `laws download-gz [部门]`（从国家规章库下载部门规章）
 - `laws organize`（列出整理计划；确认后加 `--apply` 移入仓库。仓库里已有的文件不会被覆盖，有变化的会生成 diff）
 - `laws db update`
 - 提交更改，并提 pr

修改解析、入库逻辑后运行 `make test`；想确认对现有数据的影响，改之前和改之后各运行一次 `laws snapshot <目录>`，再 `diff -r` 两个目录。

---

PS 如果你有发现某部法律不完整，有问题，或者需要新增某些，但又不会自己提 pr，你可以在提一个 issue，或者直接联系设置中我的邮箱，我会在下个版本修复或增加