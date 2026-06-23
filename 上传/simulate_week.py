# -*- coding: utf-8 -*-
"""7天周期模拟 v5: 数据存output/YYYY-MM-DD/, 与正式流程相同路径, AI总结+飞书推送无缝兼容"""
import os, sys, json, time, csv, re, urllib.request, urllib.parse, shutil
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup
from ccgp_fast_scraper import Pipe, Item, BID_KEYWORDS, http_get, parse_ccgp_detail, norm_date
from keywords import KEYWORDS_20, DOMAIN_FILTER

START = datetime(2026, 6, 17)
END   = datetime(2026, 6, 23)
WAIT  = 60

os.environ["SILICONFLOW_API_KEY"] = "sk-vpfuqehzyivwtlturuhdfwndrgurgcelvqbvgdpyaxugtxrl"
os.environ["FEISHU_APP_ID"] = "cli_aabba8e342781bde"
os.environ["FEISHU_APP_SECRET"] = "UYrGGoD6km6ba47bPDiCLgbJqAd2udiA"
os.environ["FEISHU_CHAT_ID"] = "oc_30f03e7773054a3974c05b461d14370b"

def log(*a):
    print(*a, flush=True)


def search_exact_date(kw, target_date):
    base = "https://search.ccgp.gov.cn/bxsearch"
    ref  = "https://www.ccgp.gov.cn/"
    ds   = target_date.strftime("%Y:%m:%d")
    params = {
        "searchtype": "2", "page_index": "1", "bidSort": "0",
        "buyerName": "", "projectId": "", "pinMu": "0",
        "bidType": "0", "dbselect": "bidx", "kw": kw,
        "start_time": ds, "end_time": ds, "timeType": "6",
        "displayZone": "", "zoneId": "", "pppStatus": "0", "agentName": "",
    }
    url = base + "?" + urllib.parse.urlencode(params)

    html = ""
    for attempt in range(4):
        html = http_get(url, referer=ref, retries=1, delay=1)
        if not html or ("频繁" in html and len(html) < 3000):
            wt = 8 + attempt * 5
            log(f"    频率限制,等待{wt}s (尝试{attempt+1}/4)")
            time.sleep(wt)
            continue
        break

    if not html or "频繁" in html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("ul li"):
        a = li.find("a")
        if not a:
            continue
        href = a.get("href", "")
        if "ccgp.gov.cn" not in href:
            continue
        if not href.startswith("http"):
            href = "https:" + href if href.startswith("//") else ref.rstrip("/") + "/" + href.lstrip("/")
        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        item = Item()
        item.title = title
        item.url = href
        item.source = "中国政府采购网"

        text = li.get_text(" ", strip=True)
        m = re.search(r"(\d{4})[/.年-](\d{1,2})[/.月-](\d{1,2})", text)
        if m:
            item.date = norm_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")

        for kw_val in BID_KEYWORDS:
            if kw_val in title or kw_val in text:
                item.bid_type = kw_val + "公告" if not kw_val.endswith("公告") else kw_val
                break
        items.append(item)
    return items


def process_day(date_str, is_day7):
    ds = datetime.strptime(date_str, "%Y-%m-%d")
    day_dir = os.path.join("output", date_str)
    ai_dir  = os.path.join(day_dir, "AI总结")
    os.makedirs(ai_dir, exist_ok=True)

    all_items = []
    for ki, kw in enumerate(KEYWORDS_20, 1):
        results = search_exact_date(kw, ds)
        if results:
            all_items.extend(results)
        if ki % 5 == 0:
            log(f"    [{ki}/{len(KEYWORDS_20)}] {kw}: 累计{len(all_items)}条")
        time.sleep(0.2)

    log(f"  原始: {len(all_items)}条")
    unique = Pipe.dedup(all_items)
    log(f"  去重: {len(unique)}条")
    domain = [it for it in unique if any(dk in it.title for dk in DOMAIN_FILTER)]
    log(f"  域名: {len(domain)}条")
    filtered = Pipe.filter(domain)
    log(f"  中标/成交/废标/更正: {len(filtered)}条")

    if not filtered:
        log(f"  ⚠️ 无中标信息!")

    for i, it in enumerate(filtered, 1):
        html = http_get(it.url, referer="https://www.ccgp.gov.cn/", retries=2, delay=1)
        if html and not ("频繁" in html and len(html) < 3000):
            d = parse_ccgp_detail(html, it.url)
            for k in ("buyer", "agent", "supplier", "supplier_addr", "amount", "date", "region", "bid_type"):
                if d.get(k):
                    setattr(it, k, d[k])
        if i % 5 == 0:
            log(f"    详情 {i}/{len(filtered)}")
        time.sleep(0.3)

    final = Pipe.sort(filtered)
    Pipe.csv(final, os.path.join(day_dir, "文物数字化.csv"))
    Pipe.json(final, os.path.join(day_dir, "文物数字化.json"))

    # AI总结(模板1+2)
    if final:
        log(f"  AI总结(模板1+2)...")
        try:
            import ai_summarize
            ai_summarize.run(date_str=date_str, skip_trend=True)
            log(f"  AI总结完成")
        except Exception as e:
            log(f"  AI总结错误: {str(e)[:80]}")

    # 飞书推送
    log(f"  飞书推送...")
    try:
        import feishu_push
        feishu_push.run(date_str=date_str)
        log(f"  推送完成")
    except Exception as e:
        log(f"  推送错误: {str(e)[:80]}")

    return final


def process_day7(date_str):
    day_dir = os.path.join("output", date_str)
    log("")
    log("=" * 50)
    log("  Day 7 特殊: 合并7天CSV + 行业趋势")
    log("=" * 50)

    days = []
    cur = START
    while cur <= datetime.strptime(date_str, "%Y-%m-%d"):
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    all_rows = []
    header = None
    for fld in days:
        fp = os.path.join("output", fld, "文物数字化.csv")
        if not os.path.exists(fp):
            continue
        with open(fp, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            lines = list(reader)
        if lines:
            if header is None:
                header = lines[0]
            for row in lines[1:]:
                if row and any(c.strip() for c in row):
                    all_rows.append(row)

    if header and all_rows:
        mp = os.path.join(day_dir, "本周文物数字化汇总.csv")
        with open(mp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(all_rows)
        log(f"  合并: {len(all_rows)}条")

    log(f"  模板3行业趋势...")
    try:
        import ai_summarize
        all_s = []
        for fld in days:
            sp = os.path.join("output", fld, "summaries.json")
            if os.path.exists(sp):
                with open(sp, "r", encoding="utf-8") as f:
                    all_s.extend(json.load(f))
        if all_s:
            ai_summarize.trend_radar(all_s, day_dir)
            log(f"  行业趋势完成")
        else:
            log(f"  ⚠️ 无AI总结数据,跳过趋势")
    except Exception as e:
        log(f"  趋势错误: {str(e)[:80]}")


def run():
    days = []
    cur = START
    while cur <= END:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    log("=" * 60)
    log(f"  7天周期: {days[0]} -> {days[-1]}")
    log(f"  流程: CCGP精确日期 -> AI总结(模板1+2) -> 飞书推送 -> 等待{WAIT}s")
    log(f"  数据目录: output/YYYY-MM-DD/ (与正式流程相同)")
    log("=" * 60)

    all_final = {}
    for i, ds in enumerate(days, 1):
        is_day7 = (i == 7)
        log(f"\n{'─'*50}")
        log(f"  Day {i}/7 | {ds} | {'⭐第7天' if is_day7 else '常规日'}")
        log(f"{'─'*50}")

        final = process_day(ds, is_day7)
        log(f"  Day {i} 完成: {len(final)}条")
        all_final[ds] = final

        if is_day7:
            process_day7(ds)

        if i < 7:
            log(f"\n  ⏳ 等待{WAIT}s...")
            time.sleep(WAIT)

    total = sum(len(v) for v in all_final.values())
    log(f"\n{'='*60}")
    log(f"  7天完成! 共 {total} 条")
    for d in days:
        n = len(all_final[d])
        log(f"    {d}: {n}条" + (" ⚠️" if n == 0 else ""))
    log(f"{'='*60}")


if __name__ == "__main__":
    run()
