---
draft: true
---

本项目收集各类法律法规、部门规章、案例等，并将其按照章节等信息进行了处理。

## 应用

 - [LawRefBook](https://github.com/RanKKI/LawRefBook) 是原生 iOS 应用，使用 SwiftUI 构建。

## 贡献指南

### 手动贡献

 - 根据[法律法规模版](法律法规模版.md) 的格式，将法律法规放入 `法律法规` 文件夹下合适的位置
 - 在 `scripts` 目录下运行 `python database.py`（会自动更新 `sqlite` 内容）
 - 提交更改，并提 pr

### 自动脚本

`scripts` 目录下有一 `request.py` 脚本，支持从 [国家法律法规数据库](https://flk.npc.gov.cn) 爬取最新的法律法规。

在 `scripts` 目录下，执行以下指令

 - `python requessts.py` （脚本会自动处理，将新增法律加入列表以及合适的位置）
 - `python database.py` （会自动更新 `sqlite` 内容）
 - 提交更改，并提 pr

---

PS 如果你有发现某部法律不完整，有问题，或者需要新增某些，但又不会自己提 pr，你可以在提一个 issue，或者直接联系设置中我的邮箱，我会在下个版本修复或增加