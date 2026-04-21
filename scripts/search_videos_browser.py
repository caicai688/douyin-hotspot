#!/usr/bin/env python3
"""
抖音搜索页面采集脚本（Playwright 版）

通过浏览器自动化打开抖音搜索页面，抓取视频搜索结果的结构化数据。

模式说明：
  1. --use-chrome：使用本机 Chrome 的用户数据（推荐，可复用登录态和指纹）
  2. --no-headless：使用 Playwright 自带浏览器（可手动处理验证码）
  3. 默认：headless 模式（如遇验证码会自动提示切换模式）

用法：
  # 推荐：使用本机 Chrome 浏览器（复用登录态，不触发验证码）
  python search_videos_browser.py "穿搭" --use-chrome

  python search_videos_browser.py "穿搭" --top 10
  python search_videos_browser.py "穿搭" --format json --top 5
  python search_videos_browser.py "穿搭" --no-headless      # 弹窗模式
  python search_videos_browser.py --login                    # 仅登录保存cookies
"""

import os
import sys
import json
import argparse
import time
import re
import subprocess
import signal
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
COOKIES_PATH = SKILL_DIR / "cache" / "douyin_cookies.json"
SCREENSHOT_DIR = SKILL_DIR / "cache" / "screenshots"

# Chrome 用户数据目录
CHROME_USER_DATA = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
CHROME_PROFILE = "Profile 1"  # 可在命令行覆盖

# 检查 playwright 可用性
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


def save_cookies(context):
    """保存浏览器 cookies 到文件"""
    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    cookies = context.cookies()
    with open(COOKIES_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print(f"  ✅ Cookies 已保存 ({len(cookies)} 条)")


def load_cookies(context):
    """从文件加载 cookies"""
    if COOKIES_PATH.exists():
        try:
            with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            print(f"  ✅ 已加载保存的 Cookies ({len(cookies)} 条)")
            return True
        except Exception as e:
            print(f"  ⚠️ 加载 Cookies 失败: {e}")
    return False


def take_screenshot(page, name="debug"):
    """截图用于调试"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{name}_{ts}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"  📸 截图: {path}")
    return path


def create_stealth_context(browser):
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
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)
    return context


def do_login(headless=False):
    """打开抖音让用户登录，保存 cookies"""
    if not HAS_PLAYWRIGHT:
        print("❌ 需要安装 playwright", file=sys.stderr)
        return False

    print("🔐 打开抖音登录页面...")
    print("   请在浏览器中扫码登录，登录成功后关闭浏览器窗口即可。")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = create_stealth_context(browser)
        page = context.new_page()
        page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)

        print("  ⏳ 等待登录... (登录后会自动检测)")
        print("     如果没有弹出登录框，请手动点击页面右上角「登录」按钮")
        print()

        max_wait = 300
        start = time.time()
        logged_in = False

        while time.time() - start < max_wait:
            cookies = context.cookies()
            cookie_names = [c["name"] for c in cookies]
            if any(name in cookie_names for name in ["passport_csrf_token", "sessionid", "sid_guard"]):
                logged_in = True
                break
            time.sleep(2)

        if logged_in:
            save_cookies(context)
            print("\n🎉 登录成功！后续搜索将自动使用已保存的登录状态。")
        else:
            print("\n⚠️ 等待超时，未检测到登录状态。")
            save_cookies(context)

        browser.close()
        return logged_in


# ============================================================
# 方案 A: 使用本机 Chrome（推荐）
# ============================================================

def launch_chrome_debug(port=9222, profile=None):
    """启动本机 Chrome（CDP 远程调试模式）"""
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    chrome_bin = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome_bin = p
            break

    if not chrome_bin:
        return None, "未找到 Chrome 浏览器"

    # 用独立的临时数据目录，避免和正在运行的 Chrome 冲突
    tmp_data = SKILL_DIR / "cache" / "chrome_tmp_profile"
    tmp_data.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={tmp_data}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
    ]

    print(f"  🚀 启动 Chrome (port {port})...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 等待 Chrome 启动并且 CDP 端口可用
    import urllib.request
    max_wait = 15
    start = time.time()
    while time.time() - start < max_wait:
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            if resp.status == 200:
                print(f"  ✅ Chrome CDP 已就绪")
                return proc, None
        except Exception:
            pass
        time.sleep(1)

    return proc, f"Chrome 启动超时（{max_wait}秒内未检测到 CDP 端口 {port}）"


def search_with_chrome(keyword, top_n=10, sort="default", debug=False, profile=None, interactive=False):
    """使用本机 Chrome 通过 CDP 连接搜索抖音
    
    Args:
        interactive: 交互模式。遇到验证码时暂停等待人工处理，而不是直接失败。
    """
    if not HAS_PLAYWRIGHT:
        return None, "playwright 未安装"

    port = 9222
    chrome_proc, err = launch_chrome_debug(port, profile)
    if err:
        return None, err

    sort_param = ""
    if sort == "likes":
        sort_param = "&sort_type=1"
    elif sort == "latest":
        sort_param = "&sort_type=2"

    url = f"https://www.douyin.com/search/{quote(keyword)}?type=video{sort_param}"
    videos = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()

            print(f"  🔍 正在搜索: {keyword}")
            print(f"  🔗 {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等待页面加载
            print("  ⏳ 等待页面加载...")
            page.wait_for_timeout(5000)

            if debug:
                take_screenshot(page, "chrome_load")

            # 检查是否有搜索结果
            has_results = check_has_results(page)
            if not has_results:
                if interactive:
                    # 交互模式：等待人工处理验证码
                    print("  ⚠️ 遇到验证码/页面未加载，请在 Chrome 窗口中手动处理...")
                    print("  👆 处理完成后搜索结果会自动加载，脚本会自动继续")
                    print("  ⏳ 等待中（最多 180 秒）...")
                    start_wait = time.time()
                    while time.time() - start_wait < 180:
                        if check_has_results(page):
                            print("  ✅ 验证通过，搜索结果已加载！")
                            page.wait_for_timeout(2000)
                            break
                        time.sleep(3)
                    else:
                        print("  ⚠️ 等待超时（180秒），跳过此热点")
                        page.close()
                        browser.close()
                        return None, "人工处理验证码超时（180秒）"
                else:
                    # 非交互模式：再等 5 秒后放弃
                    print("  ⚠️ 页面未显示搜索结果，等待更长时间...")
                    page.wait_for_timeout(5000)
                    has_results = check_has_results(page)

            if debug:
                take_screenshot(page, "chrome_check")

            # 滚动加载更多
            page.evaluate("window.scrollTo(0, 800)")
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 1600)")
            page.wait_for_timeout(2000)

            if debug:
                take_screenshot(page, "chrome_scroll")

            # 提取数据
            videos = try_extract_from_script(page)
            if not videos:
                videos = try_extract_from_dom(page)
            if not videos:
                videos = try_extract_from_ssr(page)

            # 关闭标签页（不关浏览器）
            page.close()
            browser.close()

    except Exception as e:
        return None, f"Chrome CDP 采集失败: {str(e)}"
    finally:
        # 关闭 Chrome 进程
        if chrome_proc:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()

    if videos:
        return videos[:top_n], None
    else:
        return None, "未能提取视频数据。可尝试 --interactive 模式手动完成验证码后再采集。"


# ============================================================
# 方案 B: 使用 Playwright 自带浏览器
# ============================================================

def search_douyin_videos(keyword, top_n=10, sort="default", headless=True, debug=False):
    """通过 Playwright 打开抖音搜索页面，抓取视频搜索结果"""
    if not HAS_PLAYWRIGHT:
        return None, "playwright 未安装"

    sort_param = ""
    if sort == "likes":
        sort_param = "&sort_type=1"
    elif sort == "latest":
        sort_param = "&sort_type=2"

    url = f"https://www.douyin.com/search/{quote(keyword)}?type=video{sort_param}"
    videos = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = create_stealth_context(browser)
            has_cookies = load_cookies(context)
            if not has_cookies:
                print("  ⚠️ 没有保存的登录状态，建议先运行 --login 登录")

            page = context.new_page()
            print(f"  🔍 正在搜索: {keyword}")
            print(f"  🔗 {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            print("  ⏳ 等待页面加载...")
            page.wait_for_timeout(3000)

            has_results = check_has_results(page)
            if not has_results:
                if headless:
                    print("  ⚠️ 页面未显示搜索结果（可能遇到验证码）")
                    print("  💡 建议用 --no-headless 或 --use-chrome 模式运行。")
                    if debug:
                        take_screenshot(page, "no_results")
                    browser.close()
                    return None, "页面未显示搜索结果（可能遇到验证码），请用 --no-headless 或 --use-chrome 模式运行"
                else:
                    print("  ⚠️ 页面未显示搜索结果，可能需要手动处理验证码。")
                    print("  👆 请在浏览器窗口中完成验证码操作...")
                    print("  ⏳ 等待搜索结果出现（最多 120 秒）...")
                    start_wait = time.time()
                    while time.time() - start_wait < 120:
                        if check_has_results(page):
                            print("  ✅ 搜索结果已加载！继续采集...")
                            page.wait_for_timeout(2000)
                            break
                        time.sleep(3)
                    else:
                        print("  ⚠️ 等待超时。")

            if debug:
                take_screenshot(page, "after_load")

            page.evaluate("window.scrollTo(0, 600)")
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 1200)")
            page.wait_for_timeout(2000)

            if debug:
                take_screenshot(page, "after_scroll")

            # 提取数据
            videos = try_extract_from_script(page)
            if not videos:
                videos = try_extract_from_dom(page)
            if not videos:
                videos = try_extract_from_ssr(page)

            if debug:
                take_screenshot(page, "final")

            save_cookies(context)
            browser.close()

    except Exception as e:
        return None, f"浏览器采集失败: {str(e)}"

    if videos:
        return videos[:top_n], None
    else:
        return None, "未能提取视频数据。建议: 1) --login 登录 2) --no-headless 手动验证码 3) --use-chrome 使用本机Chrome"


# ============================================================
# 数据提取方法
# ============================================================

def check_has_results(page):
    """检查页面是否已经展示搜索结果"""
    try:
        body_text = page.inner_text("body")
        if "点击" in body_text[:300] and ("相同" in body_text[:300] or "验证" in body_text[:300]):
            return False
        if "口渴" in body_text[:300] or "拖拽" in body_text[:300]:
            return False
        if any(kw in body_text for kw in ["点赞", "播放", "关注", "万", "粉丝", "作品"]):
            return True
        cards = page.query_selector_all('[data-e2e="scroll-list"] li')
        if len(cards) > 0:
            # 检查卡片里是否有实际内容（不是空占位符）
            for card in cards[:3]:
                text = card.inner_text().strip()
                if len(text) > 10:
                    return True
    except Exception:
        pass
    return False


def try_extract_from_script(page):
    """从页面内嵌的 JSON 数据中提取视频信息"""
    videos = []
    try:
        data = page.evaluate("""
            () => {
                const renderEl = document.getElementById('RENDER_DATA');
                if (renderEl) {
                    try {
                        return { type: 'RENDER_DATA', data: JSON.parse(decodeURIComponent(renderEl.textContent)) };
                    } catch(e) {}
                }
                const nextEl = document.getElementById('__NEXT_DATA__');
                if (nextEl) {
                    try {
                        return { type: 'NEXT_DATA', data: JSON.parse(nextEl.textContent) };
                    } catch(e) {}
                }
                if (window._SSR_HYDRATED_DATA) {
                    return { type: 'SSR', data: window._SSR_HYDRATED_DATA };
                }
                return null;
            }
        """)

        if not data:
            return []

        raw = data.get("data", {})
        videos = _deep_find_videos(raw)
        if videos:
            print(f"  ✅ 从 {data['type']} 提取到 {len(videos)} 条视频")

    except Exception as e:
        print(f"  ⚠️ Script 提取失败: {e}")

    return videos


def _deep_find_videos(obj, depth=0, max_depth=10):
    """递归搜索 JSON 结构中的视频列表"""
    if depth > max_depth:
        return []

    videos = []

    if isinstance(obj, dict):
        if "desc" in obj and ("video" in obj or "author" in obj or "statistics" in obj):
            vid = _extract_video_from_dict(obj)
            if vid:
                return [vid]

        for key in ["data", "aweme_list", "video_list", "items", "list", "search_list"]:
            if key in obj and isinstance(obj[key], list):
                for item in obj[key]:
                    vids = _deep_find_videos(item, depth + 1, max_depth)
                    videos.extend(vids)
                if videos:
                    return videos

        for key, val in obj.items():
            vids = _deep_find_videos(val, depth + 1, max_depth)
            videos.extend(vids)
            if len(videos) >= 30:
                return videos

    elif isinstance(obj, list):
        for item in obj:
            vids = _deep_find_videos(item, depth + 1, max_depth)
            videos.extend(vids)
            if len(videos) >= 30:
                return videos

    return videos


def _extract_video_from_dict(obj):
    """从视频字典中提取结构化信息"""
    try:
        title = obj.get("desc", "")
        if not title:
            return None

        author_info = obj.get("author", {})
        author = author_info.get("nickname", "") if isinstance(author_info, dict) else ""

        stats = obj.get("statistics", {})
        if isinstance(stats, dict):
            likes = _safe_int(stats.get("digg_count", 0))
            comments = _safe_int(stats.get("comment_count", 0))
            shares = _safe_int(stats.get("share_count", 0))
            plays = _safe_int(stats.get("play_count", 0))
        else:
            likes = comments = shares = plays = 0

        aweme_id = obj.get("aweme_id", "")
        url = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""

        video_info = obj.get("video", {})
        duration = 0
        if isinstance(video_info, dict):
            duration = _safe_int(video_info.get("duration", 0))

        return {
            "title": title,
            "author": author,
            "url": url,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "plays": plays,
            "duration_ms": duration,
        }
    except Exception:
        return None


def try_extract_from_dom(page):
    """从 DOM 元素中提取视频信息"""
    videos = []
    try:
        selectors = [
            'div[data-e2e="scroll-list"] > ul > li',
            'ul[data-e2e="scroll-list"] > li',
            '[class*="search-result-card"]',
            '[class*="video-card"]',
        ]

        for selector in selectors:
            elements = page.query_selector_all(selector)
            if elements:
                print(f"  📦 DOM [{selector}] => {len(elements)} 个元素")
                for el in elements:
                    vid = _extract_from_element(el)
                    if vid:
                        videos.append(vid)
                if videos:
                    break

    except Exception as e:
        print(f"  ⚠️ DOM 提取失败: {e}")

    return videos


def _extract_from_element(el):
    """从单个 DOM 元素中提取视频信息"""
    try:
        # 先取整个元素的文本，如果太短说明是空占位符
        full_text = el.inner_text().strip()
        if len(full_text) < 5:
            return None

        # 解析全文本的各行
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]

        # 提取链接
        url = ""
        link_el = el.query_selector('a[href*="/video/"]')
        if link_el:
            href = link_el.get_attribute("href") or ""
            if href.startswith("//"):
                url = "https:" + href
            elif href.startswith("/"):
                url = "https://www.douyin.com" + href
            else:
                url = href

        # 解析结构化信息
        # 抖音搜索结果卡片的文本通常结构为:
        # 时长(mm:ss) / 点赞数 / 标题 / 作者(@xxx) / 发布时间
        duration_str = ""
        likes = 0
        title = ""
        author = ""
        publish_time = ""

        # 用正则解析各行
        time_pattern = re.compile(r'^(\d{2}:\d{2})$')  # 00:19
        count_pattern = re.compile(r'^[\d.]+[万亿]?$')  # 29.0万, 2383, 2
        author_pattern = re.compile(r'^@(.+)$')  # @蟹煲
        time_ago_pattern = re.compile(r'^\d+[小时天分钟秒]+前$|^\d+天前$|^昨天$|^前天$')  # 22小时前, 1天前

        title_parts = []
        for line in lines:
            if time_pattern.match(line):
                duration_str = line
            elif count_pattern.match(line) and not title_parts:
                # 点赞数通常出现在标题之前
                likes = _parse_count_text(line)
            elif author_pattern.match(line):
                author = author_pattern.match(line).group(1)
            elif time_ago_pattern.match(line):
                publish_time = line
            else:
                # 其他内容视为标题
                title_parts.append(line)

        title = " ".join(title_parts).strip()
        if not title:
            return None

        # 解析时长为毫秒
        duration_ms = 0
        if duration_str:
            parts = duration_str.split(":")
            if len(parts) == 2:
                try:
                    duration_ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
                except ValueError:
                    pass

        return {
            "title": title,
            "author": author,
            "url": url,
            "likes": likes,
            "comments": 0,
            "shares": 0,
            "plays": 0,
            "duration_ms": duration_ms,
            "publish_time": publish_time,
        }
    except Exception:
        return None


def try_extract_from_ssr(page):
    """尝试从 SSR 渲染的 script 标签中提取数据"""
    videos = []
    try:
        scripts = page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('script').forEach(s => {
                    const text = s.textContent || '';
                    if (text.includes('aweme_list') || text.includes('video_list') || text.includes('search_list')) {
                        const match = text.match(/\\{[\\s\\S]*aweme_list[\\s\\S]*\\}/);
                        if (match) {
                            try {
                                results.push(JSON.parse(match[0]));
                            } catch(e) {}
                        }
                    }
                });
                return results;
            }
        """)

        for script_data in (scripts or []):
            vids = _deep_find_videos(script_data)
            videos.extend(vids)

        if videos:
            print(f"  ✅ 从 SSR script 提取到 {len(videos)} 条视频")

    except Exception as e:
        print(f"  ⚠️ SSR 提取失败: {e}")

    return videos


# ============================================================
# 工具函数
# ============================================================

def _safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _parse_count_text(text):
    text = text.strip().replace(",", "")
    if "万" in text:
        try:
            return int(float(text.replace("万", "")) * 10000)
        except ValueError:
            return 0
    if "亿" in text:
        try:
            return int(float(text.replace("亿", "")) * 100000000)
        except ValueError:
            return 0
    try:
        return int(re.sub(r'[^\d]', '', text) or 0)
    except ValueError:
        return 0


def format_count(val):
    if isinstance(val, (int, float)):
        if val >= 100000000:
            return f"{val / 100000000:.1f}亿"
        if val >= 10000:
            return f"{val / 10000:.1f}万"
        return str(int(val))
    return str(val)


def format_duration(ms):
    if not ms:
        return ""
    secs = ms // 1000
    mins = secs // 60
    secs = secs % 60
    if mins > 0:
        return f"{mins}分{secs}秒"
    return f"{secs}秒"


# ============================================================
# 输出格式化
# ============================================================

def output_results(videos, keyword, err, fmt="text"):
    """统一输出结果"""
    search_url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"

    if fmt == "json":
        output = {
            "keyword": keyword,
            "searched_at": datetime.now().isoformat(),
            "search_url": search_url,
            "method": "playwright_browser",
            "total": len(videos) if videos else 0,
            "items": videos or [],
        }
        if err:
            output["error"] = err
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif fmt == "markdown":
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        if videos:
            print(f"# 🎬 「{keyword}」视频搜索结果")
            print(f"\n> 搜索时间：{now}　|　共 {len(videos)} 条")
            print(f"> 🔗 [在抖音查看]({search_url})")
            print()
            print("| # | 视频标题 | 作者 | ❤️ 点赞 | 💬 评论 | ▶️ 播放 | 链接 |")
            print("|:-:|----------|------|---------|---------|---------|------|")
            for i, v in enumerate(videos):
                title = v['title'][:40] + "..." if len(v['title']) > 40 else v['title']
                link = f"[查看]({v['url']})" if v['url'] else "-"
                print(f"| {i+1} | {title} | {v['author']} | {format_count(v['likes'])} | {format_count(v['comments'])} | {format_count(v['plays'])} | {link} |")
        else:
            print(f"⚠️ 未能获取视频数据: {err}")
            print(f"🔗 [手动查看]({search_url})")
    else:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        if videos:
            print(f"🎬 热点视频搜索：「{keyword}」({now})")
            print(f"🔗 {search_url}")
            print(f"{'=' * 60}")
            for i, v in enumerate(videos):
                print(f"\n  {i+1}. {v['title']}")
                if v['author']:
                    print(f"     👤 {v['author']}")
                stats = []
                if v.get('plays'):
                    stats.append(f"▶️ {format_count(v['plays'])}")
                if v.get('likes'):
                    stats.append(f"❤️ {format_count(v['likes'])}")
                if v.get('comments'):
                    stats.append(f"💬 {format_count(v['comments'])}")
                if v.get('shares'):
                    stats.append(f"🔄 {format_count(v['shares'])}")
                if stats:
                    print(f"     {' | '.join(stats)}")
                dur = format_duration(v.get('duration_ms', 0))
                if dur:
                    print(f"     ⏱️ {dur}")
                pt = v.get('publish_time', '')
                if pt:
                    print(f"     🕐 {pt}")
                if v['url']:
                    print(f"     🔗 {v['url']}")
            print(f"\n{'=' * 60}")
            print(f"共 {len(videos)} 条视频")
        else:
            print(f"⚠️ 采集失败: {err}")
            print(f"🔗 手动查看: {search_url}")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="抖音搜索页面采集（Playwright 版）")
    parser.add_argument("keyword", type=str, nargs="?", default=None, help="搜索关键词")
    parser.add_argument("--top", type=int, default=10, help="返回前 N 条")
    parser.add_argument("--sort", choices=["default", "likes", "latest"], default="default", help="排序方式")
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="text", help="输出格式")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--use-chrome", action="store_true", help="⭐ 使用本机 Chrome（推荐，可复用登录态）")
    parser.add_argument("--chrome-profile", type=str, default=None, help="Chrome Profile 名称（默认 'Profile 1'）")
    parser.add_argument("--debug", action="store_true", help="调试模式（截图等）")
    parser.add_argument("--interactive", action="store_true", help="交互模式：遇到验证码时暂停等人工处理")
    parser.add_argument("--login", action="store_true", help="仅登录抖音并保存 cookies")
    args = parser.parse_args()

    if not HAS_PLAYWRIGHT:
        print("❌ 需要安装 playwright：", file=sys.stderr)
        print("   pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(1)

    if args.login:
        success = do_login(headless=False)
        sys.exit(0 if success else 1)

    if not args.keyword:
        print("❌ 请提供搜索关键词（或使用 --login 仅登录）", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    # 选择搜索方式
    if args.use_chrome:
        print("  🌐 模式: 本机 Chrome" + (" (交互模式)" if args.interactive else ""))
        videos, err = search_with_chrome(
            args.keyword,
            top_n=args.top,
            sort=args.sort,
            debug=args.debug,
            profile=args.chrome_profile,
            interactive=args.interactive,
        )
    else:
        mode = "弹窗" if args.no_headless else "无头"
        print(f"  🌐 模式: Playwright ({mode})")
        videos, err = search_douyin_videos(
            args.keyword,
            top_n=args.top,
            sort=args.sort,
            headless=not args.no_headless,
            debug=args.debug,
        )

    output_results(videos, args.keyword, err, args.format)


if __name__ == "__main__":
    main()
