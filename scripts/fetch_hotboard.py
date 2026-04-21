#!/usr/bin/env python3
"""
抖音热搜榜数据获取脚本 — 多源冗余版
主源：起零数据（api.istero.com）
备源1：小小API（v2.xxapi.cn）
备源2：TenAPI（tenapi.cn）

用法：
  python fetch_hotboard.py                  # 获取热搜榜（默认 TOP 50）
  python fetch_hotboard.py --top 20         # 获取 TOP 20
  python fetch_hotboard.py --format json    # 输出原始 JSON
  python fetch_hotboard.py --no-cache       # 跳过缓存
"""

import os
import sys
import json
import time
import hashlib
import argparse
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SKILL_DIR / "config" / "api_config.json"
FILTER_PATH = SKILL_DIR / "config" / "filter_rules.json"
CACHE_DIR = SKILL_DIR / "cache" / "daily"

def load_config():
    """加载 API 配置"""
    if not CONFIG_PATH.exists():
        print(f"[ERROR] 配置文件不存在: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_filter_rules():
    """加载热点过滤规则"""
    if not FILTER_PATH.exists():
        return None
    try:
        with open(FILTER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def filter_items(items, filter_rules):
    """
    过滤不适合营销的热点话题
    返回: (filtered_items, removed_items)
    """
    if not filter_rules:
        return items, []

    blocked = filter_rules.get("blocked_categories", {})
    whitelist = filter_rules.get("whitelist_override", {}).get("keywords", [])

    # 预编译所有屏蔽关键词 -> 对应类别
    block_map = []
    for cat_name, cat_info in blocked.items():
        ignore_wl = cat_info.get("ignore_whitelist", False)
        for kw in cat_info.get("keywords", []):
            block_map.append((kw.lower(), cat_name, cat_info.get("reason", ""), ignore_wl))

    filtered = []
    removed = []

    for item in items:
        title = item.get("title", "").lower()
        hit_category = None
        hit_reason = ""
        hit_ignore_wl = False

        # 检查是否命中白名单（优先保留）
        has_whitelist = any(wk in title for wk in whitelist)

        # 检查是否命中屏蔽关键词
        for kw, cat, reason, ignore_wl in block_map:
            if kw in title:
                hit_category = cat
                hit_reason = reason
                hit_ignore_wl = ignore_wl
                break

        # 判断是否过滤：命中屏蔽词 且 (不在白名单中 或 该类别忽略白名单)
        should_filter = hit_category and (not has_whitelist or hit_ignore_wl)

        if should_filter:
            item_copy = dict(item)
            item_copy["_filtered"] = True
            item_copy["_filter_category"] = hit_category
            item_copy["_filter_reason"] = hit_reason
            removed.append(item_copy)
        else:
            filtered.append(item)

    return filtered, removed

# ============================================================
# 缓存层
# ============================================================
def get_cache_path():
    """获取今日缓存文件路径"""
    today = datetime.now().strftime("%Y-%m-%d")
    return CACHE_DIR / f"hotboard_{today}.json"

def read_cache(ttl_minutes=30):
    """读取缓存，过期则返回 None"""
    cache_path = get_cache_path()
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        cached_time = datetime.fromisoformat(cached.get("fetched_at", "2000-01-01"))
        if datetime.now() - cached_time > timedelta(minutes=ttl_minutes):
            return None
        return cached
    except Exception:
        return None

def write_cache(data):
    """写入缓存"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_cache_path()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============================================================
# API 数据源
# ============================================================
def _http_get(url, headers=None, timeout=10):
    """统一的 HTTP GET 请求封装（优先 requests，降级 urllib）"""
    if HAS_REQUESTS:
        try:
            resp = requests.get(url, headers=headers or {}, timeout=timeout)
            resp.raise_for_status()
            return resp.json(), None
        except Exception as e:
            return None, str(e)
    else:
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except Exception as e:
            return None, str(e)


def fetch_from_istero(config):
    """从起零数据获取热搜榜"""
    cfg = config["primary"]
    url = cfg["base_url"]
    token = cfg.get("token", "")

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "DouyinHotspot-Skill/1.0"
    }

    raw, err = _http_get(url, headers=headers)
    if err:
        return None, f"起零数据请求失败: {err}"

    # 解析数据 — 起零数据返回格式：{code, msg/message, data: [{rank, title, hot, url}]}
    if isinstance(raw, dict):
        data_list = raw.get("data", [])
        if not data_list and raw.get("code") != 200:
            return None, f"起零数据返回异常: {raw.get('msg', raw.get('message', str(raw)))}"
    elif isinstance(raw, list):
        data_list = raw
    else:
        return None, f"起零数据返回格式未知: {type(raw)}"

    mapping = cfg["response_mapping"]
    items = []
    for i, item in enumerate(data_list):
        items.append({
            "rank": item.get(mapping["rank_field"], i + 1),
            "title": item.get(mapping["title_field"], ""),
            "hot_value": item.get(mapping["hot_field"], ""),
            "url": item.get(mapping["url_field"], ""),
            "source": "istero"
        })

    return items, None


def fetch_from_xxapi(config):
    """从小小API获取热搜榜"""
    cfg = config["fallback_1"]
    url = cfg["base_url"]

    headers = {"User-Agent": "DouyinHotspot-Skill/1.0"}

    raw, err = _http_get(url, headers=headers)
    if err:
        return None, f"小小API请求失败: {err}"

    if raw.get("code") != 200:
        return None, f"小小API返回异常: {raw.get('msg', str(raw))}"

    mapping = cfg["response_mapping"]
    data_list = raw.get("data", [])
    items = []
    for i, item in enumerate(data_list):
        cover_urls = []
        cover_data = item.get(mapping.get("cover_field", ""), {})
        if isinstance(cover_data, dict):
            cover_urls = cover_data.get("url_list", [])

        items.append({
            "rank": item.get(mapping["rank_field"], i + 1),
            "title": item.get(mapping["title_field"], ""),
            "hot_value": item.get(mapping["hot_field"], 0),
            "url": f"https://www.douyin.com/search/{item.get(mapping['title_field'], '')}",
            "video_count": item.get(mapping.get("video_count_field", ""), 0),
            "cover_url": cover_urls[0] if cover_urls else "",
            "source": "xxapi"
        })

    return items, None


def fetch_from_tenapi(config):
    """从TenAPI获取热搜榜"""
    cfg = config["fallback_2"]
    url = cfg["base_url"]

    headers = {"User-Agent": "DouyinHotspot-Skill/1.0"}

    raw, err = _http_get(url, headers=headers)
    if err:
        return None, f"TenAPI请求失败: {err}"

    if raw.get("code") != 200:
        return None, f"TenAPI返回异常: {raw.get('msg', str(raw))}"

    mapping = cfg["response_mapping"]
    data_list = raw.get("data", [])
    items = []
    for i, item in enumerate(data_list):
        items.append({
            "rank": i + 1,
            "title": item.get(mapping["title_field"], ""),
            "hot_value": item.get(mapping["hot_field"], ""),
            "url": item.get(mapping["url_field"], ""),
            "source": "tenapi"
        })

    return items, None


# ============================================================
# 核心逻辑：多源冗余获取
# ============================================================
def fetch_hotboard(config, use_cache=True):
    """
    多源冗余获取抖音热搜榜
    优先级：缓存 > 起零数据 > 小小API > TenAPI
    """
    cache_ttl = config.get("cache", {}).get("ttl_minutes", 30)

    # 1. 尝试缓存
    if use_cache:
        cached = read_cache(cache_ttl)
        if cached:
            return cached["items"], cached.get("source", "cache"), None

    # 2. 依次尝试各数据源
    sources = [
        ("起零数据", fetch_from_istero),
        ("小小API", fetch_from_xxapi),
        ("TenAPI", fetch_from_tenapi),
    ]
    errors = []

    for name, fetcher in sources:
        items, err = fetcher(config)
        if items and len(items) > 0:
            # 成功，写缓存
            cache_data = {
                "fetched_at": datetime.now().isoformat(),
                "source": name,
                "items": items
            }
            write_cache(cache_data)
            return items, name, None
        else:
            errors.append(f"  [{name}] {err}")

    return None, None, "所有数据源均失败:\n" + "\n".join(errors)


# ============================================================
# 格式化输出
# ============================================================
def format_hot_value(val):
    """格式化热度值"""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        if val >= 10000:
            return f"{val / 10000:.1f}万"
        return str(int(val))
    return str(val)


def format_as_markdown(items, source, top_n=50):
    """格式化为 Markdown"""
    items = items[:top_n]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 🔥 抖音热搜榜",
        f"",
        f"> 更新时间：{now}　|　数据来源：{source}　|　共 {len(items)} 条",
        f"",
        f"| 排名 | 热搜话题 | 热度 | 链接 |",
        f"|:----:|----------|-----:|------|",
    ]

    for item in items:
        rank = item.get("rank", "")
        title = item.get("title", "")
        hot = format_hot_value(item.get("hot_value", ""))
        url = item.get("url", "")

        # 排名 emoji
        rank_display = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, str(rank))

        if url:
            title_display = f"[{title}]({url})"
        else:
            title_display = title

        lines.append(f"| {rank_display} | {title_display} | {hot} | {'[查看](' + url + ')' if url else '-'} |")

    lines.append("")
    lines.append("---")
    lines.append(f"*数据来源: {source} | 缓存有效期 30 分钟*")
    return "\n".join(lines)


def format_as_text(items, source, top_n=50):
    """格式化为纯文本"""
    items = items[:top_n]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"🔥 抖音热搜榜 ({now})",
        f"数据来源：{source}",
        f"{'=' * 50}",
    ]

    for item in items:
        rank = item.get("rank", "")
        title = item.get("title", "")
        hot = format_hot_value(item.get("hot_value", ""))
        lines.append(f"  {str(rank).rjust(3)}. {title}  [{hot}]")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="抖音热搜榜数据获取（多源冗余）")
    parser.add_argument("--top", type=int, default=50, help="返回 TOP N 条（默认 50）")
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="text", help="输出格式")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存，强制从 API 获取")
    parser.add_argument("--source", choices=["auto", "istero", "xxapi", "tenapi"], default="auto", help="指定数据源")
    parser.add_argument("--filter", action="store_true", help="过滤不适合营销的热点（时政、军事、明星舆论等）")
    parser.add_argument("--show-filtered", action="store_true", help="显示被过滤掉的热点及原因")
    args = parser.parse_args()

    config = load_config()

    # 获取数据
    items, source, error = fetch_hotboard(config, use_cache=not args.no_cache)

    if error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(1)

    if not items:
        print("[WARNING] 未获取到任何热搜数据", file=sys.stderr)
        sys.exit(1)

    # 过滤
    removed_items = []
    if args.filter:
        filter_rules = load_filter_rules()
        if filter_rules:
            items, removed_items = filter_items(items, filter_rules)
            # 重新编排排名
            for i, item in enumerate(items):
                item["rank"] = i + 1

    # 输出
    if args.format == "json":
        output = {
            "fetched_at": datetime.now().isoformat(),
            "source": source,
            "filtered": args.filter,
            "total": len(items[:args.top]),
            "removed_count": len(removed_items),
            "items": items[:args.top]
        }
        if args.show_filtered and removed_items:
            output["removed_items"] = removed_items
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        md = format_as_markdown(items, source, args.top)
        if args.filter:
            md += f"\n\n> ⚡ 已过滤 {len(removed_items)} 条不适合营销的热点（时政/军事/明星舆论/灾难等）"
        if args.show_filtered and removed_items:
            md += "\n\n<details><summary>📋 被过滤的热点（点击展开）</summary>\n\n"
            md += "| 原排名 | 话题 | 过滤原因 |\n|:------:|------|----------|\n"
            for item in removed_items:
                md += f"| {item.get('rank', '-')} | {item.get('title', '')} | {item.get('_filter_category', '')} |\n"
            md += "\n</details>"
        print(md)
    else:
        txt = format_as_text(items, source, args.top)
        if args.filter:
            txt += f"\n\n⚡ 已过滤 {len(removed_items)} 条不适合营销的热点"
        if args.show_filtered and removed_items:
            txt += "\n\n--- 被过滤的热点 ---"
            for item in removed_items:
                txt += f"\n  ✖ {item.get('title', '')}  [{item.get('_filter_category', '')}]"
        print(txt)


if __name__ == "__main__":
    main()
