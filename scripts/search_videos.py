#!/usr/bin/env python3
"""
抖音热点视频查询脚本

根据关键词搜索某个热点话题下的具体视频内容，包括：
- 视频标题/描述
- 作者信息
- 点赞/评论/分享/播放量
- 视频链接

用法：
  python search_videos.py "穿搭"                          # 搜索"穿搭"相关视频
  python search_videos.py "穿搭" --sort likes             # 按点赞数排序
  python search_videos.py "穿搭" --sort latest            # 按最新发布排序
  python search_videos.py "穿搭" --duration short         # 只看1分钟内的短视频
  python search_videos.py "穿搭" --time week              # 只看最近一周发布的
  python search_videos.py "穿搭" --top 5 --format json    # JSON输出TOP 5
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SKILL_DIR / "config" / "api_config.json"


def load_config():
    """加载 API 配置"""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 视频搜索 API 方案
# ============================================================
# 方案 1：直接构造抖音搜索 URL（无需额外 API，用户在浏览器打开）
# 方案 2：通过第三方 API 获取结构化的视频列表数据

def get_douyin_search_url(keyword, sort="default"):
    """构造抖音搜索 URL（在浏览器中直接查看）"""
    encoded = quote(keyword)
    # 抖音搜索视频页面
    return f"https://www.douyin.com/search/{encoded}?type=video"


def search_via_api(keyword, sort_type=0, publish_time=0, filter_duration=0, page=1):
    """
    通过起零数据平台搜索抖音视频
    如果不可用则尝试抖音网页端解析
    """
    if not HAS_REQUESTS:
        return None, "requests 库未安装"

    config = load_config()
    token = config.get("primary", {}).get("token", "")

    # 尝试起零数据的搜索接口
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "DouyinHotspot-Skill/1.0"
    }

    # 起零数据可能有搜索接口，先尝试
    search_url = f"https://api.istero.com/resource/v1/douyin/search?keyword={quote(keyword)}&page={page}"
    try:
        resp = requests.get(search_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                return parse_istero_search(data), None
    except Exception:
        pass

    # 尝试其他免费接口
    return search_via_fallback(keyword, sort_type, publish_time, filter_duration, page)


def search_via_fallback(keyword, sort_type=0, publish_time=0, filter_duration=0, page=1):
    """备用搜索方案"""
    # 方案 A: 使用抖音的 web 搜索建议接口（公开）
    try:
        sug_url = f"https://www.douyin.com/aweme/v1/web/search/item/?keyword={quote(keyword)}&search_channel=aweme_video_web&sort_type={sort_type}&publish_time={publish_time}&filter_duration={filter_duration}&offset={(page-1)*10}&count=10"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json",
        }
        resp = requests.get(sug_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data"):
                return parse_douyin_web_search(data), None
    except Exception:
        pass

    # 方案 B: 返回构造的搜索 URL 供用户手动查看
    return None, "API 搜索不可用，已生成抖音搜索链接供手动查看"


def parse_istero_search(data):
    """解析起零数据的搜索结果"""
    items = []
    for item in data.get("data", []):
        items.append({
            "title": item.get("title", item.get("desc", "")),
            "author": item.get("author", item.get("nickname", "")),
            "likes": item.get("likes", item.get("digg_count", 0)),
            "comments": item.get("comments", item.get("comment_count", 0)),
            "shares": item.get("shares", item.get("share_count", 0)),
            "plays": item.get("plays", item.get("play_count", 0)),
            "url": item.get("url", item.get("share_url", "")),
            "duration": item.get("duration", 0),
            "create_time": item.get("create_time", ""),
        })
    return items


def parse_douyin_web_search(data):
    """解析抖音网页搜索结果"""
    items = []
    for item_wrap in data.get("data", []):
        item = item_wrap.get("aweme_info", item_wrap)
        author = item.get("author", {})
        stats = item.get("statistics", {})
        video = item.get("video", {})

        # 提取视频描述
        desc = item.get("desc", "")

        # 提取作者
        author_name = author.get("nickname", "")

        # 提取统计
        likes = stats.get("digg_count", 0)
        comments = stats.get("comment_count", 0)
        shares = stats.get("share_count", 0)
        plays = stats.get("play_count", 0)

        # 视频时长（毫秒 -> 秒）
        duration = video.get("duration", 0)
        if duration > 1000:
            duration = duration / 1000

        # 分享链接
        aweme_id = item.get("aweme_id", "")
        share_url = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""

        items.append({
            "title": desc,
            "author": author_name,
            "author_followers": author.get("follower_count", 0),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "plays": plays,
            "duration": int(duration),
            "url": share_url,
            "create_time": item.get("create_time", ""),
        })
    return items


# ============================================================
# 格式化输出
# ============================================================
def format_count(val):
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


def format_duration(seconds):
    """格式化时长"""
    if not seconds:
        return "-"
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}分{s}秒"
    return f"{s}秒"


def format_as_markdown(keyword, videos, search_url):
    """格式化为 Markdown"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 🎬 热点视频查询：「{keyword}」",
        f"",
        f"> 查询时间：{now}　|　找到 {len(videos)} 条视频",
        f"> 🔗 [在抖音中搜索更多]({search_url})",
        f"",
    ]

    if not videos:
        lines.append("⚠️ 未通过 API 获取到视频数据，请点击上方链接在抖音中直接搜索查看。")
        lines.append("")
        lines.append("**💡 提示**：你也可以让我打开浏览器帮你搜索（需要配置 Playwright）。")
        return "\n".join(lines)

    lines.extend([
        f"| # | 视频内容 | 作者 | ▶️播放 | ❤️点赞 | 💬评论 | 时长 |",
        f"|:--:|----------|------|------:|------:|------:|-----:|",
    ])

    for i, v in enumerate(videos):
        title = v.get("title", "")
        if len(title) > 40:
            title = title[:40] + "…"
        url = v.get("url", "")
        if url:
            title = f"[{title}]({url})"

        author = v.get("author", "未知")
        plays = format_count(v.get("plays", 0))
        likes = format_count(v.get("likes", 0))
        comments = format_count(v.get("comments", 0))
        duration = format_duration(v.get("duration", 0))

        lines.append(f"| {i+1} | {title} | {author} | {plays} | {likes} | {comments} | {duration} |")

    lines.extend([
        f"",
        f"---",
        f"*数据仅供参考，实时数据请到抖音 App 中查看*",
    ])

    return "\n".join(lines)


def format_as_text(keyword, videos, search_url):
    """格式化为纯文本"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"🎬 热点视频查询：「{keyword}」({now})",
        f"🔗 抖音搜索链接: {search_url}",
        f"{'=' * 60}",
    ]

    if not videos:
        lines.append("⚠️ 未通过 API 获取到视频数据")
        lines.append(f"请直接访问: {search_url}")
        return "\n".join(lines)

    for i, v in enumerate(videos):
        title = v.get("title", "")
        if len(title) > 50:
            title = title[:50] + "…"
        author = v.get("author", "未知")
        plays = format_count(v.get("plays", 0))
        likes = format_count(v.get("likes", 0))
        comments = format_count(v.get("comments", 0))
        duration = format_duration(v.get("duration", 0))
        url = v.get("url", "")

        lines.append(f"")
        lines.append(f"  {i+1}. {title}")
        lines.append(f"     作者: {author}  |  时长: {duration}")
        lines.append(f"     ▶️{plays}  ❤️{likes}  💬{comments}")
        if url:
            lines.append(f"     🔗 {url}")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================
SORT_MAP = {
    "default": 0, "综合": 0,
    "likes": 1, "点赞": 1, "最多点赞": 1,
    "latest": 2, "最新": 2, "最新发布": 2,
}

TIME_MAP = {
    "all": 0, "不限": 0,
    "day": 1, "今天": 1, "一天": 1,
    "week": 2, "本周": 2, "一周": 2,
    "halfyear": 3, "半年": 3,
}

DURATION_MAP = {
    "all": 0, "不限": 0,
    "short": 1, "短": 1, "1分钟内": 1,
    "medium": 2, "中": 2, "1-5分钟": 2,
    "long": 3, "长": 3, "5分钟以上": 3,
}


def main():
    parser = argparse.ArgumentParser(description="抖音热点视频查询")
    parser.add_argument("keyword", type=str, help="搜索关键词（热点话题名称）")
    parser.add_argument("--top", type=int, default=10, help="返回前 N 条（默认 10）")
    parser.add_argument("--sort", type=str, default="default",
                        help="排序方式：default(综合) / likes(最多点赞) / latest(最新)")
    parser.add_argument("--time", type=str, default="all",
                        help="发布时间：all(不限) / day(一天内) / week(一周内) / halfyear(半年内)")
    parser.add_argument("--duration", type=str, default="all",
                        help="视频时长：all(不限) / short(1分钟内) / medium(1-5分钟) / long(5分钟以上)")
    parser.add_argument("--page", type=int, default=1, help="分页（默认第 1 页）")
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="text", help="输出格式")
    args = parser.parse_args()

    keyword = args.keyword
    sort_type = SORT_MAP.get(args.sort, 0)
    publish_time = TIME_MAP.get(args.time, 0)
    filter_duration = DURATION_MAP.get(args.duration, 0)

    # 构造抖音搜索 URL（始终可用）
    search_url = get_douyin_search_url(keyword)

    # 尝试通过 API 获取视频数据
    videos, err = search_via_api(keyword, sort_type, publish_time, filter_duration, args.page)

    if videos:
        videos = videos[:args.top]
    else:
        videos = []

    # 输出
    if args.format == "json":
        output = {
            "keyword": keyword,
            "searched_at": datetime.now().isoformat(),
            "search_url": search_url,
            "total": len(videos),
            "api_available": len(videos) > 0,
            "items": videos,
        }
        if err:
            output["note"] = err
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(format_as_markdown(keyword, videos, search_url))
    else:
        print(format_as_text(keyword, videos, search_url))

    # 如果 API 没数据，提示用户
    if not videos and err:
        print(f"\n💡 {err}", file=sys.stderr)
        print(f"💡 抖音搜索链接: {search_url}", file=sys.stderr)


if __name__ == "__main__":
    main()
