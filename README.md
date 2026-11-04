---
draft: true
---

本项目收集各类法律法规、部门规章、案例等，并将其按照章节等信息进行了处理。

## 应用

 - [LawRefBook](https://github.com/RanKKI/LawRefBook) 是原生 iOS 应用，使用 SwiftUI 构建。

## 贡献指南

下面的操作都可以在仓库根目录运行 `make`（即 `make shell`），按菜单选择，不用记命令。另有 `make lint`、`make test`；第一次使用或 `requirements.txt` 变化后运行 `make setup`。

### 手动贡献

 - 根据[法律法规模版](法律法规模版.md) 的格式，将法律法规放入 `法律法规` 文件夹下合适的位置
 - 在仓库根目录运行 `.venv/bin/python scripts/lint.py`，检查格式（有 error 时退出码为 1）
 - 在 `scripts` 目录下运行 `./update_all_db.sh`（会自动更新 `sqlite` 内容）
 - 提交更改，并提 pr

### 自动脚本

`scripts/scrape.py` 支持从 [国家法律法规数据库](https://flk.npc.gov.cn) 抓取最新的法律法规。

在仓库根目录，执行以下指令

 - `.venv/bin/python scripts/scrape.py download-all`（下载尚未收录的法律、行政法规和司法解释，`--limit N` 限制数量）
 - `.venv/bin/python scripts/scrape.py download <名称>`（按名称下载）
 - `.venv/bin/python scripts/scrape.py download-dlc <地区>`（下载地方性法规）
 - `.venv/bin/python scripts/scrape.py organize`（列出整理计划；确认后加 `--apply` 移入仓库。仓库里已有的文件不会被覆盖，有变化的会生成 diff）
 - 在 `scripts` 目录下运行 `./update_all_db.sh`
 - 提交更改，并提 pr

修改解析逻辑后，在仓库根目录运行 `.venv/bin/python -m unittest discover scripts/tests`。

---

PS 如果你有发现某部法律不完整，有问题，或者需要新增某些，但又不会自己提 pr，你可以在提一个 issue，或者直接联系设置中我的邮箱，我会在下个版本修复或增加