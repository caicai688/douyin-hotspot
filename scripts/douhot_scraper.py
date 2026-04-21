#!/usr/bin/env python3
"""
抖音热点宝数据采集脚本（Playwright 版）

通过浏览器自动化访问抖音热点宝（douhot.douyin.com），采集：
1. 热点话题列表（热度值、上榜时长等）
2. 每个热点的关联视频（标题、作者、播放量、点赞数、视频链接）

前置条件：
  pip install playwright && playwright install chromium

用法：
  # 第一次使用：扫码登录并保存 cookies
  python douhot_scraper.py --login

  # 采集热点关联视频（默认 top 10 热点，每个 5 条视频）
  python douhot_scraper.py --top 10 --videos 5

  # 只采集热点列表（不采集视频）
  python douhot_scraper.py --list-only

  # 按关键词搜索热点关联视频
  python douhot_scraper.py --keyword "拨开天空的乌云"

  # 输出 JSON 格式
  python douhot_scraper.py --top 5 --format json --output /tmp/douhot_data.json
"""

import os
import sys
import json
import argparse
import time
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CACHE_DIR = SKILL_DIR / "cache"
COOKIES_PATH = CACHE_DIR / "douhot_cookies.json"
SCREENSHOT_DIR = CACHE_DIR / "screenshots"

# 热点宝 URL
DOUHOT_BASE = "https://douhot.douyin.com"
DOUHOT_HOME = f"{DOUHOT_BASE}/square/hotspot"  # 榜单聚合页（含视频榜、话题榜、搜索榜）
DOUHOT_SEARCH = f"{DOUHOT_BASE}/square/hotspot"  # 搜索榜

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# ============================================================
# Cookie 管理
# ============================================================

def save_cookies(context, path=None):
    """保存浏览器 cookies"""
    path = path or COOKIES_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cookies = context.cookies()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print(f"  ✅ Cookies 已保存 ({len(cookies)} 条) → {path}")
    return cookies


def load_cookies(context, path=None):
    """加载 cookies 到浏览器上下文"""
    path = path or COOKIES_PATH
    if Path(path).exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            # 只加载 douyin.com 相关的 cookies
            valid_cookies = []
            for c in cookies:
                if "douyin" in c.get("domain", ""):
                    valid_cookies.append(c)
            context.add_cookies(valid_cookies)
            print(f"  ✅ 已加载 Cookies ({len(valid_cookies)} 条)")
            return True
        except Exception as e:
            print(f"  ⚠️ 加载 Cookies 失败: {e}")
    return False


def check_cookies_valid():
    """检查 cookies 文件是否存在且可能有效"""
    if not COOKIES_PATH.exists():
        return False, "未找到 cookies 文件，请先运行 --login 登录"
    try:
        with open(COOKIES_PATH, "r") as f:
            cookies = json.load(f)
        if len(cookies) < 5:
            return False, f"Cookies 太少 ({len(cookies)} 条)，请重新 --login"
        # 检查是否有 douyin.com 相关的 cookie
        douyin_cookies = [c for c in cookies if "douyin" in c.get("domain", "")]
        if len(douyin_cookies) < 3:
            return False, "Cookies 缺少 douyin.com 域名数据，请重新 --login"
        return True, f"Cookies 有效 ({len(douyin_cookies)} 条 douyin 相关)"
    except Exception as e:
        return False, f"Cookies 文件损坏: {e}"


# ============================================================
# 浏览器上下文
# ============================================================

def create_context(browser):
    """创建带反检测的浏览器上下文"""
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        color_scheme="light",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
        window.chrome = { runtime: {} };
    """)
    return context


def take_screenshot(page, name="debug"):
    """截图用于调试"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"douhot_{name}_{ts}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"  📸 截图: {path}")
    return path


# ============================================================
# 登录
# ============================================================

def do_login():
    """打开热点宝让用户扫码登录+授权，保存 cookies"""
    if not HAS_PLAYWRIGHT:
        print("❌ 需要安装 playwright: pip install playwright && playwright install chromium")
        return False

    print("🔐 打开抖音热点宝登录页面...")
    print("   热点宝需要两步：① 抖音账号登录 ② 授权热点宝访问你的信息")
    print("   请在浏览器中扫码完成这两步操作。")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = create_context(browser)
        page = context.new_page()

        # 直接打开热点宝，它会自动跳转到登录/授权页面
        page.goto(DOUHOT_HOME, wait_until="domcontentloaded", timeout=30000)
        print("  ⏳ 请在浏览器中完成以下操作:")
        print("     1. 用抖音扫码登录（如果要求登录）")
        print("     2. 点击「确认授权」（如果弹出授权页面）")
        print("     3. 等待热点宝页面加载完成（看到热点数据即可）")
        print()

        max_wait = 300
        start = time.time()
        logged_in = False

        while time.time() - start < max_wait:
            # 检查页面是否已经加载了热点数据
            try:
                body = page.inner_text("body")
                # 热点宝加载成功的标志
                if any(kw in body for kw in ["热点榜", "热搜", "上榜", "热度", "话题详情"]):
                    # 确认不是停留在登录/授权页面
                    if "扫一扫" not in body and "确认授权" not in body and "申请使用" not in body:
                        logged_in = True
                        break
            except Exception:
                pass
            time.sleep(3)

        if logged_in:
            # 多等一会让数据完全加载
            page.wait_for_timeout(3000)
            save_cookies(context)
            print("\n🎉 热点宝登录+授权成功！后续采集将自动使用已保存的登录状态。")
        else:
            print("\n⚠️ 等待超时（300秒），未检测到热点宝页面加载成功。")
            # 仍然保存 cookies，可能部分登录成功
            save_cookies(context)
            # 检查停在了哪一步
            try:
                body = page.inner_text("body")
                if "扫一扫" in body or "登录" in body:
                    print("   → 看起来停在了登录页面，请重试 --login")
                elif "确认授权" in body or "申请使用" in body:
                    print("   → 看起来停在了授权页面，请点击「确认授权」后重试")
                else:
                    take_screenshot(page, "login_timeout")
                    print("   → 截图已保存，请检查页面状态")
            except Exception:
                pass

        browser.close()
        return logged_in


# ============================================================
# 数据采集 - 网络请求拦截模式
# ============================================================

def scrape_hotspot_list(page, debug=False, max_challenge_pages=3):
    """
    从热点宝榜单聚合页采集数据。
    通过拦截 XHR 请求获取接口数据。
    
    热点宝有三类榜单:
    - hot_search/query_list: 搜索榜（热搜词 + 搜索热度）
    - material/video_billboard: 视频榜（热门视频 + 播放量）
    - material/challenge_billboard: 话题榜（话题 + 播放量）
    
    Args:
        page: Playwright page 对象
        debug: 调试模式
        max_challenge_pages: 话题榜最大翻页次数（默认3页，首页+2次翻页）
    """
    captured_data = {
        "search": [],    # 搜索榜
        "video": [],     # 视频榜
        "challenge": [],  # 话题榜
    }

    def handle_response(response):
        """拦截网络响应，捕获热点数据接口"""
        url = response.url
        try:
            if response.status == 200:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    body = response.json()
                    if body.get("code") == 0 and body.get("data"):
                        if "hot_search/query_list" in url:
                            captured_data["search"].append(body["data"])
                            if debug:
                                print(f"  🔍 捕获搜索榜接口")
                        elif "video_billboard" in url:
                            captured_data["video"].append(body["data"])
                            if debug:
                                print(f"  🎬 捕获视频榜接口")
                        elif "challenge_billboard" in url:
                            captured_data["challenge"].append(body["data"])
                            if debug:
                                print(f"  📌 捕获话题榜接口 (第{len(captured_data['challenge'])}批)")
        except Exception:
            pass

    page.on("response", handle_response)

    # 导航到榜单聚合页
    print("  🔄 正在加载热点宝榜单聚合页...")
    page.goto(DOUHOT_HOME, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(10000)  # 等待 SPA 渲染和所有接口请求完成

    if debug:
        take_screenshot(page, "hotspot_list")

    # 切换到话题榜 Tab 并利用分页器翻页获取更多话题
    # 聚合页的话题榜只显示 5 个预览，话题榜 Tab 页有 Arco Pagination 分页器，
    # 每页 10 条，总计约 1000 条。
    if max_challenge_pages > 1:
        print(f"  🔄 切换到话题榜 Tab 获取更多话题 (最多{max_challenge_pages}页)...")
        try:
            # 点击话题榜 Tab
            tab_btn = page.locator('text="话题榜"').first
            if tab_btn.is_visible(timeout=3000):
                tab_btn.click()
                page.wait_for_timeout(5000)
                if debug:
                    print(f"     ✅ 已切换到话题榜 Tab")
                    take_screenshot(page, "challenge_tab")
                
                # 利用 Arco Design 分页器翻页
                # 分页器结构: [class*="pagination"] 包含 [class*="next"] 下一页按钮
                for page_num in range(1, max_challenge_pages):
                    prev_count = len(captured_data["challenge"])
                    
                    try:
                        next_btn = page.locator('[class*="pagination"] [class*="next"]').first
                        if next_btn.is_visible(timeout=2000):
                            # 检查是否被 disabled
                            is_disabled = next_btn.get_attribute("class") or ""
                            if "disabled" in is_disabled:
                                if debug:
                                    print(f"     已到最后一页，停止翻页")
                                break
                            next_btn.click()
                            page.wait_for_timeout(3000)
                            
                            if len(captured_data["challenge"]) > prev_count:
                                if debug:
                                    print(f"     第{page_num + 1}页: 获取成功")
                            else:
                                if debug:
                                    print(f"     第{page_num + 1}页: 无新数据，停止翻页")
                                break
                        else:
                            if debug:
                                print(f"     未找到下一页按钮，停止翻页")
                            break
                    except Exception as e:
                        if debug:
                            print(f"     翻页异常: {e}")
                        break
                
                total_challenge_batches = len(captured_data["challenge"])
                print(f"  ✅ 话题榜采集完成: 共 {total_challenge_batches} 批数据")
            else:
                print(f"  ⚠️ 未找到话题榜 Tab")
        except Exception as e:
            print(f"  ⚠️ 话题榜 Tab 切换失败: {e}")

    # 解析搜索榜数据（最有价值，包含热搜词和搜索热度）
    hotspots = []
    for data in captured_data["search"]:
        search_list = data.get("search_list", [])
        for item in search_list:
            hotspots.append({
                "title": item.get("key_word", ""),
                "hot_value": item.get("search_score", 0),
                "trends": item.get("trends", []),
                "source": "search_billboard",
            })

    if hotspots:
        print(f"  ✅ 从搜索榜获取到 {len(hotspots)} 个热搜词")

    # 解析视频榜数据
    video_list = []
    for data in captured_data["video"]:
        objs = data.get("objs", [])
        for item in objs:
            video_list.append({
                "item_id": item.get("item_id", ""),
                "title": item.get("item_title", ""),
                "cover": item.get("item_cover_url", ""),
                "author": item.get("nick_name", ""),
                "avatar": item.get("avatar_url", ""),
                "fans_count": _safe_int(item.get("fans_cnt", 0)),
                "play_count": _safe_int(item.get("play_cnt", 0)),
                "like_count": _safe_int(item.get("like_cnt", 0)),
                "follow_count": _safe_int(item.get("follow_cnt", 0)),
                "follow_rate": item.get("follow_rate", 0),
                "like_rate": item.get("like_rate", 0),
                "score": _safe_int(item.get("score", 0)),
                "publish_time": item.get("publish_time", 0),
                "duration": _safe_int(item.get("item_duration", 0)),
                "media_type": item.get("media_type", 0),
                "url": f"https://www.douyin.com/video/{item.get('item_id', '')}",
                "source": "video_billboard",
            })

    if video_list:
        # 去重（同一个 item_id 只保留一次）
        seen_ids = set()
        unique_videos = []
        for v in video_list:
            vid = v.get("item_id", "")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                unique_videos.append(v)
        video_list = unique_videos
        print(f"  ✅ 从视频榜获取到 {len(video_list)} 条热门视频（已去重）")

    # 解析话题榜数据
    challenge_list = []
    for data in captured_data["challenge"]:
        objs = data.get("objs", [])
        for item in objs:
            challenge_list.append({
                "title": item.get("challenge_name", ""),
                "challenge_id": item.get("challenge_id", ""),
                "play_count": _safe_int(item.get("play_cnt", 0)),
                "publish_count": _safe_int(item.get("publish_cnt", 0)),
                "avg_play_count": _safe_int(item.get("avg_play_cnt", 0)),
                "score": _safe_int(item.get("score", 0)),
                "cover": item.get("cover_url", ""),
                "trends": item.get("trends", []),
                "rank": item.get("show_rank", 0),
                "source": "challenge_billboard",
            })

    if challenge_list:
        # 去重（同一个 challenge_id 只保留一次，翻页可能有重复）
        seen_cids = set()
        unique_challenges = []
        for c in challenge_list:
            cid = c.get("challenge_id", "")
            if cid and cid not in seen_cids:
                seen_cids.add(cid)
                unique_challenges.append(c)
            elif not cid:
                unique_challenges.append(c)  # 无 ID 的保留
        if len(unique_challenges) < len(challenge_list):
            print(f"  ✅ 从话题榜获取到 {len(unique_challenges)} 个热门话题（去重前 {len(challenge_list)} 个）")
        else:
            print(f"  ✅ 从话题榜获取到 {len(unique_challenges)} 个热门话题")
        challenge_list = unique_challenges

    # 合并结果：优先搜索榜，同时附带视频榜和话题榜
    result = {
        "hotspots": hotspots,
        "videos": video_list,
        "challenges": challenge_list,
    }

    if not hotspots and not video_list and not challenge_list:
        print("  ❌ 未能获取任何榜单数据")
        if debug:
            take_screenshot(page, "hotspot_fail")
            body_text = page.inner_text("body")[:300]
            print(f"  📄 页面内容预览: {body_text}")

    return result


def _parse_hotspot_api_data(data):
    """从热点宝 API 响应中解析热点列表"""
    hotspots = []

    if not isinstance(data, dict):
        return hotspots

    # 递归查找包含热点数据的列表
    def _find_list(obj, depth=0):
        if depth > 5:
            return []
        results = []

        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    # 判断是否是热点数据项
                    if any(k in item for k in ["word", "title", "hot_value", "sentence_id", "group_id"]):
                        results.append(item)
                    else:
                        results.extend(_find_list(item, depth + 1))
            return results

        if isinstance(obj, dict):
            # 常见的列表字段名
            for key in ["word_list", "data", "list", "items", "hot_list", "trending_list",
                        "hotspot_list", "result", "words"]:
                if key in obj and isinstance(obj[key], list):
                    found = _find_list(obj[key], depth + 1)
                    if found:
                        return found
            # 递归搜索其他字段
            for key, val in obj.items():
                found = _find_list(val, depth + 1)
                if found:
                    return found

        return results

    raw_list = _find_list(data)

    for item in raw_list:
        hotspot = {
            "title": item.get("word") or item.get("title") or item.get("sentence", ""),
            "hot_value": item.get("hot_value") or item.get("heat") or item.get("score", 0),
            "label": item.get("label") or item.get("tag", ""),
            "group_id": item.get("group_id") or item.get("sentence_id", ""),
            "video_count": item.get("video_count", 0),
            "raw": item,
        }
        if hotspot["title"]:
            hotspots.append(hotspot)

    return hotspots


def _extract_hotspots_from_dom(page):
    """从热点宝页面 DOM 中提取热点列表"""
    hotspots = []
    try:
        # 尝试多种选择器
        selectors = [
            'table tbody tr',
            '[class*="hotspot"] [class*="item"]',
            '[class*="hot-list"] [class*="item"]',
            '[class*="rank"] [class*="item"]',
            'div[class*="list"] > div',
        ]

        for selector in selectors:
            elements = page.query_selector_all(selector)
            if len(elements) >= 3:  # 至少要有 3 个条目才算有效
                print(f"  📦 DOM [{selector}] => {len(elements)} 个元素")
                for i, el in enumerate(elements):
                    text = el.inner_text().strip()
                    if len(text) < 3:
                        continue

                    # 尝试解析文本行
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    if lines:
                        title = ""
                        hot_value = 0
                        for line in lines:
                            # 跳过纯数字排名
                            if re.match(r'^\d{1,2}$', line):
                                continue
                            # 热度值
                            hot_match = re.search(r'([\d,]+\.?\d*)\s*[万]?', line)
                            if hot_match and not title:
                                continue
                            # 第一个非数字非热度的文本作为标题
                            if not title and len(line) > 2 and not re.match(r'^[\d,.]+$', line):
                                title = line

                        if title:
                            hotspots.append({
                                "title": title,
                                "hot_value": hot_value,
                                "rank": i + 1,
                            })

                if hotspots:
                    break

    except Exception as e:
        print(f"  ⚠️ DOM 提取失败: {e}")

    return hotspots


# ============================================================
# 数据采集 - 热点关联视频
# ============================================================

def scrape_hotspot_videos(page, keyword, top_n=5, debug=False):
    """
    采集热点关键词对应的视频列表。
    优先从热点宝的热点详情页获取，降级走抖音搜索。
    """
    captured_videos = []

    def handle_response(response):
        url = response.url
        try:
            if any(k in url for k in ["video", "aweme", "related", "search"]):
                if response.status == 200:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        body = response.json()
                        captured_videos.append({
                            "url": url,
                            "data": body,
                        })
                        if debug:
                            print(f"  🎬 捕获视频接口: {url[:100]}...")
        except Exception:
            pass

    page.on("response", handle_response)

    # 尝试热点宝搜索
    search_url = f"{DOUHOT_BASE}/analytics/hotspot?keyword={quote(keyword)}"
    print(f"  🔍 搜索关联视频: {keyword}")

    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(6000)

    if debug:
        take_screenshot(page, f"video_{keyword[:10]}")

    # 从接口数据解析视频列表
    videos = []
    for item in captured_videos:
        parsed = _parse_video_api_data(item["data"])
        if parsed:
            videos.extend(parsed)

    # 去重（按 title 或 item_id）
    seen = set()
    unique = []
    for v in videos:
        key = v.get("item_id") or v.get("title", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(v)

    if unique:
        print(f"  ✅ 获取到 {len(unique)} 条关联视频")
        return unique[:top_n]

    # 降级：从 DOM 提取
    dom_videos = _extract_videos_from_dom(page)
    if dom_videos:
        print(f"  ✅ 从 DOM 提取到 {len(dom_videos)} 条视频")
        return dom_videos[:top_n]

    print(f"  ⚠️ 未获取到 {keyword} 的关联视频")
    return []


def _parse_video_api_data(data):
    """从 API 响应中解析视频列表"""
    videos = []

    if not isinstance(data, dict):
        return videos

    def _find_videos(obj, depth=0):
        if depth > 5:
            return []
        results = []

        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    if any(k in item for k in ["aweme_id", "item_id", "desc", "title"]):
                        vid = _extract_video(item)
                        if vid:
                            results.append(vid)
                    else:
                        results.extend(_find_videos(item, depth + 1))
            return results

        if isinstance(obj, dict):
            for key in ["aweme_list", "video_list", "items", "data", "list",
                        "related_videos", "search_list", "videos"]:
                if key in obj and isinstance(obj[key], list):
                    found = _find_videos(obj[key], depth + 1)
                    if found:
                        return found
            for key, val in obj.items():
                found = _find_videos(val, depth + 1)
                if found:
                    return found

        return results

    return _find_videos(data)


def _extract_video(item):
    """从单个视频数据字典中提取结构化信息"""
    title = item.get("desc") or item.get("title") or ""
    if not title:
        return None

    aweme_id = item.get("aweme_id") or item.get("item_id") or ""
    url = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""

    author_info = item.get("author", {})
    author = ""
    if isinstance(author_info, dict):
        author = author_info.get("nickname", "")

    stats = item.get("statistics", {})
    if isinstance(stats, dict):
        likes = _safe_int(stats.get("digg_count", 0))
        comments = _safe_int(stats.get("comment_count", 0))
        shares = _safe_int(stats.get("share_count", 0))
        plays = _safe_int(stats.get("play_count", 0))
    else:
        likes = comments = shares = plays = 0

    # 热点宝可能用不同的字段名
    if not likes:
        likes = _safe_int(item.get("digg_count") or item.get("like_count", 0))
    if not plays:
        plays = _safe_int(item.get("play_count") or item.get("vv", 0))
    if not comments:
        comments = _safe_int(item.get("comment_count", 0))

    video_info = item.get("video", {})
    duration = 0
    if isinstance(video_info, dict):
        duration = _safe_int(video_info.get("duration", 0))

    cover = ""
    if isinstance(video_info, dict):
        cover_info = video_info.get("cover", {})
        if isinstance(cover_info, dict):
            urls = cover_info.get("url_list", [])
            if urls:
                cover = urls[0]
    if not cover:
        cover = item.get("cover", "") or item.get("cover_url", "")

    create_time = item.get("create_time", 0)

    return {
        "title": title,
        "author": author,
        "item_id": aweme_id,
        "url": url,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "plays": plays,
        "duration_ms": duration,
        "cover": cover,
        "create_time": create_time,
    }


def _extract_videos_from_dom(page):
    """从页面 DOM 中提取视频列表"""
    videos = []
    try:
        # 热点宝页面的视频卡片选择器
        selectors = [
            '[class*="video-card"]',
            '[class*="video-item"]',
            '[class*="aweme-item"]',
            'a[href*="/video/"]',
        ]

        for selector in selectors:
            elements = page.query_selector_all(selector)
            if elements:
                for el in elements:
                    text = el.inner_text().strip()
                    if len(text) < 5:
                        continue

                    # 提取链接
                    href = ""
                    link = el if el.get_attribute("href") else el.query_selector("a[href*='/video/']")
                    if link:
                        href = link.get_attribute("href") or ""
                        if href.startswith("//"):
                            href = "https:" + href
                        elif href.startswith("/"):
                            href = "https://www.douyin.com" + href

                    # 提取 item_id
                    item_id = ""
                    id_match = re.search(r'/video/(\d+)', href)
                    if id_match:
                        item_id = id_match.group(1)

                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    title = lines[0] if lines else ""

                    if title:
                        videos.append({
                            "title": title,
                            "author": "",
                            "item_id": item_id,
                            "url": href,
                            "likes": 0,
                            "comments": 0,
                            "shares": 0,
                            "plays": 0,
                            "duration_ms": 0,
                            "cover": "",
                            "create_time": 0,
                        })

                if videos:
                    break

    except Exception as e:
        print(f"  ⚠️ DOM 视频提取失败: {e}")

    return videos


# ============================================================
# 主采集流程
# ============================================================

def scrape_douhot(top_n=10, videos_per_topic=5, list_only=False,
                  keyword=None, debug=False, headless=True):
    """
    主采集入口。

    Args:
        top_n: 采集 Top N 热点
        videos_per_topic: 每个热点采集几条视频
        list_only: 只采集热点列表，不采集视频
        keyword: 指定关键词搜索（不走热点列表）
        debug: 调试模式
        headless: 是否无头模式

    Returns:
        dict: {
            "hotspots": [...],     # 搜索榜热点，每项可含 videos 字段
            "top_videos": [...],   # 视频榜热门视频
            "challenges": [...],   # 话题榜热门话题
            "scraped_at": "...",
            "source": "douhot",
        }
    """
    if not HAS_PLAYWRIGHT:
        return {"error": "playwright 未安装", "hotspots": []}

    # 检查登录态
    valid, msg = check_cookies_valid()
    if not valid:
        print(f"  ⚠️ {msg}")
        return {"error": msg, "hotspots": []}

    result = {
        "hotspots": [],
        "top_videos": [],
        "challenges": [],
        "scraped_at": datetime.now().isoformat(),
        "source": "douhot.douyin.com",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = create_context(browser)
        load_cookies(context)
        page = context.new_page()

        if keyword:
            # 关键词模式：直接搜索视频
            videos = scrape_hotspot_videos(page, keyword, top_n=videos_per_topic, debug=debug)
            result["hotspots"] = [{
                "title": keyword,
                "hot_value": 0,
                "videos": videos,
            }]
        else:
            # 榜单聚合模式
            data = scrape_hotspot_list(page, debug=debug)

            if not data or (not data.get("hotspots") and not data.get("videos") and not data.get("challenges")):
                print("  ⚠️ 未获取到任何榜单数据，可能需要重新登录")
                take_screenshot(page, "no_data")
                browser.close()
                return {"error": "未获取到榜单数据，可能需要重新 --login", "hotspots": []}

            # 搜索榜热点
            hotspots = data.get("hotspots", [])[:top_n]
            for hs in hotspots:
                hs["videos"] = []

            # 视频榜热门视频（直接附带在结果中，不需要额外采集）
            result["top_videos"] = data.get("videos", [])
            result["challenges"] = data.get("challenges", [])

            # 为搜索榜热点匹配视频榜中的视频（按关键词粗匹配）
            if not list_only and result["top_videos"]:
                for hs in hotspots:
                    kw = hs["title"]
                    matched = [v for v in result["top_videos"] if kw in v.get("title", "")]
                    hs["videos"] = matched[:videos_per_topic]

            result["hotspots"] = hotspots

            print(f"\n  📊 采集汇总:")
            print(f"     搜索榜: {len(hotspots)} 个热搜词")
            print(f"     视频榜: {len(result['top_videos'])} 条热门视频")
            print(f"     话题榜: {len(result['challenges'])} 个热门话题")

        # 刷新 cookies
        save_cookies(context)
        browser.close()

    return result


# ============================================================
# 供外部脚本调用的接口
# ============================================================

def fetch_topic_detail(challenge_id, headless=True, debug=False, context=None, page=None):
    """
    采集话题详情页数据（challenge_analysis 接口）。
    
    通过访问 douhot.douyin.com/topic/detail?topic_id=xxx 页面，
    拦截 XHR 获取：
    - challenge_info: 话题基本信息
    - data_summary/index: 热度/互动数据概览
    - data_summary/item_list: 关联热门视频列表（最多 30 条）
    
    Args:
        challenge_id: 话题 ID
        headless: 无头模式
        debug: 调试模式
        context: 复用已有浏览器上下文（批量采集时避免重复打开浏览器）
        page: 复用已有页面
    
    Returns:
        dict: {
            "challenge_id": str,
            "challenge_name": str,
            "play_cnt": int,
            "publish_cnt": int,
            "create_time": int,
            "hot_score": int,
            "like_cnt": int,
            "comment_cnt": int,
            "new_play_cnt": int,   # 新增播放量（来自 data_summary/index）
            "top_videos": [        # 按点赞排序的 top 视频
                {
                    "item_id": str,
                    "title": str,
                    "author": str,
                    "url": str,
                    "like_cnt": int,
                    "comment_cnt": int,
                    "share_cnt": int,
                    "play_cnt": int,
                    "create_time": int,
                    "duration": int,
                },
                ...
            ],
            "error": None or str,
        }
    """
    captured_info = {}
    captured_index = {}
    captured_items = []

    def handle_response(response):
        url = response.url
        try:
            if response.status == 200 and 'json' in response.headers.get('content-type', ''):
                body = response.json()
                if isinstance(body, dict) and body.get('code') == 0 and body.get('data'):
                    data = body['data']
                    if 'challenge_info' in url and isinstance(data, dict):
                        captured_info.update(data)
                    elif 'data_summary/index' in url and isinstance(data, dict):
                        captured_index.update(data)
                    elif 'item_list' in url and isinstance(data, list):
                        captured_items.extend(data)
        except Exception:
            pass

    result = {
        "challenge_id": str(challenge_id),
        "challenge_name": "",
        "play_cnt": 0,
        "publish_cnt": 0,
        "create_time": 0,
        "hot_score": 0,
        "like_cnt": 0,
        "comment_cnt": 0,
        "new_play_cnt": 0,
        "top_videos": [],
        "error": None,
    }

    own_browser = False
    try:
        if page is None:
            # 需要自己创建浏览器
            if not HAS_PLAYWRIGHT:
                result["error"] = "playwright 未安装"
                return result
            valid, msg = check_cookies_valid()
            if not valid:
                result["error"] = msg
                return result

            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=headless)
            context = create_context(browser)
            load_cookies(context)
            page = context.new_page()
            own_browser = True

        page.on("response", handle_response)

        topic_url = f"{DOUHOT_BASE}/topic/detail?active_tab=topic_detail&topic_id={challenge_id}"
        if debug:
            print(f"  🔗 访问话题详情: {topic_url}")
        page.goto(topic_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(8000)

        # 解析 challenge_info
        if captured_info:
            result["challenge_name"] = captured_info.get("challenge_name", "")
            result["play_cnt"] = _safe_int(captured_info.get("play_cnt", 0))
            result["publish_cnt"] = _safe_int(captured_info.get("publish_cnt", 0))
            result["create_time"] = _safe_int(captured_info.get("create_time", 0))

        # 解析 data_summary/index
        if captured_index:
            result["hot_score"] = _safe_int(captured_index.get("hot_score", 0))
            result["like_cnt"] = _safe_int(captured_index.get("like_cnt", 0))
            result["comment_cnt"] = _safe_int(captured_index.get("comment_cnt", 0))
            result["new_play_cnt"] = _safe_int(captured_index.get("play_cnt", 0))

        # 解析 item_list — 按点赞排序
        if captured_items:
            videos = []
            for item in captured_items:
                videos.append({
                    "item_id": item.get("item_id", ""),
                    "title": item.get("item_title", ""),
                    "author": item.get("nick_name", ""),
                    "url": f"https://www.douyin.com/video/{item.get('item_id', '')}",
                    "like_cnt": _safe_int(item.get("like_cnt", 0)),
                    "comment_cnt": _safe_int(item.get("comment_cnt", 0)),
                    "share_cnt": _safe_int(item.get("share_cnt", 0)),
                    "play_cnt": _safe_int(item.get("play_cnt", 0)),
                    "create_time": _safe_int(item.get("item_create_time") or item.get("create_time", 0)),
                    "duration": _safe_int(item.get("item_duration", 0)),
                })
            # 按点赞数降序
            videos.sort(key=lambda x: x["like_cnt"], reverse=True)
            result["top_videos"] = videos

        # 移除响应监听（避免重复绑定）
        try:
            page.remove_listener("response", handle_response)
        except Exception:
            pass

    except Exception as e:
        result["error"] = str(e)

    finally:
        if own_browser:
            try:
                browser.close()
                pw.stop()
            except Exception:
                pass

    return result


def fetch_topics_with_videos(challenges, top_videos_per_topic=2, headless=True, debug=False):
    """
    批量采集话题详情数据（复用同一个浏览器上下文）。
    
    Args:
        challenges: 话题列表，每项需含 challenge_id
        top_videos_per_topic: 每个话题取 top N 视频
        headless: 无头模式
        debug: 调试模式
    
    Returns:
        list[dict]: 每项为 fetch_topic_detail 的返回值，附加 top_videos 截断
    """
    if not HAS_PLAYWRIGHT:
        print("  ⚠️ playwright 未安装，跳过话题详情采集")
        return []
    
    valid, msg = check_cookies_valid()
    if not valid:
        print(f"  ⚠️ 热点宝 {msg}")
        return []

    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = create_context(browser)
        load_cookies(context)
        page = context.new_page()
        
        for i, ch in enumerate(challenges):
            cid = ch.get("challenge_id", "")
            cname = ch.get("title", "") or ch.get("challenge_name", "")
            if not cid:
                continue
            
            print(f"  [{i+1}/{len(challenges)}] 📌 话题详情: #{cname} (id={cid})")
            detail = fetch_topic_detail(cid, headless=headless, debug=debug, context=context, page=page)
            
            if detail.get("error"):
                print(f"     ⚠️ 采集失败: {detail['error']}")
            else:
                n_vids = len(detail.get("top_videos", []))
                top_like = detail["top_videos"][0]["like_cnt"] if detail["top_videos"] else 0
                print(f"     ✅ 视频: {n_vids} 条, top1 点赞: {format_count(top_like)}, 热度分: {format_count(detail.get('hot_score', 0))}")
            
            # 截断到 top N
            detail["top_videos"] = detail.get("top_videos", [])[:top_videos_per_topic]
            # 保留榜单排名和热度分
            detail["rank"] = ch.get("rank", i + 1)
            detail["billboard_score"] = ch.get("score", 0)
            
            results.append(detail)
            
            # 防封间隔
            if i < len(challenges) - 1:
                time.sleep(2)
        
        save_cookies(context)
        browser.close()
    
    return results

def fetch_billboard_data(headless=True, debug=False):
    """
    供 hotspot_pipeline.py / daily_report.py 调用的简化接口。
    一次性获取热点宝所有榜单数据。

    Returns:
        dict: {
            "hotspots": [...],     # 搜索榜（热搜词列表）
            "top_videos": [...],   # 视频榜（热门视频列表，pipeline 标准格式）
            "challenges": [...],   # 话题榜
            "error": None or str,
        }
    """
    data = scrape_douhot(top_n=50, list_only=True, debug=debug, headless=headless)
    
    # 将视频数据转换为 pipeline 标准格式
    std_videos = []
    for v in data.get("top_videos", []):
        std_videos.append({
            "title": v.get("title", ""),
            "author": v.get("author", ""),
            "url": v.get("url", ""),
            "likes": v.get("like_count", 0),
            "comments": 0,
            "shares": 0,
            "plays": v.get("play_count", 0),
            "duration_ms": v.get("duration", 0),
            "item_id": v.get("item_id", ""),
            "cover": v.get("cover", ""),
            "score": v.get("score", 0),
            "source": "douhot_video_billboard",
        })
    data["top_videos_std"] = std_videos
    return data


def fetch_videos_for_keywords(keywords, videos_per_keyword=5, headless=True, debug=False):
    """
    供 hotspot_pipeline.py 调用的接口：按关键词匹配热点宝视频榜数据。
    
    原理：先一次性获取视频榜全部数据，再按关键词模糊匹配。
    这样只需要打开一次浏览器，效率更高。

    Args:
        keywords: list of str，关键词列表（热搜话题名）
        videos_per_keyword: 每个关键词采集几条视频
        headless: 是否无头模式
        debug: 是否调试

    Returns:
        dict: { "关键词": [视频列表(pipeline 标准格式)], ... }
    """
    if not HAS_PLAYWRIGHT:
        print("  ⚠️ playwright 未安装，跳过视频采集")
        return {}

    valid, msg = check_cookies_valid()
    if not valid:
        print(f"  ⚠️ 热点宝 {msg}")
        return {}

    # 获取完整视频榜
    data = fetch_billboard_data(headless=headless, debug=debug)
    all_videos = data.get("top_videos_std", [])
    
    if not all_videos:
        print("  ⚠️ 热点宝视频榜为空")
        return {}

    results = {}
    for kw in keywords:
        # 模糊匹配：关键词出现在视频标题中
        matched = [v for v in all_videos if kw in v.get("title", "")]
        results[kw] = matched[:videos_per_keyword]
        if matched:
            print(f"  ✅ 「{kw}」匹配到 {len(matched)} 条视频")

    return results


# ============================================================
# 工具函数
# ============================================================

def _safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def format_count(val):
    if isinstance(val, (int, float)):
        if val >= 100000000:
            return f"{val / 100000000:.1f}亿"
        if val >= 10000:
            return f"{val / 10000:.1f}万"
        return str(int(val))
    return str(val)


# ============================================================
# 输出
# ============================================================

def output_results(data, fmt="text", output_file=None):
    """格式化输出结果"""
    out = sys.stdout
    if output_file:
        out = open(output_file, "w", encoding="utf-8")

    if fmt == "json":
        json.dump(data, out, ensure_ascii=False, indent=2)
        if output_file:
            out.close()
            print(f"\n  📄 已保存到 {output_file}")
        return

    # Markdown 格式
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    hotspots = data.get("hotspots", [])
    top_videos = data.get("top_videos", [])
    challenges = data.get("challenges", [])

    if data.get("error"):
        print(f"❌ 错误: {data['error']}", file=out)
        return

    print(f"# 🔥 抖音热点宝数据采集", file=out)
    print(f"\n> 采集时间：{now}　|　数据源：热点宝 douhot.douyin.com", file=out)

    # 搜索榜
    if hotspots:
        print(f"\n## 📊 搜索榜 Top {len(hotspots)}", file=out)
        print(f"\n| # | 热搜词 | 搜索热度 |", file=out)
        print(f"|:-:|--------|---------|", file=out)
        for i, hs in enumerate(hotspots):
            title = hs.get("title", "")
            hot_val = format_count(hs.get("hot_value", 0))
            print(f"| {i+1} | {title} | {hot_val} |", file=out)

    # 视频榜
    if top_videos:
        print(f"\n## 🎬 视频榜 Top {len(top_videos)}", file=out)
        print(f"\n| # | 视频标题 | 作者 | ▶️ 播放 | ❤️ 点赞 | 🔥 热度分 | 链接 |", file=out)
        print(f"|:-:|----------|------|---------|---------|----------|------|", file=out)
        for j, v in enumerate(top_videos[:20]):
            t = v["title"][:35] + "..." if len(v["title"]) > 35 else v["title"]
            link = f"[查看]({v['url']})" if v.get("url") else "-"
            plays = format_count(v.get("play_count", 0))
            likes = format_count(v.get("like_count", 0))
            score = format_count(v.get("score", 0))
            author = v.get("author", "-") or "-"
            print(f"| {j+1} | {t} | {author} | {plays} | {likes} | {score} | {link} |", file=out)

    # 话题榜
    if challenges:
        print(f"\n## 📌 话题榜 Top {len(challenges)}", file=out)
        print(f"\n| # | 话题 | ▶️ 总播放 | 📝 发布数 | 📊 均播放 | 🔥 热度分 |", file=out)
        print(f"|:-:|------|---------|---------|---------|----------|", file=out)
        for k, c in enumerate(challenges[:20]):
            name = c.get("title", "")
            plays = format_count(c.get("play_count", 0))
            pubs = format_count(c.get("publish_count", 0))
            avg = format_count(c.get("avg_play_count", 0))
            score = format_count(c.get("score", 0))
            print(f"| {k+1} | #{name} | {plays} | {pubs} | {avg} | {score} |", file=out)

    if output_file:
        out.close()
        print(f"\n  📄 已保存到 {output_file}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="抖音热点宝数据采集")
    parser.add_argument("--login", action="store_true", help="扫码登录并保存 cookies")
    parser.add_argument("--top", type=int, default=10, help="采集 Top N 热点（默认 10）")
    parser.add_argument("--videos", type=int, default=5, help="每个热点采集几条视频（默认 5）")
    parser.add_argument("--list-only", action="store_true", help="只采集热点列表，不采集视频")
    parser.add_argument("--keyword", type=str, help="按关键词搜索关联视频")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    parser.add_argument("--output", type=str, help="输出到文件")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口（调试用）")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    if not HAS_PLAYWRIGHT:
        print("❌ 需要安装 playwright:")
        print("   pip install playwright && playwright install chromium")
        sys.exit(1)

    if args.login:
        success = do_login()
        sys.exit(0 if success else 1)

    # 采集
    data = scrape_douhot(
        top_n=args.top,
        videos_per_topic=args.videos,
        list_only=args.list_only,
        keyword=args.keyword,
        debug=args.debug,
        headless=not args.no_headless,
    )

    output_results(data, fmt=args.format, output_file=args.output)


if __name__ == "__main__":
    main()
