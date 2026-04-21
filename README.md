# 🔥 抖音热点梗分析工具 — 使用指南

> 面向星广联投素材团队的抖音热点梗采集 + AI 分析工具。
> 一键获取当下最火的梗，AI 自动分析出游戏广告素材的创作方向。

## 📌 这个工具能帮你做什么？

1. **自动采集抖音三大榜单**：搜索榜、视频榜、话题榜（数据来自抖音热点宝）
2. **智能过滤**：自动排除政治、灾难、官方活动等不适合做素材的话题
3. **相似话题合并**：同一个热点事件的多个话题自动合并，不浪费分析名额
4. **AI 梗分析**：用 Gemini AI 分析每个热梗，直接给出游戏广告素材的创作方向
5. **输出报告**：Markdown 格式报告，可直接转发给编导团队

---

## 🚀 快速上手（3 步搞定）

### 第 1 步：环境准备（只需做一次）

```bash
# 安装 Python 依赖
pip3 install requests playwright google-genai

# 安装浏览器引擎
playwright install chromium
```

### 第 2 步：热点宝登录（Cookies 过期后需重新登录）

```bash
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/douhot_scraper.py --login
```

会弹出浏览器窗口，**用抖音 APP 扫码登录热点宝**，登录成功后 Cookies 自动保存（有效期约 1-7 天）。

### 第 3 步：一键生成热梗分析报告 🎯

```bash
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py \
  --gemini-key "你的Gemini API Key" \
  --top-topics 8 \
  --top-video-analyze 2
```

等待 5-8 分钟，报告自动生成到 `cache/hotspot_report_今天日期.md`。

---

## 📋 常用命令速查

### 🎯 核心命令：一键热梗分析报告

```bash
# 分析 TOP 8 话题 + 视频榜 TOP 2，使用 AI 分析
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py \
  --gemini-key "AIzaSyXXXXXX" \
  --top-topics 8 \
  --top-video-analyze 2

# 不用 AI，只用规则分析（不需要 API Key，速度更快但质量一般）
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py \
  --top-topics 8

# 输出到桌面
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/hotspot_pipeline.py \
  --gemini-key "AIzaSyXXXXXX" \
  --output ~/Desktop/今日热梗分析.md
```

### 📊 辅助命令

```bash
# 只看热搜榜 TOP 20（快速浏览，不做深度分析）
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/fetch_hotboard.py --top 20 --filter

# 只看热点宝三榜数据（搜索榜+视频榜+话题榜）
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/douhot_scraper.py --list-only

# 搜索某个话题下的视频
python3 ~/.workbuddy/skills/douyin-hotspot/scripts/search_videos.py "误闯天家" --top 5
```

---

## 📊 参数说明

| 参数 | 含义 | 默认值 | 建议值 |
|------|------|--------|--------|
| `--top-topics N` | 分析多少个话题 | 10 | 5-10 |
| `--top-video-analyze N` | 视频榜独立分析几条 | 2 | 2-3 |
| `--videos-per-topic N` | 每个话题取几条关联视频 | 2 | 2 |
| `--gemini-key KEY` | Gemini API Key | 无 | 必填才有 AI 分析 |
| `--gemini-model MODEL` | Gemini 模型 | gemini-3.1-pro-preview | 默认即可 |
| `--output PATH` | 报告保存路径 | cache/hotspot_report_日期.md | 按需指定 |
| `--no-dedup` | 不跳过已分析话题 | 默认去重 | 想重新分析时加 |
| `--skip-ai` | 跳过 AI 分析 | 不跳过 | 只想看数据时加 |

---

## 📝 报告里有什么？

### 话题榜分析（每个话题包含）：
- **热梗标签**：提炼出的核心梗标签
- **话题关联视频**：Top 2 热门视频数据（标题、点赞、评论、链接）
- **梗分析**：1-3 句话说清楚这个梗是什么、怎么用
- **可参考的内容产出方向**：2-3 个具体创作方向，每个方向有示例文案和镜头描述

### 视频榜分析（Top 2 视频）：
- 独立分析视频榜最热的 2 条视频
- 同样包含梗分析 + 创作方向

### 梗参考汇总表：
- 一张表格汇总所有梗，方便快速查阅

---

## ⚙️ Gemini API Key 获取方式

1. 打开 https://aistudio.google.com
2. 用 Google 账号登录
3. 点击「Get API key」→「Create API key」
4. 复制 Key，用在 `--gemini-key` 参数中

> 💡 免费额度完全够用，无需付费。

---

## 🔧 常见问题

**Q: 报告显示"规则分析"而不是 AI 分析？**
A: 没有传 `--gemini-key` 参数，或者 Key 无效。

**Q: 话题榜只有几个话题？**
A: 热点宝 Cookies 可能过期了，重新运行 `--login` 扫码登录。

**Q: 运行报错 "模块不可用"？**
A: 运行 `pip3 install requests playwright google-genai` 安装依赖。

**Q: Gemini 分析很慢？**
A: 正常，每次 AI 分析需要 10-30 秒。如果遇到 503 会自动重试并降级到备选模型。模型降级链：`gemini-3.1-pro` → `gemini-2.5-pro` → `gemini-2.5-flash`。

**Q: 想重新分析今天已分析过的话题？**
A: 加 `--no-dedup` 参数，跳过去重。

---

## 📁 文件结构

```
douyin-hotspot/
├── scripts/
│   ├── hotspot_pipeline.py   # ⭐ 核心：一键热梗分析流水线
│   ├── douhot_scraper.py     # 热点宝数据采集（三大榜单）
│   ├── fetch_hotboard.py     # 热搜榜数据获取（起零数据API）
│   ├── analyze_trends.py     # 热点趋势分析
│   ├── search_videos.py      # 视频搜索
│   └── daily_report.py       # 每日汇总报告
├── prompts/                   # Gemini AI 分析的 prompt 模板
│   ├── system_prompt.md       # 角色设定
│   ├── few_shot_examples.md   # 示例输出
│   ├── output_schema.md       # 输出格式规范
│   ├── task_with_videos.md    # 有视频时的任务模板
│   └── task_without_videos.md # 无视频时的任务模板
├── config/
│   ├── api_config.json        # API 配置
│   ├── filter_rules.json      # 热搜过滤规则
│   └── topic_filter_rules.json # 话题过滤规则
├── cache/                     # 数据缓存（不上传 Git）
└── README.md                  # 本文件
```

---

## 🔄 更新日志

### v2.1（2026-04-21）
- ✅ **话题榜翻页**：从 9 个话题提升到 30+，利用分页器自动翻页
- ✅ **话题聚合去重**：同一事件的多个话题自动合并（如 #机器人马拉松 + #2026人形机器人半马）
- ✅ **视频榜降级分析**：无 Gemini 时也能分析视频榜
- ✅ **双通道选题**：时效性过滤 + 始终保留最新 3 个话题（抓最新热梗）
- ✅ **Gemini 输出优化**：清理 AI 开场白废话，直接输出干货
- ✅ **模型降级链**：3.1-pro → 2.5-pro → 2.5-flash，自动切换

### v2.0（2026-04-15）
- 指导性上下文重构：Gemini prompt 外部化到 prompts/ 目录
- 注入业务背景 + few-shot 示例 + 输出 schema

### v1.0（2026-04-07）
- 核心功能上线：热搜采集、话题过滤、AI 分析、报告生成
