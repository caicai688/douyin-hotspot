#!/usr/bin/env python3
"""
抖音热点梗分析流水线 v2

以热点宝话题榜为主要信息源，辅以视频榜 top 视频：
1. 采集话题榜 + 视频榜 → 过滤话题（时间/内容/去重）
2. 对每个话题访问详情页获取关联热门视频 top2
3. 调用 Gemini 分析视频内容+脚本，提炼可用的梗
4. 视频榜 top2 视频做独立脚本分析
5. 汇总生成报告（含梗参考汇总表格）

用法：
  python hotspot_pipeline.py --gemini-key YOUR_KEY
  python hotspot_pipeline.py --top-topics 10 --top-video-analyze 2
  python hotspot_pipeline.py --output ~/Desktop/热点梗分析.md
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CACHE_DIR = SKILL_DIR / "cache"
CONFIG_DIR = SKILL_DIR / "config"

# 导入现有模块
sys.path.insert(0, str(SCRIPT_DIR))
from fetch_hotboard import load_config, fetch_hotboard, format_hot_value, load_filter_rules, filter_items
from analyze_trends import categorize_topic, AD_FRIENDLY_CATEGORIES, get_ad_reason


# ============================================================
# 话题过滤逻辑
# ============================================================

def load_topic_filter_rules():
    """加载话题过滤规则"""
    path = CONFIG_DIR / "topic_filter_rules.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def filter_challenges(challenges, filter_rules=None, analyzed_ids=None):
    """
    过滤话题榜，保留适合游戏广告素材的娱乐性话题。
    
    过滤条件（在此阶段应用的）：
    1. 去重 — 之前分析过的 challenge_id 跳过
    2. 去非娱乐内容 — 涉政、公共舆论、明星绯闻等（屏蔽关键词）
    3. 去抖音官方大赛/大赏/挑战赛（屏蔽前缀）
    
    注意：时效性过滤（2025年后 OR 近30天有视频）在详情页采集后统一执行，
    因为榜单数据不一定带 create_time，且老话题可能近期重新爆发。
    """
    if not filter_rules:
        filter_rules = load_topic_filter_rules()
    
    if analyzed_ids is None:
        analyzed_ids = set()
    
    blocked_keywords = filter_rules.get("blocked_keywords", [])
    blocked_prefixes = filter_rules.get("blocked_prefixes", [])
    
    kept = []
    removed_reasons = {}
    
    for ch in challenges:
        cid = ch.get("challenge_id", "")
        cname = ch.get("title", "") or ch.get("challenge_name", "")
        
        # 过滤 1: 已分析过的（去重）
        if cid and str(cid) in analyzed_ids:
            removed_reasons[cname] = "已分析过"
            continue
        
        # 过滤 2: 屏蔽关键词（非娱乐内容）
        blocked = False
        for kw in blocked_keywords:
            if kw in cname:
                removed_reasons[cname] = f"命中屏蔽词: {kw}"
                blocked = True
                break
        if blocked:
            continue
        
        # 过滤 3: 官方前缀
        for prefix in blocked_prefixes:
            if cname.startswith(prefix):
                removed_reasons[cname] = f"官方话题: {prefix}"
                blocked = True
                break
        if blocked:
            continue
        
        kept.append(ch)
    
    return kept, removed_reasons


def merge_similar_topics(challenges):
    """
    合并同一事件的相似话题，保留热度最高的。
    
    合并策略：
    1. 话题名互为子串（如 "机器人马拉松" 包含于 "2026人形机器人半马" 的核心词）
    2. 话题名有高 Jaccard 字符相似度（> 0.4）
    3. 同一组中保留 score 最高的，其他作为别名记录
    
    Returns:
        tuple: (merged_list, merge_log)
    """
    if len(challenges) <= 1:
        return challenges, {}
    
    import re
    
    def _extract_keywords(name):
        """提取话题名中的关键词集合（多粒度 n-gram + 核心词）"""
        # 去掉纯数字年份前缀（如 "2026"）
        name = re.sub(r'^\d{4}', '', name)
        tokens = set()
        # 提取连续中文片段
        cn_parts = re.findall(r'[\u4e00-\u9fff]{2,}', name)
        for part in cn_parts:
            tokens.add(part)  # 完整片段
            # 2-gram, 3-gram, 4-gram
            for gram_len in [2, 3, 4]:
                for i in range(len(part) - gram_len + 1):
                    tokens.add(part[i:i+gram_len])
        # 英文单词（小写）
        en_parts = re.findall(r'[a-zA-Z]+', name.lower())
        tokens.update(en_parts)
        return tokens
    
    def _core_word_overlap(name_a, name_b):
        """检查两个话题名是否共享核心词（3字以上的公共子串）"""
        clean_a = re.sub(r'[\s\d#年月日]', '', name_a)
        clean_b = re.sub(r'[\s\d#年月日]', '', name_b)
        # 从较短的名称中提取 3 字以上子串，看是否出现在较长名称中
        short, long_ = (clean_a, clean_b) if len(clean_a) <= len(clean_b) else (clean_b, clean_a)
        for length in range(min(len(short), 6), 2, -1):  # 从 6 字开始到 3 字
            for i in range(len(short) - length + 1):
                substr = short[i:i+length]
                if substr in long_:
                    return True, substr
        return False, ""
    
    def _similarity(name_a, name_b):
        """计算两个话题名的相似度（综合多种策略）"""
        # 策略 1: 互为子串（去数字/空格后）
        clean_a = re.sub(r'[\s\d#]', '', name_a)
        clean_b = re.sub(r'[\s\d#]', '', name_b)
        if len(clean_a) >= 2 and len(clean_b) >= 2:
            if clean_a in clean_b or clean_b in clean_a:
                return 0.85
        
        # 策略 2: 核心词重叠（3字以上公共子串）
        has_core, core_word = _core_word_overlap(name_a, name_b)
        if has_core and len(core_word) >= 3:
            return 0.6
        
        # 策略 3: Jaccard n-gram 相似度
        kw_a = _extract_keywords(name_a)
        kw_b = _extract_keywords(name_b)
        if not kw_a or not kw_b:
            return 0.0
        intersection = kw_a & kw_b
        union = kw_a | kw_b
        return len(intersection) / len(union) if union else 0.0
    
    # Union-Find 分组
    n = len(challenges)
    parent = list(range(n))
    
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    
    # 两两比较相似度
    names = [ch.get("title", "") or ch.get("challenge_name", "") for ch in challenges]
    SIMILARITY_THRESHOLD = 0.35
    
    for i in range(n):
        for j in range(i + 1, n):
            sim = _similarity(names[i], names[j])
            if sim >= SIMILARITY_THRESHOLD:
                union(i, j)
    
    # 按组聚合，每组保留 score 最高的
    groups = {}
    for i in range(n):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(i)
    
    merged = []
    merge_log = {}
    
    for root, indices in groups.items():
        if len(indices) == 1:
            merged.append(challenges[indices[0]])
        else:
            # 按 score 降序取最高的
            best_idx = max(indices, key=lambda i: challenges[i].get("score", 0))
            best = challenges[best_idx]
            others = [names[i] for i in indices if i != best_idx]
            best_name = names[best_idx]
            merge_log[best_name] = others
            merged.append(best)
    
    return merged, merge_log


# ============================================================
# 已分析话题记录（去重用）
# ============================================================

ANALYZED_TOPICS_PATH = CACHE_DIR / "analyzed_topics.json"

def load_analyzed_topics():
    """加载已分析过的话题 ID 集合"""
    if ANALYZED_TOPICS_PATH.exists():
        try:
            with open(ANALYZED_TOPICS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(str(x) for x in data.get("ids", []))
        except Exception:
            pass
    return set()


def save_analyzed_topics(ids_set):
    """保存已分析过的话题 ID"""
    ANALYZED_TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ANALYZED_TOPICS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "ids": list(ids_set),
            "updated_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)

def step1_get_hotspots(top_n=5, no_cache=False):
    """
    Step 1: 采集热点宝话题榜+视频榜，过滤后返回待分析话题列表。
    
    数据源优先级：热点宝话题榜（主） + 起零数据热搜（补充）
    """
    print("\n" + "=" * 70)
    print("📡 Step 1: 采集热点宝榜单 + 过滤话题")
    print("=" * 70)

    # 1a. 采集热点宝三榜
    douhot_billboard = None
    try:
        from douhot_scraper import fetch_billboard_data, check_cookies_valid
        valid, msg = check_cookies_valid()
        if valid:
            print("  🔄 采集热点宝榜单数据...")
            douhot_billboard = fetch_billboard_data(headless=True)
        else:
            print(f"  ⚠️ 热点宝: {msg}")
    except ImportError:
        print("  ⚠️ 热点宝模块不可用")

    challenges = douhot_billboard.get("challenges", []) if douhot_billboard else []
    top_videos = douhot_billboard.get("top_videos", []) if douhot_billboard else []
    top_videos_std = douhot_billboard.get("top_videos_std", []) if douhot_billboard else []

    print(f"  📌 话题榜: {len(challenges)} 个话题")
    print(f"  🎬 视频榜: {len(top_videos)} 条视频")

    # 1b. 起零数据热搜作为补充（暂不用于分析，仅存档）
    config = load_config()
    search_items, source, error = fetch_hotboard(config, use_cache=not no_cache)
    if search_items:
        print(f"  🔍 搜索榜: {len(search_items)} 条热搜 (来源: {source}，仅作参考)")

    # 1c. 过滤话题
    analyzed_ids = load_analyzed_topics()
    filter_rules = load_topic_filter_rules()
    filtered, removed = filter_challenges(challenges, filter_rules, analyzed_ids)
    
    if removed:
        print(f"\n  🔍 话题过滤: 保留 {len(filtered)}/{len(challenges)} 个")
        for name, reason in list(removed.items())[:5]:
            print(f"     ❌ #{name}: {reason}")
        if len(removed) > 5:
            print(f"     ... 另有 {len(removed) - 5} 个被过滤")

    # 1d. 合并同一事件的相似话题（如 #机器人马拉松 和 #2026人形机器人半马）
    merged, merge_log = merge_similar_topics(filtered)
    if merge_log:
        print(f"\n  🔗 话题聚合: {len(filtered)} → {len(merged)} 个")
        for main_name, aliases in merge_log.items():
            print(f"     🔗 #{main_name} ← 合并 {', '.join('#' + a for a in aliases)}")

    selected = merged[:top_n]
    
    print(f"\n  🎯 选定 {len(selected)} 个话题进行深度分析:")
    for i, ch in enumerate(selected):
        name = ch.get("title", "")
        score = _format_count(ch.get("score", 0))
        print(f"     {i+1}. #{name} (热度分: {score})")

    return selected, douhot_billboard, search_items


# ============================================================
# Step 2: 采集话题详情页的关联视频
# ============================================================

def step2_collect_topic_videos(topics, top_videos_per_topic=2):
    """
    对每个话题访问详情页，获取关联的热门视频 top2。
    """
    print("\n" + "=" * 70)
    print("📌 Step 2: 采集话题详情 + 关联热门视频")
    print("=" * 70)

    if not topics:
        print("  ⚠️ 无待分析话题")
        return []

    try:
        from douhot_scraper import fetch_topics_with_videos
    except ImportError:
        print("  ⚠️ douhot_scraper 模块不可用")
        return [{"topic": t, "detail": {"error": "模块不可用", "top_videos": []}} for t in topics]

    details = fetch_topics_with_videos(
        topics,
        top_videos_per_topic=top_videos_per_topic,
        headless=True,
    )

    results = []
    for i, (topic, detail) in enumerate(zip(topics, details)):
        n_vids = len(detail.get("top_videos", []))
        results.append({
            "topic": topic,
            "detail": detail,
        })
    
    return results


# ============================================================
# Step 3: Gemini AI 分析（话题梗 + 视频脚本）
# ============================================================

def step3_ai_analysis(topic_data, video_billboard_top=None, api_key=None, model_name="gemini-3.1-pro-preview"):
    """
    AI 分析两部分内容：
    1. 话题榜：对每个话题+其关联 top 视频进行梗分析
    2. 视频榜：对视频榜 top2 做独立的视频脚本分析
    """
    print("\n" + "=" * 70)
    print("🤖 Step 3: AI 智能分析")
    print("=" * 70)

    # 检查 Gemini SDK
    gemini_available = False
    if api_key:
        try:
            from google import genai
            gemini_available = True
            print(f"  ✅ Gemini SDK 已就绪, 模型: {model_name}")
        except ImportError:
            print("  ⚠️ google-genai 未安装，将使用规则分析模式")
    else:
        print("  ℹ️ 未提供 Gemini API Key，使用规则分析模式")

    # 3a. 话题梗分析
    print("\n  📌 === 话题榜分析 ===")
    topic_results = []
    for item in topic_data:
        topic = item["topic"]
        detail = item["detail"]
        cname = detail.get("challenge_name", "") or topic.get("title", "")
        top_videos = detail.get("top_videos", [])

        print(f"\n  🔍 话题: #{cname} (关联视频: {len(top_videos)} 条)")

        if gemini_available and api_key:
            # 构建话题作为 hotspot 对象
            hotspot_obj = {
                "title": cname,
                "category": categorize_topic(cname)[0],
                "hot_value": detail.get("hot_score", topic.get("score", 0)),
            }
            # 将话题关联视频转为标准格式
            std_videos = []
            for v in top_videos:
                std_videos.append({
                    "title": v.get("title", ""),
                    "author": v.get("author", ""),
                    "url": v.get("url", ""),
                    "likes": v.get("like_cnt", 0),
                    "comments": v.get("comment_cnt", 0),
                    "shares": v.get("share_cnt", 0),
                    "plays": v.get("play_cnt", 0),
                    "duration_ms": v.get("duration", 0),
                })
            analysis = _gemini_analyze(api_key, model_name, hotspot_obj, std_videos)
        else:
            hotspot_obj = {
                "title": cname,
                "category": categorize_topic(cname)[0],
                "hot_value": detail.get("hot_score", 0),
            }
            analysis = _rule_based_analyze(hotspot_obj, [])

        topic_results.append({
            "topic": topic,
            "detail": detail,
            "analysis": analysis,
        })

    # 3b. 视频榜 top2 独立脚本分析
    print("\n  🎬 === 视频榜 Top 视频分析 ===")
    video_results = []
    if video_billboard_top:
        for i, v in enumerate(video_billboard_top):
            vtitle = v.get("title", "")[:40]
            print(f"\n  🔍 视频榜 #{i+1}: {vtitle}")
            
            hotspot_obj = {
                "title": v.get("title", ""),
                "category": "视频榜热门",
                "hot_value": v.get("score", v.get("play_count", 0)),
            }
            std_video = [{
                "title": v.get("title", ""),
                "author": v.get("author", ""),
                "url": v.get("url", f"https://www.douyin.com/video/{v.get('item_id', '')}"),
                "likes": v.get("like_count", 0),
                "comments": 0,
                "shares": 0,
                "plays": v.get("play_count", 0),
                "duration_ms": v.get("duration", 0),
            }]
            
            if gemini_available and api_key:
                analysis = _gemini_analyze(api_key, model_name, hotspot_obj, std_video)
            else:
                analysis = _rule_based_analyze(hotspot_obj, std_video)
            
            video_results.append({
                "video": v,
                "analysis": analysis,
            })

    return topic_results, video_results


def _load_prompt_template(template_name):
    """从 prompts/ 目录加载 prompt 模板文件"""
    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    filepath = prompts_dir / template_name
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return None


def _build_prompt(hotspot, videos, video_summaries_text, video_urls):
    """基于外部模板文件构建完整的 Gemini prompt"""
    keyword = hotspot["title"]
    category = hotspot.get("category", "其他")
    hot_value = format_hot_value(hotspot.get("hot_value", ""))
    today = datetime.now().strftime("%Y年%m月%d日")

    # 加载各模块
    system_prompt = _load_prompt_template("system_prompt.md") or ""
    few_shot_examples = _load_prompt_template("few_shot_examples.md") or ""
    output_schema_full = _load_prompt_template("output_schema.md") or ""

    # 只取 Markdown 输出格式部分（去掉 JSON 部分，Gemini 用 Markdown 输出）
    output_schema_md = output_schema_full
    json_marker = "## JSON 输出格式"
    if json_marker in output_schema_md:
        output_schema_md = output_schema_md[:output_schema_md.index(json_marker)].rstrip()

    has_real_videos = len(video_summaries_text.strip()) > 0

    if has_real_videos:
        template = _load_prompt_template("task_with_videos.md")
    else:
        template = _load_prompt_template("task_without_videos.md")

    if template:
        # 用模板渲染
        prompt = template.replace("{system_prompt}", system_prompt)
        prompt = prompt.replace("{few_shot_examples}", few_shot_examples)
        prompt = prompt.replace("{output_schema_markdown}", output_schema_md)
        prompt = prompt.replace("{today}", today)
        prompt = prompt.replace("{keyword}", keyword)
        prompt = prompt.replace("{category}", category)
        prompt = prompt.replace("{hot_value}", hot_value)
        prompt = prompt.replace("{video_summaries}", video_summaries_text)
    else:
        # 降级：模板文件不存在时使用内联 prompt
        print("     ⚠️ prompt 模板文件不存在，使用内置 prompt")
        if has_real_videos:
            prompt = f"""{system_prompt}

## 严格规则
- 只能基于下方提供的热搜数据和视频数据进行分析
- 严禁引用任何不在数据中的信息
- 今天的日期是 {today}

## 热点数据
- 话题: {keyword}
- 分类: {category}
- 热度: {hot_value}

## 该话题关联的热门视频
{video_summaries_text}

请提炼出具体的"梗"，分析梗与游戏广告素材的结合方式，给出具体的内容产出方向。用中文回复。"""
        else:
            prompt = f"""{system_prompt}

## 严格规则
- 只能基于下方提供的热搜话题标题进行分析
- 今天的日期是 {today}

## 热点数据
- 话题: {keyword}
- 分类: {category}
- 热度: {hot_value}

请提炼出具体的"梗"，分析梗与游戏广告素材的结合方式，给出具体的内容产出方向。
暂无视频链接，建议在抖音搜索关键词"{keyword}"。用中文回复。"""

    return prompt


def _clean_gemini_output(text):
    """清理 Gemini 输出中可能出现的开场白和结尾废话"""
    import re
    
    # 常见开场白模式（Gemini 角色确认）
    preamble_patterns = [
        r'^好的[，,].*?[。：:]\s*\n*',
        r'^没问题[，,].*?[。：:]\s*\n*',
        r'^收到[，,].*?[。：:]\s*\n*',
        r'^.*?分析师已就位.*?\n+',
        r'^.*?这是基于.*?的分析.*?[。：:]\s*\n*',
        r'^.*?以下是.*?分析报告.*?[。：:]\s*\n*',
    ]
    
    for pattern in preamble_patterns:
        text = re.sub(pattern, '', text, count=1, flags=re.MULTILINE)
    
    # 确保从 **热梗标签** 开始（如果存在的话）
    marker = '**热梗标签**'
    idx = text.find(marker)
    if idx > 0:
        # 检查前面是否只有空白和无意义文字
        before = text[:idx].strip()
        if before and len(before) < 100:
            # 前面的文字很短，可能是残余的开场白
            text = text[idx:]
    
    return text.strip()


def _gemini_analyze(api_key, model_name, hotspot, videos):
    """使用 Gemini 模型分析热点和视频"""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        keyword = hotspot["title"]

        # 构建视频数据摘要
        video_summaries = []
        video_urls = []
        for i, v in enumerate(videos[:8]):
            summary = f"视频{i+1}: 《{v['title']}》"
            if v.get("author"):
                summary += f" 作者: {v['author']}"
            if v.get("likes"):
                summary += f" 点赞: {_format_count(v['likes'])}"
            if v.get("plays"):
                summary += f" 播放: {_format_count(v['plays'])}"
            if v.get("duration_ms"):
                dur_s = v["duration_ms"] // 1000
                summary += f" 时长: {dur_s // 60}分{dur_s % 60}秒"
            if v.get("url") and "douyin.com/video/" in v.get("url", ""):
                summary += f" 链接: {v['url']}"
            video_summaries.append(summary)
            if v.get("url") and "douyin.com/video/" in v.get("url", ""):
                video_urls.append(v["url"])

        # 判断是否有实际视频数据
        has_real_videos = len(video_summaries) > 0 and not any(
            "[请手动查看]" in s for s in video_summaries
        )

        video_summaries_text = "\n".join(video_summaries) if has_real_videos else ""

        # 构建 prompt（从外部模板加载）
        prompt = _build_prompt(hotspot, videos, video_summaries_text, video_urls)

        # 带重试和备选模型的调用
        import time as _time
        models_to_try = [model_name]
        # 备选模型降级链: 3.1 Pro → 2.5 Pro → 2.5 Flash
        if "3.1" in model_name:
            models_to_try.extend(["gemini-2.5-pro", "gemini-2.5-flash"])
        elif "2.5-pro" in model_name:
            models_to_try.append("gemini-2.5-flash")
        elif "2.5-flash" in model_name:
            models_to_try.append("gemini-2.5-pro")

        last_error = None
        for try_model in models_to_try:
            for attempt in range(3):
                try:
                    print(f"     🤖 调用 Gemini {try_model}..." + (f" (重试 {attempt+1}/3)" if attempt > 0 else ""))
                    response = client.models.generate_content(
                        model=try_model,
                        contents=prompt,
                    )
                    if response and response.text:
                        # 后处理：清理 Gemini 可能输出的开场白废话
                        cleaned = _clean_gemini_output(response.text)
                        print(f"     ✅ AI 分析完成 ({len(cleaned)} 字)")
                        return {
                            "method": "gemini",
                            "model": try_model,
                            "content": cleaned,
                            "video_urls_analyzed": video_urls[:3],
                        }
                    else:
                        print(f"     ⚠️ Gemini 返回为空")
                        last_error = "empty response"
                        break  # 空响应不重试，换模型
                except Exception as retry_err:
                    last_error = retry_err
                    err_str = str(retry_err)
                    if "503" in err_str or "UNAVAILABLE" in err_str or "overloaded" in err_str.lower():
                        wait = (attempt + 1) * 5
                        print(f"     ⏳ 服务繁忙，等待 {wait}s 后重试...")
                        _time.sleep(wait)
                        continue
                    elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        wait = (attempt + 1) * 10
                        print(f"     ⏳ 速率限制，等待 {wait}s 后重试...")
                        _time.sleep(wait)
                        continue
                    else:
                        print(f"     ⚠️ Gemini 分析失败: {retry_err}")
                        break  # 非临时错误不重试，换模型
            else:
                # 3 次重试都失败了，换下一个模型
                if len(models_to_try) > 1 and try_model == models_to_try[0]:
                    print(f"     🔄 {try_model} 不可用，尝试备选模型...")
                continue
            # 内层 break 到这里，换下一个模型
            if len(models_to_try) > 1 and try_model == models_to_try[0]:
                print(f"     🔄 {try_model} 失败，尝试备选模型...")
                continue
            break

        print(f"     ⚠️ 所有模型均失败: {last_error}")
        return _rule_based_analyze(hotspot, videos)

    except Exception as e:
        print(f"     ⚠️ Gemini 分析失败: {e}")
        return _rule_based_analyze(hotspot, videos)


def _rule_based_analyze(hotspot, videos):
    """基于规则的分析（不需要 API）"""
    keyword = hotspot["title"]
    category = hotspot.get("category", "其他")

    # 分析视频数据特征
    total_likes = sum(v.get("likes", 0) for v in videos)
    avg_likes = total_likes // len(videos) if videos else 0
    durations = [v.get("duration_ms", 0) for v in videos if v.get("duration_ms")]
    avg_duration = sum(durations) // len(durations) if durations else 0

    # 提取高频词
    all_titles = " ".join(v.get("title", "") for v in videos)
    
    # 时长分析
    short_count = sum(1 for d in durations if d < 60000)
    medium_count = sum(1 for d in durations if 60000 <= d < 300000)
    long_count = sum(1 for d in durations if d >= 300000)

    if short_count >= medium_count and short_count >= long_count:
        duration_insight = "以1分钟内短视频为主，节奏快、信息密度高"
    elif medium_count >= short_count:
        duration_insight = "以1-5分钟中等时长为主，有充足的展示空间"
    else:
        duration_insight = "以5分钟以上长视频为主，内容深度较高"

    # 品类建议
    category_products = {
        "美食生活": "食品饮料、生活用品、家居好物、厨房电器",
        "情感搞笑": "日用消费品、APP推广、游戏、饮品零食",
        "商业财经": "金融产品、教育课程、企业服务、知识付费",
        "科技数码": "3C数码、APP、智能硬件、运营商服务",
        "影视剧集": "快消品、服饰、美妆、跨界联名",
        "娱乐明星": "美妆、服饰、时尚配饰",
        "其他": "根据具体话题内容匹配相关品类",
    }

    content = f"""### 1. 热点解读
「{keyword}」当前处于抖音热搜榜，属于 **{category}** 类别。{hotspot.get('ad_reason', '')}。

### 2. 爆款视频共性分析
- **数据概况**: 采集到 {len(videos)} 条相关视频，平均点赞 {_format_count(avg_likes)}
- **时长特点**: {duration_insight}
- **内容趋势**: 高赞视频主要围绕「{keyword}」的实用性和趣味性展开

### 3. 素材制作建议
1. **视频形式**: 建议制作 {'30-60秒短视频' if avg_duration < 60000 else '1-3分钟中等时长视频'}，参考热门视频的节奏
2. **开头设计**: 前3秒直接切入话题「{keyword}」，引发共鸣或好奇
3. **内容结构**: 痛点引入→产品/方案展示→效果对比→引导互动
4. **话术参考**: 标题建议包含「{keyword}」关键词 + 数字/疑问/惊叹句式
5. **注意事项**: 避免生硬植入，保持内容原生感；遵守平台社区规范

### 4. 投放建议
- **适合品类**: {category_products.get(category, category_products['其他'])}
- **投放时间**: 热点时效性强，建议 24-48 小时内完成素材制作和投放
- **预估效果**: 借势热点可提升 30-50% 自然流量，建议配合 DOU+ 助推"""

    return {
        "method": "rule_based",
        "content": content,
    }


# ============================================================
# Step 4: 生成完整分析报告
# ============================================================

def generate_full_report(topic_results, video_results, douhot_billboard, start_time):
    """生成完整的热点梗分析报告（Markdown 格式）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# 🔥 抖音热点梗分析报告",
        "",
        f"> 时间: {now} | 话题分析: {len(topic_results)} 个 | 视频分析: {len(video_results)} 条",
        "",
    ]

    # ── Part 1: 话题榜分析 ──
    if topic_results:
        lines.extend(["## 📌 话题榜梗分析", ""])
        
        for i, item in enumerate(topic_results):
            detail = item["detail"]
            analysis = item["analysis"]
            cname = detail.get("challenge_name", "")
            rank = detail.get("rank", i + 1)
            hot_score = _format_count(detail.get("hot_score", detail.get("billboard_score", 0)))
            new_play = _format_count(detail.get("new_play_cnt", 0))
            top_videos = detail.get("top_videos", [])
            
            lines.extend([
                f"### {i+1}. #{cname}",
                "",
                f"> 榜单排名: #{rank} | 热度分: {hot_score} | 新增播放: {new_play}",
                "",
            ])
            
            # 关联视频数据
            if top_videos:
                lines.extend([
                    "**话题关联热门视频**：",
                    "",
                    "| # | 视频标题 | 作者 | ❤️ 点赞 | 💬 评论 | 🔄 转发 | 链接 |",
                    "|:-:|----------|------|---------|---------|---------|------|",
                ])
                for j, v in enumerate(top_videos):
                    vtitle = v["title"][:40] + "..." if len(v["title"]) > 40 else v["title"]
                    link = f"[查看]({v['url']})" if v.get("url") else "-"
                    lines.append(
                        f"| {j+1} | {vtitle} | {v.get('author', '-')} | "
                        f"{_format_count(v.get('like_cnt', 0))} | "
                        f"{_format_count(v.get('comment_cnt', 0))} | "
                        f"{_format_count(v.get('share_cnt', 0))} | {link} |"
                    )
                lines.extend(["", ""])
            
            # AI 分析内容
            lines.extend([
                "**梗分析**：",
                "",
                analysis.get("content", "暂无分析"),
                "",
                "---",
                "",
            ])

    # ── Part 2: 视频榜 Top 视频分析 ──
    if video_results:
        lines.extend(["## 🎬 视频榜热门视频脚本分析", ""])
        
        for i, item in enumerate(video_results):
            v = item["video"]
            analysis = item["analysis"]
            vtitle = v.get("title", "")[:50]
            url = v.get("url", f"https://www.douyin.com/video/{v.get('item_id', '')}")
            
            lines.extend([
                f"### 视频 {i+1}: {vtitle}",
                "",
                f"- **链接**: [{url}]({url})",
                f"- **作者**: {v.get('author', '-')}",
                f"- **播放**: {_format_count(v.get('play_count', 0))}",
                f"- **点赞**: {_format_count(v.get('like_count', 0))}",
                "",
                analysis.get("content", "暂无分析"),
                "",
                "---",
                "",
            ])

    # ── Part 3: 梗参考汇总表格 ──
    lines.extend([
        "## 📊 梗参考汇总",
        "",
        "| # | 梗/话题 | 来源 | 热度 | 视频链接 | 核心玩法 | 可参考方向 |",
        "|:-:|---------|------|------|----------|----------|-----------|",
    ])
    
    row_idx = 1
    for item in topic_results:
        detail = item["detail"]
        analysis = item["analysis"]
        cname = detail.get("challenge_name", "")
        hot = _format_count(detail.get("hot_score", detail.get("billboard_score", 0)))
        top_videos = detail.get("top_videos", [])
        vid_links = " ".join([f"[视频{j+1}]({v['url']})" for j, v in enumerate(top_videos[:2])]) if top_videos else "暂无"
        
        # 从 AI 分析中提取核心信息（取前 80 字作为摘要）
        content = analysis.get("content", "")
        # 尝试提取梗分析部分
        core_play = _extract_summary(content, "梗分析", 60)
        directions = _extract_summary(content, "内容产出方向", 60)
        
        lines.append(
            f"| {row_idx} | #{cname} | 话题榜 | {hot} | {vid_links} | {core_play} | {directions} |"
        )
        row_idx += 1
    
    for item in video_results:
        v = item["video"]
        analysis = item["analysis"]
        vtitle = v.get("title", "")[:20]
        url = v.get("url", "")
        plays = _format_count(v.get("play_count", 0))
        content = analysis.get("content", "")
        core_play = _extract_summary(content, "梗分析", 60)
        directions = _extract_summary(content, "内容产出方向", 60)
        
        lines.append(
            f"| {row_idx} | {vtitle} | 视频榜 | ▶️{plays} | [{url[:30]}...]({url}) | {core_play} | {directions} |"
        )
        row_idx += 1
    
    lines.extend([
        "",
        "---",
        f"*douyin-hotspot v2 | {now}*",
    ])

    return "\n".join(lines)


def _extract_summary(content, section_name, max_len=60):
    """从 AI 分析内容中提取指定段落的摘要"""
    if not content:
        return "-"
    
    # 尝试找到 section
    marker = f"**{section_name}**"
    idx = content.find(marker)
    if idx < 0:
        # 尝试 Markdown 标题格式
        for m in [f"### {section_name}", f"## {section_name}", section_name]:
            idx = content.find(m)
            if idx >= 0:
                break
    
    if idx >= 0:
        # 取 marker 后面的文本
        start = content.find("\n", idx)
        if start < 0:
            start = idx + len(section_name) + 5
        text = content[start:start + max_len * 2].strip()
        # 清理 Markdown 格式
        text = text.replace("**", "").replace("*", "").replace("#", "").replace("\n", " ").strip()
        # 去掉可能的冒号前缀
        if text.startswith("：") or text.startswith(":"):
            text = text[1:].strip()
        if len(text) > max_len:
            text = text[:max_len] + "…"
        return text if text else "-"
    
    # 降级：取前 max_len 字
    text = content[:max_len * 2].replace("**", "").replace("*", "").replace("#", "").replace("\n", " ").strip()
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text if text else "-"


# ============================================================
# 工具函数
# ============================================================

def _format_count(val):
    """格式化数字"""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        if val >= 100000000:
            return f"{val / 100000000:.1f}亿"
        if val >= 10000:
            return f"{val / 10000:.1f}万"
        return str(int(val))
    return str(val)


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="抖音热点梗分析流水线 v2 — 话题榜为主→详情页视频→AI梗分析→汇总报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--top-topics", type=int, default=10,
                        help="分析 TOP N 个话题（默认 10）")
    parser.add_argument("--top-video-analyze", type=int, default=2,
                        help="视频榜独立分析 TOP N 条（默认 2）")
    parser.add_argument("--videos-per-topic", type=int, default=2,
                        help="每个话题取 TOP N 关联视频（默认 2）")
    parser.add_argument("--gemini-key", type=str, default=None,
                        help="Gemini API Key")
    parser.add_argument("--gemini-model", type=str, default="gemini-3.1-pro-preview",
                        help="Gemini 模型名称（默认 gemini-3.1-pro-preview）")
    parser.add_argument("--skip-ai", action="store_true",
                        help="跳过 AI 分析步骤")
    parser.add_argument("--no-cache", action="store_true",
                        help="热搜数据不使用缓存")
    parser.add_argument("--no-dedup", action="store_true",
                        help="不去重（不跳过之前分析过的话题）")
    parser.add_argument("--output", type=str, default=None,
                        help="输出报告文件路径")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown",
                        help="输出格式（默认 markdown）")
    args = parser.parse_args()

    api_key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
    start_time = time.time()

    print("🚀 抖音热点梗分析流水线 v2")
    print(f"   话题: TOP {args.top_topics} | 视频榜: TOP {args.top_video_analyze}")
    print(f"   每话题视频: {args.videos_per_topic} 条")
    if api_key:
        print(f"   AI: Gemini {args.gemini_model}")
    else:
        print(f"   AI: 规则分析模式（无 API Key）")
    print()

    # Step 1: 采集话题榜+视频榜，过滤话题
    selected_topics, douhot_billboard, search_items = step1_get_hotspots(
        top_n=args.top_topics,
        no_cache=args.no_cache,
    )

    if not selected_topics:
        print("\n❌ 过滤后无可分析话题，流水线终止。")
        sys.exit(1)

    # Step 2: 话题详情页采集
    topic_data = step2_collect_topic_videos(
        selected_topics,
        top_videos_per_topic=args.videos_per_topic,
    )

    # 二次过滤：双通道选题策略
    # 
    # 通道 1 — 时效性过滤：保留满足以下任一条件的话题
    #   A) 话题创建时间在 2025-01-01 之后（新话题）
    #   B) 话题关联 top 视频中有近 30 天内发布的（老话题近期重新爆发）
    #
    # 通道 2 — 最新话题直选：始终保留 create_time 最新的 N 个话题
    #   这些是当下最新出现的梗，最可能成为爆款素材的灵感来源
    #
    # 两个通道取并集，确保既有活跃老梗、也有最新热梗
    
    min_create_ts = 1735689600  # 2025-01-01 00:00:00 UTC+8
    min_video_ts = int(time.time()) - 30 * 86400  # 最近30天
    newest_keep_count = 3  # 始终保留创建时间最新的 N 个话题
    
    # --- 通道 2: 先选出创建时间最新的 N 个话题 ---
    # 按 create_time 降序排列，取 top N
    topics_with_time = [item for item in topic_data if item["detail"].get("create_time", 0) > 0]
    topics_sorted_by_newest = sorted(topics_with_time, key=lambda x: x["detail"]["create_time"], reverse=True)
    newest_topics = set()
    for item in topics_sorted_by_newest[:newest_keep_count]:
        cid = item["detail"].get("challenge_id", "")
        cname = item["detail"].get("challenge_name", "")
        newest_topics.add(str(cid))
        print(f"  🔥 最新话题直选: #{cname} (创建于{datetime.fromtimestamp(item['detail']['create_time']).strftime('%Y-%m-%d')})")
    
    # --- 通道 1: 时效性过滤 ---
    passed = []
    filtered_out_reasons = {}
    
    for item in topic_data:
        detail = item["detail"]
        cname = detail.get("challenge_name", "")
        cid = str(detail.get("challenge_id", ""))
        create_time = detail.get("create_time", 0)
        top_videos = detail.get("top_videos", [])
        
        # 通道 2 命中：直接保留（不需要再看时效性）
        if cid in newest_topics:
            passed.append(item)
            continue
        
        # 条件 A: 话题创建于 2025 年之后
        is_new_topic = create_time > 0 and create_time >= min_create_ts
        
        # 条件 B: 关联视频中有近 30 天发布的
        has_recent_video = False
        if top_videos:
            has_recent_video = any(v.get("create_time", 0) > min_video_ts for v in top_videos)
        
        # 没有视频也没有 create_time 的话题 → 保守保留（数据可能采集不到）
        no_data = (create_time == 0 and not top_videos)
        
        if is_new_topic or has_recent_video or no_data:
            passed.append(item)
        else:
            # 记录过滤原因
            reasons = []
            if create_time > 0:
                reasons.append(f"创建于{datetime.fromtimestamp(create_time).strftime('%Y-%m')}")
            if top_videos:
                latest_ts = max((v.get("create_time", 0) for v in top_videos), default=0)
                if latest_ts > 0:
                    reasons.append(f"最新视频{datetime.fromtimestamp(latest_ts).strftime('%Y-%m-%d')}")
                else:
                    reasons.append("视频无时间戳")
            filtered_out_reasons[cname] = " | ".join(reasons) if reasons else "时效性不足"
    
    if filtered_out_reasons:
        print(f"\n  ⏩ 时效性过滤淘汰 {len(filtered_out_reasons)} 个话题:")
        for name, reason in filtered_out_reasons.items():
            print(f"     ❌ #{name}: {reason}")
    
    if len(passed) < len(topic_data):
        print(f"  📌 最终保留: {len(passed)}/{len(topic_data)} 个话题 (含 {len(newest_topics)} 个最新直选)")
    topic_data = passed

    # 准备视频榜 top2
    video_billboard_top = []
    if douhot_billboard:
        video_billboard_top = douhot_billboard.get("top_videos", [])[:args.top_video_analyze]

    # Step 3: AI 分析
    if args.skip_ai:
        print("\n⏭️ 跳过 AI 分析步骤")
        topic_results = [
            {**item, "analysis": {"method": "skipped", "content": "（跳过 AI 分析）"}}
            for item in topic_data
        ]
        video_results = []
    else:
        topic_results, video_results = step3_ai_analysis(
            topic_data,
            video_billboard_top=video_billboard_top,
            api_key=api_key if api_key else None,
            model_name=args.gemini_model,
        )

    # 记录已分析的话题 ID（供下次去重）
    if not args.no_dedup:
        analyzed_ids = load_analyzed_topics()
        for item in topic_results:
            cid = item.get("detail", {}).get("challenge_id", "")
            if cid:
                analyzed_ids.add(str(cid))
        save_analyzed_topics(analyzed_ids)

    # Step 4: 生成报告
    print("\n" + "=" * 70)
    print("📝 Step 4: 生成分析报告")
    print("=" * 70)

    if args.format == "json":
        report = json.dumps({
            "generated_at": datetime.now().isoformat(),
            "elapsed_seconds": time.time() - start_time,
            "topic_results": [
                {
                    "topic": r.get("topic", {}),
                    "detail": r.get("detail", {}),
                    "analysis": r.get("analysis", {}),
                }
                for r in topic_results
            ],
            "video_results": [
                {
                    "video": r.get("video", {}),
                    "analysis": r.get("analysis", {}),
                }
                for r in video_results
            ],
        }, ensure_ascii=False, indent=2, default=str)
    else:
        report = generate_full_report(topic_results, video_results, douhot_billboard, start_time)

    # 输出
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  ✅ 报告已保存: {output_path}")
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        ext = "json" if args.format == "json" else "md"
        default_path = CACHE_DIR / f"hotspot_report_{today}.{ext}"
        default_path.parent.mkdir(parents=True, exist_ok=True)
        with open(default_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  ✅ 报告已保存: {default_path}")

    elapsed = time.time() - start_time
    print(f"\n🎉 流水线完成！总耗时: {int(elapsed)} 秒")
    print(f"   话题分析: {len(topic_results)} 个 | 视频分析: {len(video_results)} 条")


if __name__ == "__main__":
    main()
