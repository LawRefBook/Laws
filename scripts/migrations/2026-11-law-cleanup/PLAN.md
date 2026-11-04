# App 迁移计划：2026-11 法律数据清理

这次数据清理改了记录 ID 和段落行号，用户的收藏会受影响，需要在 LawRefBook 里写一次迁移。本计划只描述 App 要做的事，App 代码尚未改动。

## 数据侧发生了什么

基线是线上数据包 `9950d78`（`release:alpha/metadata/laws.meta`）。

| 变化 | 数量 | App 是否要处理 |
|---|---|---|
| 删除重复记录 | 11 条 | 要：ID 换成保留的记录，见 `id_map.json` |
| 段落行号变化 | 37 部 | 要：见 `line_map.json` |
| 目录和层级调整 | 23 部 | 不用：ID 不变，分类和层级来自数据库 |
| 文件改名，`publish` 更正 | 2 部 | 不用：ID 不变 |
| 案例补 `filename` | 27 条 | 不用 |

删除的 11 条里，10 条与保留的记录正文相同，只换 ID。`最高人民法院关于适用《民事诉讼法》的解释(2022-04-02)` 并入 2022-04-01，后者多一段前言，全文行号后移 2 行，在 `line_map.json` 里以旧 ID 为键。

行号变化的原因是补了章节标题、删了正文开头的红头、删了多余目录、拆了 `飞行基本规则`。列举项、标点、零宽字符的改动不影响行号。

## 受影响的用户数据

都在 Core Data 模型 `LawData` 里：

| 实体 | 字段 | 存储 | 处理 |
|---|---|---|---|
| `FavLaw` | `id`（就是法律 ID） | Cloud | 换 ID，去重 |
| `FavContent` | `lawId` + `line` | Cloud | 换 ID，换行号，去重 |
| `SearchHistory` | `lawId` | Local | 换 ID |

`FavFolder` 不引用法律。`lawref://` 链接是运行时生成的，不用处理。`LawContentManager` 的缓存在内存里，重启即失效。

## 映射文件格式

`id_map.json`：`{"removed": {"<旧 ID>": "<保留的 ID>"}}`。ID 是不带横线的 32 位十六进制，转换用 `asDBString()` 的反向逻辑。

`line_map.json`：

```json
{"baseline": "<commit>", "laws": {"<旧 ID>": {"ranges": [[7, 79, -6]], "dropped": [0, 1]}}}
```

- `ranges` 的每一项是 `[起始行, 结束行, 偏移量]`，两端都包含，新行号 = 旧行号 + 偏移量。
- 不在任何区间里的行号不变。
- `dropped` 里的行已不存在。一共 19 行，都是目录、重复标题或发布说明，没有条文。

两个文件按 bundle 资源打进 App。

## 实现步骤

### 1. Core Data 加版本字段

新建模型版本，给 `FavContent` 加可选字段 `contentRev: Integer 64`，默认 0。

`line` 不能只靠本地标记防重复，必须记在记录上。`FavContent` 经 CloudKit 同步，如果两台设备各迁移一次，行号会被偏移两次。

这一步会改 CloudKit schema，发版前要在 CloudKit Dashboard 把 schema 部署到 Production。

### 2. 判断新数据包是否已安装

在主数据库里查 `id_map.json` 的任意一个旧 ID。查不到就说明新包已安装，查得到就跳过迁移。

这样 App 和数据包谁先到都能正常工作，不需要依赖安装顺序。

### 3. 迁移逻辑

放在 `LawManager.connect()` 完成之后执行，只处理主数据库。DLC 的 ID 不在映射里，不受影响。

```swift
for fav in FavContent where contentRev == 0 {
    let old = fav.lawId
    if let entry = lineMap[old] {
        if entry.dropped.contains(fav.line) { delete(fav); continue }
        fav.line += entry.delta(for: fav.line)
    }
    fav.lawId = removed[old] ?? old
    fav.contentRev = 1
}
for fav in FavLaw where removed[fav.id] != nil { fav.id = removed[fav.id] }
for item in SearchHistory where removed[item.lawId] != nil { item.lawId = removed[item.lawId] }
```

完成后去重：

- `FavLaw`：同一 `id` 留 `favAt` 最早的一条。
- `FavContent`：同一 `lawId + line + folder` 留一条。

### 4. 每次启动都跑

CloudKit 的记录可能在迁移之后才到达，所以不要设「已完成」标记。每次启动查一遍 `contentRev == 0`，没有就立刻返回，开销很小。

`FavLaw` 和 `SearchHistory` 的换 ID 本身是幂等的，因为旧 ID 不会再出现。

### 5. 新收藏写入版本

`FavContent.new` 按当前数据包写 `contentRev`：新包已安装写 1，否则写 0。

## 发版顺序

**先发 App，等大多数用户更新后再发数据包。**

旧版 App 拿到新数据包时：

- 11 条被删记录的收藏不显示。记录本身还在，不会丢，`FavoriteContentViewModel` 只是跳过了找不到的法律，新版 App 迁移后能恢复。
- 37 部法规的段落收藏会显示成错误的段落。这个问题要到用户更新 App 才恢复，也是要先发 App 的原因。

## 已知风险

- **基线必须匹配。** `line_map.json` 只对 `9950d78` 到当前工作区成立。发数据包前如果再改法律文件，或者先发了别的数据包，要重跑 `python3 generate.py`，必要时传入新的基线。
- **更早的数据包不在映射范围内。** 还停留在 `9950d78` 之前版本的用户，收藏的行号本来就可能和基线不同，这次迁移不做处理。
- **旧版 App 的多设备场景。** 旧版 App 在新数据包上新建的收藏，`contentRev` 是 0，但行号已经是新的，迁移时会被多偏移一次。先发 App 能把这个窗口压到最小。
- **`飞行基本规则`。** 旧版每章是一整段，收藏映射到该章第一条，无法精确到具体条文。

## 测试

- 单测：`ranges` 边界、`dropped`、不在映射里的法律、连续跑两次结果不变。
- 单测：旧 ID 和保留 ID 都被收藏时，去重后只剩一条，`favAt` 取最早。
- 集成：用旧数据包创建 `民族团结进步促进法` 第一条的段落收藏，切到新包，确认显示的还是第一条。
- 多设备：一台迁移后，另一台同步到 `contentRev == 1` 的记录，确认不会再偏移。

## 映射的生成和校验

`generate.py` 移植了 `LawContentParser` 和 `TLaw.getNames()`。生成时做过这些校验：

- 把 App 的 Swift parser 原样编译，与 Python 版在基线和当前版本上全量对比，共 3523 个文件，行号和规范化文本都没有差异。
- 逐段校验 84688 段，映射后的新旧段落都是同一段文字，其中 131 段有格式或拆并改动，没有错配。

如果 parser 的行号逻辑改了，`generate.py` 要同步修改。尤其注意 Foundation 的 `whitespacesAndNewlines` 包含 U+200B，这一点和 Python 的 `str.strip()` 不同。
