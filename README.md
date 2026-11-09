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

## 数据库

每个数据包有一个 `db.sqlite3`：本体在仓库根目录，DLC 在 `DLC/<名称>/db.sqlite3`。法规文件放在数据库所在目录下的 `category.folder` 里。数据库由 `laws db update` 生成和维护，表的定义在 [`scripts/lawref/db/models.py`](scripts/lawref/db/models.py)。

> 字段、`flags` 的各位、关系类型都是和 App 的约定，**只能加，不能改已有的含义**。

ID 是 UUID，存成 32 位十六进制文本（不带 `-`）。日期是 `YYYY-MM-DD` 格式的文本。

### category

一个目录一条记录。

| 列 | 说明 |
| --- | --- |
| `id` | UUID |
| `name` | 显示名，默认是目录的最后一级 |
| `folder` | 相对数据库所在目录的路径，如 `民法商法`、`部门规章/教育部`、`地方性法规/北京` |
| `isSubFolder` | 是否作为 `group` 下的子目录显示 |
| `group` | 所属分组，如 `法律法规`、`部门规章`；DLC 都是 `地方法规` |
| `order` | 排序；部门规章按国务院机构序列从 500 开始，不在序列里的部门是 599 |

### law

一个文件一条记录，同一部法规的每个版本各是一条。

| 列 | 说明 |
| --- | --- |
| `id` | UUID；update 时保留已有的 ID，只给新文件生成 |
| `level` | 层级，按顶层目录判断：`宪法`、`法律`、`行政法规`、`部门规章`、`司法解释`、`地方性法规`、`案例`，其余目录都是 `法律`；文件名不带日期的记录手工维护 |
| `name` | 名称，不带「中华人民共和国」 |
| `subtitle` | 副标题，如案例的案名；手工维护 |
| `filename` | 文件名（不含 `.md`）；为空时文件名是 `name(publish)` |
| `publish` | 公布日期，取自文件名 |
| `valid_from` | 施行日期，从正文的施行条款读出；读不到、或早于公布日期（修订版沿用原施行日期）时取公布日期 |
| `valid_to` | 失效日期，由 `supersedes`、`abolishes` 关系决定；`2099-12-31` 表示有效；`1970-01-01` 表示已失效、日期未知，是手工标记，update 不改动 |
| `order` | 目录内的排序，如刑法、民法典各编；手工维护 |
| `ver` | 库里同名法规的版本数 |
| `tags` | 逗号分隔的关键词；手工维护 |
| `flags` | 见下方 [flags](#flags) |
| `category_id` | 所属目录，对应 `category.id` |

找文件时在 `category.folder` 下依次试 `filename`、`name(publish)`、`name`、`subtitle` 加上 `.md`（和 App 的 `TLaw.getNames` 一致）。

### flags

`law.flags` 是按位组合的整数，App 打开正文前根据它决定显示哪些按钮。各位和 App 的 `TLaw.Flags` 一一对应。

| 位 | 值 | 名称 | 含义 |
| --- | --- | --- | --- |
| 0 | `1` | `HISTORY` | 修订链上不止一个版本，可以看修订历史。修订链由 `supersedes` 连起来，同一条链上的各个版本都有这一位 |
| 1 | `2` | `TOC` | 正文有目录 |
| 2 | `4` | `INFO` | 正文开头有信息 |

`TOC`、`INFO` 的判断规则和 App 的 `LawContentParser` 一致（App 的单元测试会核对）：

- 逐行去掉首尾空白，跳过空行、一级标题（`# …`）和 `<!-- FORCE BREAK -->`、`<!-- TABLE END -->` 标记
- `<!-- INFO END -->` 之前剩下的任何一行都算信息
- `<!-- INFO END -->` 之后出现 `##`、`###` 等标题就有目录
- 没有 `<!-- INFO END -->` 的文件，全文都算信息，没有目录

「有相关法律」没有对应的位：实施它的规定可能在用户装了的 DLC 里，只有 App 知道，由 App 自己算。

### relationship

法规之间的关系，`source_id` 对 `target_id`，都对应 `law.id`。每次 update 清空重建，`(source_id, target_id, type)` 唯一。

| `type` | source → target | `date` |
| --- | --- | --- |
| `supersedes` | 新版本 → 同名的上一版本（按 `publish` 排序后相邻的两个版本） | source 的施行日期，也就是 target 的失效日期 |
| `abolishes` | 写明「《某法》同时废止」的法规，或者国务院废止行政法规的决定 → 被废止法规的最新版本。几部法规都写了的，取最早施行的那部；案例只是引述，不算 | source 的施行日期，也就是 target 的失效日期 |
| `amends` | 名称里有「决定」「修改」的修改决定 → 被修改的法规在决定公布前的最新版本，也就是修改前的那一版；库里只有之后的版本时指向最早的版本 | 决定的施行日期 |
| `implements` | 实施条例、实施细则、司法解释、法律解释 → 它实施或解释的法律 | 空 |

`implements` 的判断：

- 按名称：「关于适用《某法》…」「关于《某法》第 X 条的解释」「某法实施条例」等，名称里写「修改」「印发」「转发」「废止」某文件的不算
- 部门规章、行政法规、地方性法规还看第一条「根据《某法》…制定本办法」写明的立法依据。部门规章、地方性法规可以指向法律、行政法规，行政法规只能指向法律
- 同名有多个版本时，取 source 施行时已公布的最新版本，都晚于 source 的取最早的版本
- 民法典这类按编拆开的，名称里写了哪一编就指向那一编，没写的指向第一编

DLC 数据库里，`implements` 的 target 可以是本体数据库的法规（如「北京市实施《义务教育法》办法」指向本体的义务教育法），这时 `target_id` 是本体里的 ID，在 DLC 数据库里查不到。其他关系的 target 必须在本库里，`laws db check <数据库>` 和发布时会校验。

---

PS 如果你有发现某部法律不完整，有问题，或者需要新增某些，但又不会自己提 pr，你可以在提一个 issue，或者直接联系设置中我的邮箱，我会在下个版本修复或增加