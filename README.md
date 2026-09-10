# 九仓 PR 工程效率看板

Python 标准库采集程序 + SQLite + 无外部依赖的网页。覆盖 openeuler 下 ubs-engine、ubs-comm、ubs-virt、ubs-io、ubs-mem、OmniStateStore、ham、ubturbo、ubs-atomic 九个仓库。

在线地址：https://tianli-backkom.github.io/ubs_core_monitor/

GitHub Actions 每天北京时间 07:30（UTC 23:30）自动采集九仓最近 30 天的 master PR，验证后将最新派生快照发布到 GitHub Pages。也可以在仓库 Actions 页面手动运行 `Collect and deploy dashboard`。计划任务可能因 GitHub 平台负载延迟启动。

## 打开与更新

在 PowerShell 中运行：

```powershell
cd D:\monitors
python serve.py --port 8765
```

打开 http://127.0.0.1:8765 。服务仅监听本机，按 Ctrl+C 停止。如果服务已启动，直接打开地址即可。

统一截止时间刷新全部九仓最近 30 天数据：

```powershell
python -X utf8 collect.py --all --days 30
```

单独更新使用 `python -X utf8 collect.py --repo ubs-comm --days 30`；不指定 `--repo` 或 `--all` 时保持只更新 ubs-engine。单仓更新不会覆盖其他仓库。

采集完成后，在看板点击“重新加载快照”。默认 4 个并发请求，共享约 10 次/秒的限速；失败最多重试 3 次。PR 列表、评论、操作日志和 Jenkins 构建索引重新查询；已结束构建的日志和事件元数据复用缓存。`--refresh` 强制更新历史缓存。本地仍由用户手动更新，线上由 GitHub Actions 定时更新。

指定滚动区间截止点：

```powershell
python -X utf8 collect.py --days 30 --until "2026-09-09T21:58:38.753+08:00"
```

截止点控制 PR 创建时间及门禁事件时间；PR 状态仍为本次从平台读取的状态，不是历史状态重建。无时区的截止时间按上海时间解释。

使用同一截止点和 `--offline` 可仅从缓存重算，验证幂等性或调整计算逻辑。`--limit N` 仅用于诊断抽样，会在看板显示显著的非全量提示。

## 看板操作

- **跨仓总览**：默认首页展示九仓对比、跨仓指标、PR 状态筛选、采集时间与状态；点击仓库进入单仓页。跨仓指标直接汇聚入选 PR 的代表值，不平均各仓均值或 P90。无匹配 PR 的仓库仍保留，未知耗时不补零。
- **PR 工程效率**：合并总览与明细，顶部按 PR 代表值展示 E2E、x86、ARM、DT 平均/P90及有效 PR 样本数，下方展示单值耗时和代表 trigger。仓库切换器与返回总览支持跨仓浏览。旧 `#overview`、`#prs` 链接进入 ubs-engine 单仓页；`#repositories` 进入跨仓首页。
- **筛选与排序**：按状态、搜索、完整性选择 PR，代表批次保持固定；支持最新创建、代表 E2E 降序、批次数降序及任务排队/执行/总耗时切换。
- **PR 下钻**：始终显示全部提交、重跑、批次与任务，代表批次标注“用于 PR 效率汇总”并默认展开，不展示 PR 平均/P90。
- **数据质量**：未匹配事件、无门禁 PR、取消批次及采集异常。耗时未知显示空值，不补零。
- **统计口径**：完整定义与本地更新命令。

统计基于原始毫秒；页面主单位是分钟，悬浮可查看秒或毫秒。仓库汇总 CSV 包含仓库采集状态、覆盖率和各项汇总；PR 与批次 CSV 均包含仓库标识。PR 导出包含代表 trigger 编号、链接及 E2E、三类任务全部三种耗时单值，单位毫秒；批次导出保留全部明细并标记代表批次。CSV 对公式前缀转义。本地服务将文件保存至 `web/exports/`，GitHub Pages 使用浏览器直接下载。

## GitHub Pages 自动发布

工作流依次恢复最近缓存、采集九仓、运行 Python 和 Node 测试、执行真实数据审计，再上传 `web/` 并部署 Pages。原始 API 缓存、SQLite、历史 CSV 和备份不会包含在 Pages artifact 或 Git 提交中；线上只公开看板所需的派生 JSON。

若 GitHub-hosted runner 无法访问 GitCode 或 Jenkins，先在 Actions 日志确认是 401/403、网络超时还是任务路径变化。单仓失败会显示采集失败或过期快照；采集进程、测试或审计整体失败时不会部署并覆盖上一版 Pages。可在网络恢复后通过 `workflow_dispatch` 重跑。

## 数据与接口

| 位置 | 用途 |
|---|---|
| `collect.py` | GitCode/Jenkins 只读采集、关联、快照生成 |
| `metrics.py` | 不依赖网络的统计与状态计算 |
| `data/efficiency.sqlite` | PR、事件、批次、子任务、元数据表 |
| `data/raw/*.json` | 按来源 URL 哈希缓存的响应，带抓取时间 |
| `repositories.json` | 九仓标识与 master 分支配置 |
| `repository_store.py` | 仓库隔离持久化、历史迁移、原子发布 |
| `data/repos/NAME.json`、`web/data/repos/NAME.json` | 各仓相同的完整派生快照 |
| `data/repositories.json`、`web/data/repositories.json` | 仓库索引、统一范围、采集状态与快照路径 |
| `data/snapshot.json`、`web/data/snapshot.json` | ubs-engine 兼容快照 |
| `web/core.js` | 可独立测试的前端筛选与统计 |
| `validate.py`、`validate_multi.py` | 原始时间、跨仓隔离、代表值、SQLite 和前端算法独立审计 |

SQLite 的 PR 与事件主键包含仓库标识，批次按完整 Jenkins URL 唯一；任务记录复用完整 URL。首次迁移会在 `data/` 自动保留 `*-before-multi-*.sqlite` 备份，将旧数据归入 ubs-engine。

各仓 trigger 与任务映射从该仓 PR 门禁报告发现，并经 Jenkins 只读接口核验；核验依据保存在快照 `meta.job_mapping`。无法发现或确认的任务明确记录为缺失或异常，不借用别仓映射。

批量采集统一截止时间并隔离失败。失败仓保留上次成功快照，首次失败显示未获取数据；旧快照范围与索引当前范围不一致时不纳入跨仓汇总。采集失败与成功采集零 PR 明确区分。单仓更新时间范围变化后，其他仓库可能因范围不同被排除；使用同一 `--until` 更新或重新 `--all` 恢复统一范围。

使用 GitCode 官方 API v5 的 `pulls`、`comments` 和 `operate_logs`。PR 列表遍历全部分页，再按创建时间和 master 过滤；评论和操作日志完整分页。门禁来源取机器人报告与 Jenkins trigger 历史索引的并集，避免仅依赖最后一次检查。

Jenkins 构建主键为完整任务 URL（含 build number）。从 trigger 控制台发现下游，结合 PR 报告交叉检查，再以子任务 `upstreamBuild`、`upstreamProject` 验证父子关系。GitCode 和 Jenkins 当前公开接口可直接读取；无需复制浏览器 Cookie 或登录凭证。若未来接口需要认证，采集失败会明确标记，不生成虚构结果。

环境信息接口在内存中提取允许的事件字段后才写入缓存：事件类型、请求时间、PR ID、目标分支、重跑评论 ID。其他环境变量不落盘、不进入网页。

## 计算规则

- 每个 trigger 是一个独立批次；提交次数为创建 PR 加推送事件次数，重跑另列。强制推送不会覆盖先前批次。
- 创建 PR 起点取 `created_at`；重跑以评论 ID 精确关联；推送须 PR ID、事件类型与唯一平台推送日志共同匹配，日志时间与 webhook 时间差不超过 5 秒。无法唯一匹配时 E2E 留空，保留独立 Jenkins 跨度。
- SHA 来自平台操作日志。一次推送包含多个 commit 时保留 `shas` 列表，不猜测 head SHA；未确认的 SHA 不影响已经核验的请求时间。
- 全批结束时间取 trigger 与全部子任务结束时间的最大值。成功必须子任务全部成功，不能依据 trigger 自身 SUCCESS。
- 完整且自然结束的成功和失败批次纳入 E2E，取消、未完成、数据不完整和缺失请求时间的批次不纳入。每个 PR 选择 E2E 最长的有效批次；并列取 trigger 编号较大者。任务耗时全部取自该代表批次，不从其他批次补取。缺少任务或同类任务关联不唯一时留空。无有效代表批次的 PR 仍计入 PR 数。
- 排队 = `waitingTimeMillis + blockedTimeMillis + buildableTimeMillis`；执行 = `duration`；总计 = 排队 + 执行；缺少任何排队分项时排队和总计为空。
- P90 使用 `(n−1)×0.9` 位置的线性插值，与 Excel `PERCENTILE.INC` 一致。单仓与跨仓指标均使用每个 PR 的代表值，每项最多一个样本。趋势按 PR 创建日期聚合，覆盖率为有代表批次的 PR 数 / 当前 PR 数。筛选只选择 PR，不改变代表批次。

## 验证

```powershell
python -m unittest discover -s tests -v
node --test tests/frontend.test.cjs
python validate.py
```

浏览器已人工验证：PR 状态筛选、搜索、多次提交和重跑下钻、任务时间线。多仓审计结果见 `data/validation-multi.json`，包含每仓采集状态、PR 数及跨仓有效样本。

接口依据：[GitCode PR API 文档](https://docs.gitcode.com/v1-docs/docs/openapi/repos/pulls/)。

离线重算当前已交付快照：

```powershell
$snapshotIndex = Get-Content data/repositories.json -Raw | ConvertFrom-Json
$cutoff = [DateTimeOffset]::FromUnixTimeMilliseconds($snapshotIndex.end_ms).ToString("o")
python -X utf8 collect.py --all --days 30 --until $cutoff --offline
```

多仓索引 schema_version=3；每仓派生快照保留单仓结构，PR 的 `metrics` 保存代表批次 URL、编号、E2E 毫秒和三类任务的单值耗时；SQLite PR payload 保存同一结构。
