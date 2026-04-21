#!/usr/bin/env python3
"""
每小时热搜数据采集器

每小时运行一次，获取当前热搜榜数据，追加到当天的汇总文件中。
配合每日定时分析任务使用：先用此脚本全天采集，再由 daily_report.py 汇总去重分析。

汇总文件格式（JSON Lines）：
  cache/hourly/YYYY-MM-DD.jsonl
  每行一条 JSON：{"timestamp": "...", "items": [...]}

用法：
  python hourly_collector.py                # 采集一次并追加到今日汇总
  python hourly_collector.py --no-cache     # 跳过缓存强制从 API 拉取
  python hourly_collector.py --date 2026-04-09  # 指定写入日期（调试用）
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
HOURLY_DIR = SKILL_DIR / "cache" / "hourly"

sys.path.insert(0, str(SCRIPT_DIR))
from fetch_hotboard import load_config, fetch_hotboard, format_hot_value


def collect_once(no_cache=False, target_date=None):
    """采集一次热搜数据并追加到当日汇总文件"""
    config = load_config()
    
    # 强制不用缓存获取最新数据
    items, source, error = fetch_hotboard(config, use_cache=not no_cache)
    
    if error:
        print(f"❌ 采集失败: {error}")
        return False
    
    if not items:
        print("⚠️ 未获取到数据")
        return False
    
    now = datetime.now()
    date_str = target_date or now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()
    
    # 写入 JSONL 文件（每行一次采集记录）
    HOURLY_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = HOURLY_DIR / f"{date_str}.jsonl"
    
    record = {
        "timestamp": timestamp,
        "source": source,
        "count": len(items),
        "items": items,
    }
    
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"✅ [{now.strftime('%H:%M')}] 采集 {len(items)} 条热搜 (来源: {source})")
    print(f"   → 已追加到 {jsonl_path}")
    
    # 打印 TOP 5
    for i, item in enumerate(items[:5]):
        title = item.get("title", "")
        hot = format_hot_value(item.get("hot_value", ""))
        print(f"   {i+1}. {title} ({hot})")
    
    return True


def read_daily_collection(date_str=None):
    """
    读取指定日期的全部采集数据，返回去重后的热点列表
    
    去重逻辑：同一标题多次出现时，保留最高热度值，并记录出现次数和时间跨度
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    jsonl_path = HOURLY_DIR / f"{date_str}.jsonl"
    
    if not jsonl_path.exists():
        print(f"⚠️ 未找到 {date_str} 的采集数据: {jsonl_path}")
        return [], []
    
    # 读取所有采集记录
    all_records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    all_records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    
    if not all_records:
        print(f"⚠️ {date_str} 的采集数据为空")
        return [], []
    
    print(f"📊 读取 {date_str} 共 {len(all_records)} 次采集记录")
    
    # 汇总去重：按标题合并，保留最高热度，记录元数据
    topic_map = {}  # title -> merged_info
    
    for record in all_records:
        ts = record.get("timestamp", "")
        for item in record.get("items", []):
            title = item.get("title", "").strip()
            if not title:
                continue
            
            hot_value = _parse_hot(item.get("hot_value", 0))
            
            if title in topic_map:
                existing = topic_map[title]
                existing["appear_count"] += 1
                existing["timestamps"].append(ts)
                if hot_value > existing["max_hot_raw"]:
                    existing["max_hot_raw"] = hot_value
                    existing["hot_value"] = item.get("hot_value", 0)
                    existing["url"] = item.get("url", existing.get("url", ""))
                # 记录最高排名
                rank = item.get("rank", 999)
                if rank < existing.get("best_rank", 999):
                    existing["best_rank"] = rank
            else:
                topic_map[title] = {
                    "title": title,
                    "hot_value": item.get("hot_value", 0),
                    "max_hot_raw": hot_value,
                    "url": item.get("url", ""),
                    "source": item.get("source", ""),
                    "appear_count": 1,
                    "best_rank": item.get("rank", 999),
                    "timestamps": [ts],
                }
    
    # 按最高热度排序
    merged = sorted(topic_map.values(), key=lambda x: x["max_hot_raw"], reverse=True)
    
    # 添加排名
    for i, item in enumerate(merged):
        item["rank"] = i + 1
        # 计算持续时间
        if len(item["timestamps"]) > 1:
            first = datetime.fromisoformat(item["timestamps"][0])
            last = datetime.fromisoformat(item["timestamps"][-1])
            hours = (last - first).total_seconds() / 3600
            item["duration_hours"] = round(hours, 1)
        else:
            item["duration_hours"] = 0
    
    print(f"   去重后共 {len(merged)} 个独立话题")
    print(f"   采集时间范围: {all_records[0].get('timestamp', '?')[:16]} ~ {all_records[-1].get('timestamp', '?')[:16]}")
    
    return merged, all_records


def _parse_hot(val):
    """解析热度值为数值"""
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        val = val.replace(",", "").strip()
        if "万" in val:
            try: return float(val.replace("万", "")) * 10000
            except: return 0
        if "亿" in val:
            try: return float(val.replace("亿", "")) * 100000000
            except: return 0
        try: return float(val)
        except: return 0
    return 0


def main():
    parser = argparse.ArgumentParser(description="每小时热搜数据采集器")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存强制从 API 拉取")
    parser.add_argument("--date", type=str, default=None, help="指定写入日期（YYYY-MM-DD，调试用）")
    parser.add_argument("--summary", action="store_true", help="输出今日采集汇总而非采集新数据")
    parser.add_argument("--summary-date", type=str, default=None, help="输出指定日期的采集汇总")
    args = parser.parse_args()
    
    if args.summary or args.summary_date:
        date_str = args.summary_date or datetime.now().strftime("%Y-%m-%d")
        merged, records = read_daily_collection(date_str)
        if merged:
            print(f"\n🔥 {date_str} 热搜 TOP 20（去重后按最高热度排序）:")
            for item in merged[:20]:
                title = item["title"]
                hot = format_hot_value(item["hot_value"])
                count = item["appear_count"]
                dur = item["duration_hours"]
                print(f"  {item['rank']:3d}. {title:30s}  热度 {hot:>8s}  出现 {count} 次  持续 {dur}h")
    else:
        collect_once(no_cache=args.no_cache, target_date=args.date)


if __name__ == "__main__":
    main()
