#!/usr/bin/env python3
"""
抖音热点趋势 AI 分析脚本

基于热搜榜数据，输出结构化的热点分析报告，包括：
- 热点分类与归纳
- 可蹭热点推荐（适合广告素材的热点）
- 内容创作方向建议

用法：
  python analyze_trends.py                    # 分析当前热搜并输出报告
  python analyze_trends.py --top 20           # 只分析 TOP 20
  python analyze_trends.py --output report    # 输出为文件
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CACHE_DIR = SKILL_DIR / "cache" / "daily"

# 导入热搜获取模块
sys.path.insert(0, str(SCRIPT_DIR))
from fetch_hotboard import load_config, fetch_hotboard, format_hot_value, load_filter_rules, filter_items


# ============================================================
# 热点分类规则
# ============================================================
CATEGORY_KEYWORDS = {
    "娱乐明星": ["明星", "演员", "歌手", "导演", "综艺", "选秀", "偶像", "出道", "恋情", "分手", "结婚", "离婚", "绯闻", "粉丝"],
    "影视剧集": ["电影", "电视剧", "剧集", "上映", "预告", "票房", "口碑", "豆瓣", "主演", "开播", "大结局", "续集"],
    "社会民生": ["事故", "救援", "天气", "地震", "政策", "教育", "医疗", "房价", "就业", "养老", "民生", "物价"],
    "体育赛事": ["比赛", "冠军", "球队", "联赛", "奥运", "世界杯", "NBA", "足球", "篮球", "赛季", "淘汰", "决赛"],
    "科技数码": ["手机", "芯片", "AI", "人工智能", "苹果", "华为", "小米", "特斯拉", "机器人", "发布会", "新品"],
    "美食生活": ["美食", "菜谱", "减肥", "健身", "穿搭", "旅游", "景点", "打卡", "网红店", "探店"],
    "情感搞笑": ["搞笑", "段子", "沙雕", "挑战", "模仿", "整蛊", "日常", "vlog", "恋爱", "表白"],
    "商业财经": ["股市", "基金", "理财", "品牌", "营销", "电商", "直播带货", "双11", "618", "促销"],
}

# 适合广告素材蹭热点的类别
AD_FRIENDLY_CATEGORIES = ["美食生活", "情感搞笑", "商业财经", "科技数码", "影视剧集"]


def categorize_topic(title):
    """对热搜话题进行分类"""
    title_lower = title.lower()
    matched_categories = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in title_lower:
                matched_categories.append(category)
                break
    return matched_categories if matched_categories else ["其他"]


def analyze_hotboard(items, top_n=50):
    """分析热搜榜数据"""
    items = items[:top_n]

    # 1. 分类统计
    category_count = {}
    category_items = {}
    for item in items:
        title = item.get("title", "")
        categories = categorize_topic(title)
        for cat in categories:
            category_count[cat] = category_count.get(cat, 0) + 1
            if cat not in category_items:
                category_items[cat] = []
            category_items[cat].append(item)

    # 2. 排序
    sorted_categories = sorted(category_count.items(), key=lambda x: x[1], reverse=True)

    # 3. 筛选适合蹭热点的话题
    ad_friendly_items = []
    for item in items:
        title = item.get("title", "")
        categories = categorize_topic(title)
        for cat in categories:
            if cat in AD_FRIENDLY_CATEGORIES:
                ad_friendly_items.append({
                    **item,
                    "category": cat,
                    "reason": get_ad_reason(cat, title)
                })
                break

    # 4. 提取高热度话题（TOP 10）
    top_hot = sorted(items, key=lambda x: _parse_hot(x.get("hot_value", 0)), reverse=True)[:10]

    return {
        "total_analyzed": len(items),
        "category_distribution": sorted_categories,
        "category_items": category_items,
        "ad_friendly_topics": ad_friendly_items[:15],
        "top_hot_topics": top_hot,
        "analysis_time": datetime.now().isoformat(),
    }


def _parse_hot(val):
    """解析热度值为数字"""
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        val = val.replace(",", "").strip()
        if "万" in val:
            return float(val.replace("万", "")) * 10000
        if "亿" in val:
            return float(val.replace("亿", "")) * 100000000
        try:
            return float(val)
        except ValueError:
            return 0
    return 0


def get_ad_reason(category, title):
    """为可蹭热点话题生成推荐理由"""
    reasons = {
        "美食生活": "生活方式类热点，适合消费品、食品饮料、生活服务类广告自然切入",
        "情感搞笑": "情感共鸣类热点，适合以幽默/情感方式植入品牌，容易引发互动",
        "商业财经": "商业话题热度高，适合金融、教育、企业服务类广告借势",
        "科技数码": "科技话题受关注，适合数码、3C、App 类产品借势推广",
        "影视剧集": "影视热点流量大，适合跨界联名、场景植入类创意",
    }
    return reasons.get(category, "热度较高，可结合品牌特点创作关联内容")


# ============================================================
# 报告生成
# ============================================================
def generate_report(analysis, source):
    """生成 Markdown 格式的热点分析报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 📊 抖音热点趋势分析报告",
        f"",
        f"> 分析时间：{now}　|　数据来源：{source}　|　分析样本：TOP {analysis['total_analyzed']}",
    ]

    removed_count = analysis.get("removed_count", 0)
    if removed_count > 0:
        lines.append(f"> ⚡ 已自动过滤 {removed_count} 条不适合营销的热点（时政/军事/明星舆论/灾难等）")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 一、热点分类分布",
        f"",
    ])

    # 分类分布
    total = analysis["total_analyzed"]
    for cat, count in analysis["category_distribution"]:
        pct = count / total * 100
        bar = "█" * int(pct / 3) + "░" * (33 - int(pct / 3))
        lines.append(f"- **{cat}**：{count} 条（{pct:.0f}%）`{bar}`")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 二、🔥 热度 TOP 10",
        f"",
        f"| 排名 | 话题 | 热度 |",
        f"|:----:|------|-----:|",
    ])

    for i, item in enumerate(analysis["top_hot_topics"]):
        rank = i + 1
        title = item.get("title", "")
        hot = format_hot_value(item.get("hot_value", ""))
        url = item.get("url", "")
        title_display = f"[{title}]({url})" if url else title
        lines.append(f"| {rank} | {title_display} | {hot} |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 三、🎯 可蹭热点推荐（适合广告素材）",
        f"",
        f"以下热点话题与广告创作关联度较高，推荐结合品牌进行内容制作：",
        f"",
    ])

    for i, item in enumerate(analysis["ad_friendly_topics"]):
        title = item.get("title", "")
        hot = format_hot_value(item.get("hot_value", ""))
        cat = item.get("category", "")
        reason = item.get("reason", "")
        url = item.get("url", "")

        lines.append(f"### {i + 1}. {title}")
        lines.append(f"- **分类**：{cat}　|　**热度**：{hot}")
        if url:
            lines.append(f"- **链接**：[在抖音查看]({url})")
        lines.append(f"- **推荐理由**：{reason}")
        lines.append(f"")

    lines.extend([
        f"---",
        f"",
        f"## 四、💡 创作方向建议",
        f"",
    ])

    # 根据分类分布给出创作建议
    top_categories = [cat for cat, _ in analysis["category_distribution"][:3]]
    lines.append(f"今日热点集中在 **{'、'.join(top_categories)}** 方向，建议：")
    lines.append(f"")

    suggestion_map = {
        "娱乐明星": "- 🎤 可借助明星话题做产品场景联想，但注意避免肖像权风险",
        "影视剧集": "- 🎬 借势影视热度，制作同款/致敬/二创内容，受众精准",
        "社会民生": "- 📢 民生话题要谨慎，建议只选正能量方向，避免争议",
        "体育赛事": "- ⚽ 体育热点适合运动品牌、健康品类借势，制作赛事关联内容",
        "科技数码": "- 📱 可做产品对比、使用教程、黑科技展示等内容",
        "美食生活": "- 🍕 生活方式内容自然植入效果好，适合大部分消费品牌",
        "情感搞笑": "- 😂 搞笑/情感内容完播率高，适合做品牌软性植入",
        "商业财经": "- 💰 适合知识营销、行业解读类内容，塑造品牌专业形象",
        "其他": "- 📌 关注长尾热点，寻找差异化创作角度",
    }

    for cat in top_categories:
        lines.append(suggestion_map.get(cat, f"- 关注 {cat} 类热点，结合品牌特点创作"))

    lines.extend([
        f"",
        f"---",
        f"*报告由 douyin-hotspot Skill 自动生成*",
    ])

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="抖音热点趋势分析")
    parser.add_argument("--top", type=int, default=50, help="分析 TOP N 条")
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="markdown", help="输出格式")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径（不指定则输出到终端）")
    parser.add_argument("--no-filter", action="store_true", help="不过滤（默认会过滤不适合营销的热点）")
    args = parser.parse_args()

    # 获取热搜数据
    config = load_config()
    items, source, error = fetch_hotboard(config, use_cache=True)

    if error:
        print(f"[ERROR] 获取热搜数据失败: {error}", file=sys.stderr)
        sys.exit(1)

    # 默认启用过滤（分析报告面向营销场景）
    removed_count = 0
    if not args.no_filter:
        filter_rules = load_filter_rules()
        if filter_rules:
            items, removed = filter_items(items, filter_rules)
            removed_count = len(removed)
            # 重新编排排名
            for i, item in enumerate(items):
                item["rank"] = i + 1

    # 分析
    analysis = analyze_hotboard(items, args.top)
    analysis["removed_count"] = removed_count

    # 输出
    if args.format == "json":
        output = json.dumps(analysis, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        output = generate_report(analysis, source)
    else:
        output = generate_report(analysis, source)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"✅ 报告已保存到: {output_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()
