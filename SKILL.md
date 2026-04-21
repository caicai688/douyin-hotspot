---
title: "抖音热搜采集与热点分析"
summary: "实时获取抖音热搜榜数据，采集热点视频，调用 Gemini AI 分析视频内容，输出完整的热点分析报告和广告素材创作指导"
read_when:
  - 用户询问抖音热搜、热点、热门话题
  - 用户想了解今天有什么热点可以蹭
  - 用户需要抖音热点数据做内容创作或广告素材
  - 用户提到星广联投、素材制作、创作灵感
  - 用户提到热搜榜、热度排名、话题榜
  - 用户想看某个热点话题下的视频内容
  - 用户想搜索抖音上的视频
  - 用户需要完整的热点分析报告
  - 用户想用 AI 分析抖音视频内容
  - 用户提到热点深度分析、一键分析
---

# 抖音热搜采集与热点分析 Skill

## 🚀 首次使用 / 快速设置

> **IMPORTANT — 首次加载指令（AI 必须执行）：**
>
> 当用户首次加载此 Skill（或用户主动要求"设置/配置/初始化"时），按以下步骤引导：
>
> ### Step 1：检查环境依赖
> 运行以下命令确认 Python 和依赖可用：
> ```bash
> python3 -c "import requests; print('✅ requests 已安装')" 2>&1 || echo "❌ 需要安装: pip3 install requests"
> ```
>
> ### Step 2：检查 API Token
> 读取 `~/.workbuddy/skills/douyin-hotspot/config/api_config.json`，检查 `primary.token` 是否为默认占位符 `"YOUR_TOKEN_HERE"`。
> - 如果是占位符：提示用户需要去 https://api.istero.com 注册并获取 Token，然后填入配置文件。
> - 如果已有真实 Token：跳过此步。
>
> ### Step 3：试跑一次
> 执行以下命令验证一切正常：
> ```bash
> python3 ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py --top 5 --filter --no-cache
> ```
> 如果成功返回热搜数据，说明配置正确。
>
> ### Step 4：🔔 创建定时任务（双任务架构）
> **主动帮用户创建两个定时任务：每小时采集 + 每天汇总分析。**
>
> #### 任务 A：每小时热搜采集
> 使用 `automation_update` 工具创建 automation，参数如下：
> - **name**：`抖音热搜每小时采集`
> - **scheduleType**：`recurring`
> - **rrule**：`FREQ=HOURLY;INTERVAL=1`
> - **status**：`ACTIVE`
> - **cwds**：用户当前工作目录
> - **prompt**：
> ```
> 运行每小时热搜采集脚本，将当前热搜数据追加到今天的汇总文件中：
> python3 ~/.workbuddy/skills/douyin-hotspot/scripts/hourly_collector.py
> 脚本会自动将数据追加到 cache/hourly/YYYY-MM-DD.jsonl。
> 运行完成后无需展示结果，静默完成即可。
> ```
>
> #### 任务 B：每日热点分析报告
> 使用 `automation_update` 工具创建 automation，参数如下：
> - **name**：`每日抖音热点报告`
> - **scheduleType**：`recurring`
> - **rrule**：`FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR=10;BYMINUTE=0`
> - **status**：`ACTIVE`
> - **cwds**：用户当前工作目录
> - **prompt**：
> ```
> 加载 douyin-hotspot skill，基于全天采集数据生成每日热点分析报告：
>
> 1. 先获取今天日期：运行 python3 -c "from datetime import datetime; print(datetime.now().strftime('%Y%m%d'))"
> 2. 运行每日汇总报告脚本：
>    python3 ~/.workbuddy/skills/douyin-hotspot/scripts/daily_report.py --top-hotspots 5 --no-cache --output ~/Desktop/热点日报/热点报告_{日期}.md
>    （将 {日期} 替换为 step 1 得到的日期字符串）
> 3. 该脚本会自动读取全天 hourly_collector 采集的数据，去重合并后过滤、AI 分析、生成报告
> 4. 如果当天无采集数据，脚本会自动降级为实时获取当前热搜进行分析
> 5. 报告生成后，用 open_result_view 展示给用户
> 6. 简要总结今日 TOP 5 热点和推荐蹭的方向
> ```
>
> 告知用户：
> - ✅ 已创建双任务定时系统：
>   - 📡 **每小时采集**：全天不间断采集热搜数据，确保不遗漏热点
>   - 📊 **每天 10:00 汇总报告**：基于全天数据去重分析，生成到桌面 `热点日报` 文件夹
> - 💡 报告也可以随时手动触发："帮我看看今天抖音有什么热点"
> - ⚙️ 如需调整时间，告诉我即可修改

## 能力概述

本 Skill 提供抖音平台实时热搜数据获取、热点视频采集和 AI 深度分析能力，帮助团队快速掌握当日热点动向，为星广联投素材制作提供数据支撑和创作方向建议。

**核心特色**：
- ✅ **双任务架构**：每小时自动采集热搜 + 每天 10 点汇总去重分析，热点覆盖率更高
- ✅ **一键流水线**：热搜采集 → 视频收集 → AI 分析 → 报告生成
- ✅ **热点宝数据源**：通过 douhot.douyin.com 获取视频榜、话题榜、搜索榜三维数据
- ✅ **首次使用自动设置定时任务**（每小时采集 + 每日报告）
- ✅ 自动过滤不适合营销的热点（时政、军事、明星舆论、灾难、官方活动等）
- ✅ 智能白名单 + ignore_whitelist 机制，精准过滤不误伤
- ✅ Playwright 浏览器自动化采集热点视频数据
- ✅ 支持 Gemini AI 深度分析（默认 gemini-3.1-pro-preview，反幻觉约束）
- ✅ 多源冗余数据获取，稳定可靠

## 核心功能

### 1. 获取抖音实时热搜榜

**脚本路径**：`scripts/fetch_hotboard.py`

使用方式：
```bash
# 获取热搜榜（默认 TOP 50，纯文本格式）
python ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py

# ⭐ 获取热搜榜并过滤掉不适合营销的热点
python ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py --filter

# 过滤 + 显示被过滤掉的热点及原因
python ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py --filter --show-filtered

# 获取 TOP 20，Markdown 格式
python ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py --top 20 --format markdown --filter

# 输出原始 JSON（适合程序处理）
python ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py --format json --filter

# 跳过缓存，强制从 API 实时获取
python ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py --no-cache --filter
```

**参数说明**：
- `--top N`：返回 TOP N 条（默认 50）
- `--format`：输出格式，可选 text / markdown / json
- `--no-cache`：跳过本地缓存（缓存有效期 30 分钟）
- `--filter`：⭐ 过滤不适合营销的热点（时政/军事/明星舆论/灾难/社会争议等）
- `--show-filtered`：显示被过滤掉的热点详情及过滤原因

**过滤规则**（配置文件：`config/filter_rules.json`）：

| 过滤类别 | 说明 |
|----------|------|
| 时政类 | 政策、政府、外交、党政、关税、贸易战等 |
| 军事类 | 军事、武器、冲突、战争相关 |
| 明星舆论/花边新闻 | 出轨、丑闻、塌房、粉圈互撕等 |
| 科技发布类 | 品牌新品发布会（蹭热点易被反感） |
| 灾难事故类 | 地震、火灾、事故、伤亡 |
| 社会争议/法律类 | 犯罪、暴力、维权、性别对立等 |
| 官方活动/平台策划类 | 大赛、大赏、盛典、全民挑战、征集活动等（设置 `ignore_whitelist`，不受白名单保护） |

**智能白名单**：即使话题标题命中过滤关键词，如果同时包含"穿搭""教程""挑战""美食""旅游"等营销友好词，仍会保留。但标记了 `ignore_whitelist: true` 的分类（如官方活动类）不受白名单保护，会被强制过滤。

### 2. 热点趋势分析

**脚本路径**：`scripts/analyze_trends.py`

使用方式：
```bash
# 生成热点分析报告（默认启用过滤）
python ~/.workbuddy/skills/douyin-hotspot/scripts/analyze_trends.py

# 不过滤，分析全部热点
python ~/.workbuddy/skills/douyin-hotspot/scripts/analyze_trends.py --no-filter

# 分析 TOP 20 并保存到文件
python ~/.workbuddy/skills/douyin-hotspot/scripts/analyze_trends.py --top 20 --output ~/Desktop/热点报告.md

# 输出 JSON 格式
python ~/.workbuddy/skills/douyin-hotspot/scripts/analyze_trends.py --format json
```

**分析报告包含**：
1. **热点分类分布** — 按类别统计热搜话题分布
2. **热度 TOP 10** — 最高热度话题排行
3. **🎯 可蹭热点推荐** — 筛选出适合广告素材借势的话题，附推荐理由
4. **💡 创作方向建议** — 基于当日热点分布，给出内容创作方向

### 3. ⭐ 热点视频查询

**脚本路径**：`scripts/search_videos.py`

查看某个热点话题下的具体视频内容：

```bash
# 搜索某个热点的相关视频
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos.py "穿搭"

# 按点赞数排序
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos.py "穿搭" --sort likes

# 按最新发布排序
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos.py "穿搭" --sort latest

# 只看1分钟内的短视频
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos.py "穿搭" --duration short

# 只看最近一周的视频
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos.py "穿搭" --time week

# JSON输出
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos.py "穿搭" --format json --top 5
```

**参数说明**：
- `keyword`：搜索关键词（热点话题名称）
- `--top N`：返回前 N 条（默认 10）
- `--sort`：排序方式 default(综合) / likes(最多点赞) / latest(最新)
- `--time`：发布时间 all(不限) / day(一天内) / week(一周内) / halfyear(半年内)
- `--duration`：视频时长 all(不限) / short(1分钟内) / medium(1-5分钟) / long(5分钟以上)
- `--format`：输出格式 text / markdown / json

**返回数据包含**：
- 视频标题/描述
- 作者信息
- 播放量、点赞、评论、分享数
- 视频链接（可直接打开）
- 视频时长

**备注**：如果 API 无法获取视频数据，脚本会自动生成抖音搜索链接供你在浏览器中直接查看。

### 3b. 浏览器采集版（Playwright）

**脚本路径**：`scripts/search_videos_browser.py`

当 API 方式无法获取视频数据时，可使用浏览器自动化方式采集：

```bash
# 需要先安装 playwright
pip install playwright && playwright install chromium

# 通过浏览器采集搜索结果
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos_browser.py "穿搭"

# 显示浏览器窗口（可能需要扫码登录）
python ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos_browser.py "穿搭" --no-headless
```

## 数据源说明

采用多源冗余策略，确保数据稳定性：

| 优先级 | 数据源 | 说明 |
|:------:|--------|------|
| 1 | 起零数据（api.istero.com） | 热搜榜主数据源，已配置 Token 鉴权 |
| 2 | 热点宝（douhot.douyin.com） | 视频榜 + 话题榜 + 搜索榜，Playwright 采集 |
| 3 | 小小API（v2.xxapi.cn） | 热搜榜备用源 |
| 4 | TenAPI（tenapi.cn） | 第二备用源 |

- 主源不可用时自动切换备用源
- 数据本地缓存 30 分钟，避免频繁调用
- 热点宝需要扫码登录，Cookies 有效期约 1-7 天

### 7. ⭐ 热点宝数据采集（视频榜 + 话题榜 + 搜索榜）

**脚本路径**：`scripts/douhot_scraper.py`

通过浏览器自动化访问抖音热点宝（douhot.douyin.com），采集三大榜单数据：

```bash
# 首次使用：扫码登录并保存 cookies
python ~/.workbuddy/skills/douyin-hotspot/scripts/douhot_scraper.py --login

# 采集 Top 10 热搜词 + 视频榜 + 话题榜（Markdown 输出）
python ~/.workbuddy/skills/douyin-hotspot/scripts/douhot_scraper.py --top 10 --list-only

# 输出 JSON 格式（适合程序处理）
python ~/.workbuddy/skills/douyin-hotspot/scripts/douhot_scraper.py --format json

# 输出到文件
python ~/.workbuddy/skills/douyin-hotspot/scripts/douhot_scraper.py --top 10 --list-only --output ~/Desktop/热点宝数据.md
```

**采集到的数据**：

| 榜单 | 数据内容 |
|------|----------|
| 📊 搜索榜 | 热搜词、搜索热度、趋势数据 |
| 🎬 视频榜 | 视频标题、作者、播放量、点赞数、热度分、视频链接 |
| 📌 话题榜 | 话题名、总播放量、发布数、均播放量、热度分、趋势数据 |

**参数说明**：
- `--login`：扫码登录并保存 cookies（首次使用必须执行）
- `--top N`：搜索榜取 Top N（默认 10）
- `--list-only`：只采集榜单数据（不按关键词搜索视频）
- `--format`：输出格式 text / json
- `--output`：输出到文件
- `--debug`：调试模式（保存截图）

**注意**：热点宝 Cookies 会过期，如果采集报错请重新运行 `--login` 扫码登录。

## 配置文件

- **API 配置**：`config/api_config.json`（含 Token、接口地址、字段映射）
- **过滤规则**：`config/filter_rules.json`（营销不适合热点的过滤关键词和规则）
- **缓存目录**：`cache/daily/`（按日期存储即时数据）、`cache/hourly/`（每小时采集汇总 JSONL）

### 4. ⭐ 每小时热搜采集（全天持续采集）

**脚本路径**：`scripts/hourly_collector.py`

每小时自动运行，将当前热搜数据追加到当天的汇总文件中，配合每日报告使用。

```bash
# 执行一次采集（追加到 cache/hourly/YYYY-MM-DD.jsonl）
python ~/.workbuddy/skills/douyin-hotspot/scripts/hourly_collector.py

# 查看当天汇总数据（去重后）
python ~/.workbuddy/skills/douyin-hotspot/scripts/hourly_collector.py --summary

# 查看指定日期的汇总
python ~/.workbuddy/skills/douyin-hotspot/scripts/hourly_collector.py --summary --date 2026-04-10
```

**汇总数据包含**：
- 去重后的话题列表（按标题合并）
- 每个话题的最高热度、出现次数、持续时间
- 首次和末次出现时间

### 5. ⭐ 每日汇总分析报告（推荐）

**脚本路径**：`scripts/daily_report.py`

读取全天采集数据，去重 → 过滤 → AI 分析 → 生成带持续性标签的报告。

```bash
# 🚀 生成今天的每日报告（推荐）
python ~/.workbuddy/skills/douyin-hotspot/scripts/daily_report.py

# 指定分析 TOP 5 热点
python ~/.workbuddy/skills/douyin-hotspot/scripts/daily_report.py --top-hotspots 5

# 指定 Gemini API Key
python ~/.workbuddy/skills/douyin-hotspot/scripts/daily_report.py --gemini-key YOUR_KEY

# 指定分析日期
python ~/.workbuddy/skills/douyin-hotspot/scripts/daily_report.py --date 2026-04-10

# 输出到指定路径
python ~/.workbuddy/skills/douyin-hotspot/scripts/daily_report.py --output ~/Desktop/热点日报/报告.md

# 跳过视频采集 / 跳过 AI 分析
python ~/.workbuddy/skills/douyin-hotspot/scripts/daily_report.py --skip-videos --skip-ai
```

**与 hotspot_pipeline.py 的区别**：
| 维度 | hotspot_pipeline | daily_report |
|------|-----------------|--------------|
| 数据来源 | 实时抓取当前热搜 | 读取全天 hourly 采集数据 |
| 去重 | 无 | 按标题合并，保留最高热度 |
| 持续性标签 | 无 | 🔥🔥🔥全天霸榜 / 🔥🔥高持续 / 🔥中等 / ⚡短时热点 |
| 适用场景 | 即时查看当前热点 | 每日定时汇总分析（推荐） |

**报告持续性标签说明**：
- 🔥🔥🔥 **全天霸榜**：出现次数 ≥ 全天采集次数 80%
- 🔥🔥 **高持续性**：出现次数 ≥ 50%
- 🔥 **中等持续**：出现次数 ≥ 30%
- ⚡ **短时热点**：出现次数 < 30%

### 6. 热点深度分析流水线（即时模式）

**脚本路径**：`scripts/hotspot_pipeline.py`

**一键完成**：热搜采集 → 视频收集 → AI 分析 → 报告生成

```bash
# 🚀 完整流水线（推荐）
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py

# 指定分析 TOP 5 热点，每个热点采集 8 条视频
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py --top-hotspots 5 --videos-per-topic 8

# 使用 Gemini AI 深度分析
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py --gemini-key YOUR_API_KEY

# 也可以用环境变量
export GEMINI_API_KEY=YOUR_KEY
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py

# 指定 Gemini 模型
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py --gemini-key KEY --gemini-model gemini-3.1-pro-preview

# 跳过视频采集（仅基于热搜数据分析）
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py --skip-videos

# 跳过 AI 分析（仅采集数据）
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py --skip-ai

# 输出到指定路径
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py --output ~/Desktop/热点报告.md

# JSON 格式输出（适合程序处理）
python ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py --format json
```

**参数说明**：
- `--top-hotspots N`：分析 TOP N 个热点话题（默认 5）
- `--videos-per-topic N`：每个热点采集 N 条视频（默认 5）
- `--gemini-key`：Gemini API Key（不提供则使用规则分析引擎）
- `--gemini-model`：Gemini 模型名称（默认 gemini-3.1-pro-preview）
- `--skip-videos`：跳过视频采集
- `--skip-ai`：跳过 AI 分析
- `--no-chrome`：不使用本机 Chrome（改用 Playwright 自带浏览器）
- `--output`：指定输出文件路径
- `--format`：输出格式 markdown / json

**分析模式**：
| 模式 | 条件 | 分析深度 |
|------|------|----------|
| 🤖 Gemini AI | 提供 API Key | 深度分析：结合视频内容，给出专业创作指导和投放策略 |
| 📊 规则引擎 | 无 API Key | 基础分析：基于热度、分类、视频数据统计，给出通用创作建议 |

**输出报告包含**：
1. 热点话题概览（分类、热度、营销适配度）
2. 热门视频数据表（标题、作者、点赞、时长、链接）
3. AI/规则分析的创作指导（热点解读、爆款共性、素材建议、投放建议）

## 常见使用场景

**场景 1：早会热点速览（已过滤）**
> "帮我看看今天抖音有什么热点"
> → 执行 `fetch_hotboard.py --top 20 --format markdown --filter`

**场景 2：寻找可蹭热点**
> "今天有什么热点适合做广告素材？"
> → 执行 `analyze_trends.py`（默认已过滤不适合营销的热点）

**场景 3：查看热点下的视频**
> "穿搭这个热点下面都有什么视频？"
> → 执行 `search_videos.py "穿搭" --top 10`

**场景 4：每日热点报告（推荐，基于全天数据）**
> "生成今日热点分析报告"
> → 执行 `daily_report.py --output report.md`（基于全天采集数据，去重后分析）

**场景 5：即时热点分析（不依赖全天采集）**
> "我现在就想看看热点情况"
> → 执行 `hotspot_pipeline.py --top-hotspots 5`（即时抓取当前热搜并分析）

**场景 6：数据对接**
> "把热搜数据给我，我要用来做分析"
> → 执行 `fetch_hotboard.py --format json --filter`

**场景 7：⭐ 一键深度分析（热搜→视频→AI→报告）**
> "帮我做一份完整的热点分析，看看哪些热点适合做广告素材"
> → 执行 `hotspot_pipeline.py --gemini-key KEY`

**场景 8：查看抖音视频榜和话题榜**
> "帮我看看今天抖音视频榜有什么热门视频"
> → 执行 `douhot_scraper.py --list-only`（需要先 `--login` 扫码登录）

## 注意事项

- 起零数据免费账号每日限 100 次调用，已启用缓存机制优化
- 第三方 API 数据可能有 5-15 分钟延迟，非完全实时
- 过滤规则可在 `config/filter_rules.json` 中自定义调整
- 视频搜索如果 API 无法返回数据，会提供抖音搜索链接供手动查看
- 浏览器采集需要安装 playwright，推荐使用 `--use-chrome` 模式
- Gemini AI 分析需要 API Key（可在 https://aistudio.google.com 免费获取）
- 不提供 Gemini Key 时会使用规则分析引擎，仍可生成基础分析报告
- 完整流水线（含视频采集）耗时约 1-3 分钟，取决于网络和热点数量
- 热点宝（douhot.douyin.com）需要扫码登录，Cookies 过期后需重新 `--login`
- 热点宝采集已集成到 pipeline 和 daily_report，会自动在报告中附带视频榜和话题榜数据
