# -*- coding: utf-8 -*-
"""附件下载模块 — 从中标公告详情页提取并下载附件
用法: python download_attachments.py --date 2026-06-22
"""

import os, re, json, time, argparse, hashlib
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone
BJ_TZ = timezone(timedelta(hours=8))  # 北京时间
from bs4 import BeautifulSoup

TIMEOUT = 30
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def http_get(url, referer="", retries=2):
    for i in range(retries + 1):
        try:
            h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
            if referer:
                h["Referer"] = referer
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                if raw and len(raw) > 200:
                    return raw
        except Exception:
            pass
        if i < retries:
            time.sleep(4)
    return None

def http_get_text(url, referer="", retries=4):
    """带频率限制检测的页面获取"""
    for attempt in range(retries + 1):
        raw = http_get(url, referer, 1)
        if raw:
            try:
                text = raw.decode('utf-8')
            except:
                try:
                    text = raw.decode('gbk')
                except:
                    text = raw.decode('utf-8', 'replace')
            if '频繁' in text and len(text) < 3000:
                wait = 5 + attempt * 3
                print(f'    频率限制, 等待{wait}s (尝试{attempt+1}/{retries+1})...')
                time.sleep(wait)
                continue
            return text
        if attempt < retries:
            time.sleep(3)
    return ""

def clean_title_for_dir(title):
    t = re.sub(r'[\\/:*?"<>|]', "_", title or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:80] if t else "untitled"

ATT_KEYWORDS = ["getattach", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".jpg", ".png", "gpx-public-file", "attach", "/file", "download", "oss/download"]

def extract_attachments(html, page_url):
    """从详情页HTML中提取附件链接, 兼容多种格式"""
    attachments = []
    if not html:
        return attachments

    soup = BeautifulSoup(html, "html.parser")

    # 方式1: 标准<a href="...">格式
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not href or not text or len(text) < 2:
            continue
        href_lower = href.lower()
        is_att = any(kw in href_lower for kw in ATT_KEYWORDS)
        text_has_ext = bool(re.search(r'\.(pdf|doc|docx|xls|xlsx|zip|rar|jpg|jpeg|png)', text, re.I))
        if is_att or text_has_ext:
            if not any(skip in text for skip in ["返回", "首页", "上一页", "下一页", "更多"]):
                attachments.append({"name": text, "url": _abs_url(href, page_url)})

    # 方式2: CCGP无引号格式 <a href=xxx ignore=1>文件名</a>
    if not attachments:
        for m in re.finditer(r'<a\s+href=(\S+?)(?:\s+[^>]*)?>([^<]+)</a>', html):
            href, text = m.group(1), m.group(2).strip()
            href_lower = href.lower()
            is_att = any(kw in href_lower for kw in ATT_KEYWORDS)
            text_has_ext = bool(re.search(r'\.(pdf|doc|docx|xls|xlsx|zip|rar)', text, re.I))
            if is_att or text_has_ext:
                if not any(skip in text for skip in ["返回", "首页", "上一页", "下一页"]):
                    attachments.append({"name": text, "url": _abs_url(href, page_url)})

    # 方式3: 在"相关附件"或"附件"文本后面的所有<a>标签
    if not attachments:
        for keyword in ["相关附件", "附件下载", "附件信息", "附件"]:
            idx = html.find(keyword)
            if idx >= 0:
                snippet = html[idx:idx+5000]
                snippet_soup = BeautifulSoup(snippet, "html.parser")
                for a in snippet_soup.find_all("a", href=True):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)
                    if href and text and len(text) > 2 and href != "#":
                        if not any(skip in text for skip in ["返回", "首页"]):
                            attachments.append({"name": text, "url": _abs_url(href, page_url)})
                if attachments:
                    break

    # 去重
    seen = set()
    unique = []
    for att in attachments:
        if att["url"] not in seen and att["name"]:
            seen.add(att["url"])
            unique.append(att)
    return unique

def _abs_url(href, base):
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "http:" + href
    if href.startswith("/"):
        p = urllib.parse.urlparse(base)
        return f"{p.scheme}://{p.netloc}{href}"
    return urllib.parse.urljoin(base, href)

def download_file(url, save_path, referer=""):
    raw = http_get(url, referer)
    if not raw or len(raw) < 100:
        return False
    with open(save_path, "wb") as f:
        f.write(raw)
    return True

def get_file_extension(url, name=""):
    for source in [name, url]:
        m = re.search(r'(\.(?:pdf|doc|docx|xls|xlsx|zip|rar|jpg|jpeg|png))', source, re.I)
        if m:
            return m.group(1).lower()
    if "getattach" in url.lower() or "gpx-public-file" in url.lower() or "oss/download" in url.lower():
        return ".pdf"
    return ".bin"

def run(date_str=None):
    if not date_str:
        date_str = datetime.now(BJ_TZ).strftime("%Y-%m-%d")

    out_dir = os.path.join('output', date_str)
    json_path = os.path.join(out_dir, "文物数字化.json")

    if not os.path.exists(json_path):
        jsons = [f for f in os.listdir(out_dir) if f.endswith(".json") and f != "attachments.json" and "summaries" not in f] if os.path.isdir(out_dir) else []
        if jsons:
            json_path = os.path.join(out_dir, jsons[0])
        else:
            print(f"[!] 未找到JSON: {json_path}")
            return

    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"[*] 读取 {len(items)} 条公告, 开始下载附件...")
    manifest = []

    for i, item in enumerate(items, 1):
        url = item.get("url") or item.get("原文链接", "")
        title = item.get("title") or item.get("标题", f"item_{i}")
        dir_name = clean_title_for_dir(title)
        item_out = os.path.join(out_dir, dir_name)
        os.makedirs(item_out, exist_ok=True)

        print(f"  [{i}/{len(items)}] {title[:50]}...")
        time.sleep(1.5)  # 请求间隔, 避免CCGP频率限制

        html = http_get_text(url, retries=3)
        if not html:
            print(f"    跳过(页面获取失败)")
            continue

        attachments = extract_attachments(html, url)
        if not attachments:
            print(f"    无附件")
            continue

        print(f"    发现 {len(attachments)} 个附件")
        for att in attachments:
            ext = get_file_extension(att["url"], att["name"])
            safe_name = att["name"]
            if not safe_name.endswith(ext):
                safe_name = re.sub(r'\.[^.]+$', '', safe_name) + ext
            safe_name = re.sub(r'[\\/:*?"<>|]', '_', safe_name)
            save_path = os.path.join(item_out, safe_name)

            if os.path.exists(save_path):
                print(f"      [跳过] {safe_name} 已存在")
                continue

            ok = download_file(att["url"], save_path, referer=url)
            if ok:
                try:
                    size_kb = os.path.getsize(save_path) / 1024
                except:
                    size_kb = 0
                manifest.append({
                    "标题": title, "附件名": safe_name,
                    "附件URL": att["url"], "本地路径": save_path,
                    "大小KB": round(size_kb, 1)
                })
                print(f"      [OK] {safe_name} ({size_kb:.1f}KB)")
            else:
                print(f"      [FAIL] {safe_name}")

    manifest_path = os.path.join(out_dir, "attachments.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    total_files = len(manifest)
    print(f"\n[*] 附件下载完成: {total_files}个文件, 清单保存至 attachments.json")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="附件下载")
    p.add_argument('--date', default=None, help='日期 YYYY-MM-DD')
    a = p.parse_args()
    run(a.date)
