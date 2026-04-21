#!/usr/bin/env python3
"""
每日热点分析报告

读取 hourly_collector 全天采集的数据，去重合并后，过滤、筛选、AI分析，生成每日报告。
与 hotspot_pipeline.py 的区别：
- hotspot_pipeline 是即时模式（抓当前热搜→分析）
- daily_report 是汇总模式（读取全天采集数据→去重→过滤→分析）

用法：
  # 基于今日全天采集数据生成报告
  python daily_report.py --gemini-key YOUR_KEY

  # 基于昨日数据生成报告
  python daily_report.py --date 2026-04-09 --gemini-key YOUR_KEY

  # 指定输出路径
  python daily_report.py --gemini-key KEY --output /tmp/daily_report.md
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CACHE_DIR = SKILL_DIR / "cache"

sys.path.insert(0, str(SCRIPT_DIR))
from fetch_hotboard import load_config, fetch_hotboard, format_hot_value, load_filter_rules, filter_items
from analyze_trends import categorize_topic, AD_FRIENDLY_CATEGORIES, get_ad_reason
from hourly_collector import read_daily_collection, collect_once


def get_hotspots_from_daily(date_str, top_n=5, fallback_to_live=True):
    """
    从全天采集数据中获取去重后的热点列表
    如果当天没有采集数据，降级为实时获取
    """
    merged, records = read_daily_collection(date_str)
    
    if not merged and fallback_to_live:
        print("  ⚠️ 未找到全天采集数据，降级为实时获取...")
        # 先跑一次采集
        collect_once(no_cache=True)
        # 然后用 pipeline 的 step1 逻辑
        from hotspot_pipeline import step1_get_hotspots
        hotspots, source = step1_get_hotspots(top_n=top_n, no_cache=True)
        return hotspots, source, 0
    
    if not merged:
        return [], "无数据", 0
    
    # 过滤
    filter_rules = load_filter_rules()
    if filter_rules:
        merged, removed = filter_items(merged, filter_rules)
        print(f"  🔍 过滤后剩余 {len(merged)} 个话题 (移除 {len(removed)} 个不适合营销的)")
    
    # 筛选适合蹭热点的
    ad_friendly = []
    for item in merged:
        title = item.get("title", "")
        categories = categorize_topic(title)
        for cat in categories:
            if cat in AD_FRIENDLY_CATEGORIES:
                ad_friendly.append({
                    **item,
                    "category": cat,
                    "ad_reason": get_ad_reason(cat, title),
                })
                break
    
    # 如果广告友好的不够，从全部列表中补充
    if len(ad_friendly) < top_n:
        existing_titles = {h["title"] for h in ad_friendly}
        for item in merged:
            if item["title"] not in existing_titles:
                ad_friendly.append({
                    **item,
                    "category": categorize_topic(item["title"])[0],
                    "ad_reason": "全天热度高，可结合品牌特点创作",
                })
                if len(ad_friendly) >= top_n:
                    break
    
    selected = ad_friendly[:top_n]
    
    print(f"\n  🎯 从全天 {len(merged)} 个话题中选定 {len(selected)} 个进行深度分析:")
    for i, h in enumerate(selected):
        count = h.get("appear_count", 1)
        dur = h.get("duration_hours", 0)
        print(f"     {i+1}. [{h.get('category', '')}] {h['title']} (热度: {format_hot_value(h.get('hot_value', ''))}, 出现{count}次, 持续{dur}h)")
    
    return selected, f"全天汇总({len(records)}次采集)", len(records)


def generate_daily_report(analysis_results, date_str, total_topics, collection_count, start_time):
    """生成每日汇总分析报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    lines = [
        f"# 📊 每日抖音热点分析报告",
        "",
        f"> 分析日期: {date_str} | 生成时间: {now}",
        f"> 数据来源: 全天 {collection_count} 次采集汇总 | 独立话题: {total_topics} 个 | 深度分析: {len(analysis_results)} 个",
        "",
        "---",
        "",
    ]
    
    for i, item in enumerate(analysis_results):
        hotspot = item["hotspot"]
        analysis = item["analysis"]
        videos = item.get("videos", [])
        
        title = hotspot["title"]
        category = hotspot.get("category", "")
        hot_value = format_hot_value(hotspot.get("hot_value", ""))
        appear = hotspot.get("appear_count", 1)
        dur = hotspot.get("duration_hours", 0)
        method = analysis.get("method", "rule_based")
        method_label = "AI分析" if method == "gemini" else "规则分析"
        has_videos = videos and not videos[0].get("title", "").startswith("[请手动查看]")
        
        # 持续性标签
        persistence = ""
        if appear >= 8:
            persistence = "🔥🔥🔥 全天霸榜"
        elif appear >= 5:
            persistence = "🔥🔥 高持续性"
        elif appear >= 3:
            persistence = "🔥 中等持续"
        else:
            persistence = "⚡ 短时热点"
        
        lines.extend([
            f"## {i+1}. {title}",
            "",
            f"> {category} | 热度 {hot_value} | {method_label} | {persistence} (出现{appear}次, 持续{dur}h)",
            "",
        ])
        
        # 视频数据表格
        if has_videos:
            lines.extend([
                "### 热门视频",
                "",
                "| # | 视频标题 | 作者 | 点赞 | 时长 | 链接 |",
                "|:-:|----------|------|------:|-----:|------|",
            ])
            for j, v in enumerate(videos[:8]):
                vtitle = v["title"][:35] + "..." if len(v["title"]) > 35 else v["title"]
                author = v.get("author", "-")
                likes = _format_count(v.get("likes", 0))
                dur_str = ""
                if v.get("duration_ms"):
                    dur_s = v["duration_ms"] // 1000
                    dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
                url = v.get("url", "")
                link = f"[查看]({url})" if url and "douyin.com" in url else "-"
                lines.append(f"| {j+1} | {vtitle} | {author} | {likes} | {dur_str} | {link} |")
            lines.extend(["", ""])
        
        # AI 分析内容
        lines.extend([
            "### 分析",
            "",
            analysis.get("content", "暂无分析"),
            "",
            "---",
            "",
        ])
    
    # 报告尾部
    elapsed = time.time() - start_time
    lines.extend([
        "---",
        f"*douyin-hotspot 每日报告 | {date_str} | 生成耗时: {elapsed:.0f}s*",
    ])
    
    return "\n".join(lines)


def _format_count(val):
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        if val >= 100000000:
            return f"{val / 100000000:.1f}亿"
        if val >= 10000:
            return f"{val / 10000:.1f}万"
        return str(int(val))
    return str(val)


def main():
    parser = argparse.ArgumentParser(
        description="每日热点汇总分析报告 — 基于全天采集数据去重分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--date", type=str, default=None,
                        help="分析日期（YYYY-MM-DD，默认今天）")
    parser.add_argument("--top-hotspots", type=int, default=5,
                        help="深度分析 TOP N 个热点（默认 5）")
    parser.add_argument("--gemini-key", type=str, default=None,
                        help="Gemini API Key")
    parser.add_argument("--gemini-model", type=str, default="gemini-3.1-pro-preview",
                        help="Gemini 模型名称（默认 gemini-3.1-pro-preview）")
    parser.add_argument("--skip-ai", action="store_true",
                        help="跳过 AI 分析")
    parser.add_argument("--skip-videos", action="store_true",
                        help="跳过视频采集")
    parser.add_argument("--output", type=str, default=None,
                        help="输出报告文件路径")
    parser.add_argument("--no-fallback", action="store_true",
                        help="没有采集数据时不降级为实时获取")
    args = parser.parse_args()
    
    api_key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    
    start_time = time.time()
    
    print(f"📊 每日抖音热点汇总分析")
    print(f"   分析日期: {date_str}")
    print(f"   AI: {'Gemini ' + args.gemini_model if api_key else '规则分析'}")
    print()
    
    # Step 1: 从全天采集数据中获取热点
    print("=" * 70)
    print("📡 Step 1: 读取全天采集数据并去重")
    print("=" * 70)
    
    hotspots, source, collection_count = get_hotspots_from_daily(
        date_str,
        top_n=args.top_hotspots,
        fallback_to_live=not args.no_fallback,
    )
    
    if not hotspots:
        print(f"\n❌ 未获取到 {date_str} 的热搜数据")
        sys.exit(1)
    
    total_topics = len(hotspots)  # 用于报告
    
    # Step 2: 视频采集（复用 pipeline 的逻辑）
    if args.skip_videos:
        print("\n⏭️ 跳过视频采集步骤")
        collected_data = [{"hotspot": h, "videos": []} for h in hotspots]
    else:
        from hotspot_pipeline import step2_collect_videos
        collected_data = step2_collect_videos(hotspots)
    
    # Step 3: AI 分析（复用 pipeline 的逻辑）
    if args.skip_ai:
        print("\n⏭️ 跳过 AI 分析步骤")
        analysis_results = [
            {**item, "analysis": {"method": "skipped", "content": "（跳过 AI 分析）"}}
            for item in collected_data
        ]
    else:
        from hotspot_pipeline import step3_ai_analysis
        analysis_results = step3_ai_analysis(
            collected_data,
            api_key=api_key if api_key else None,
            model_name=args.gemini_model,
        )
    
    # Step 4: 生成报告
    print("\n" + "=" * 70)
    print("📝 Step 4: 生成每日汇总报告")
    print("=" * 70)
    
    report = generate_daily_report(
        analysis_results, date_str, total_topics, collection_count, start_time,
    )
    
    # 输出
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  ✅ 报告已保存: {output_path}")
    else:
        today = date_str
        default_path = CACHE_DIR / "daily" / f"daily_report_{today}.md"
        default_path.parent.mkdir(parents=True, exist_ok=True)
        with open(default_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  ✅ 报告已保存: {default_path}")
    
    elapsed = time.time() - start_time
    print(f"\n🎉 每日报告完成！总耗时: {elapsed:.0f} 秒")


if __name__ == "__main__":
    main()
