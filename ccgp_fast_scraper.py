#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
纯代码解析版多站并发爬虫 v4 — 无AI, 高效精确

v4改进:
  1. 日期过滤: 精确近7天, 搜索后在代码中二次过滤
  2. CCGP解析: 公告正文(div.vF_detail_content)优先, 支持纯文本+表格两种格式
  3. GGZY解析: 独立逻辑, 兼容"中标单位:XXX,中标价格"和"供应商名称：XXX"两种格式
  4. 废标公告: 保留但在公告类型列标注"废标公告"
  5. 删除冗余, 纯代码无AI
"""

import re, csv, json, time, threading, hashlib, argparse, random
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import os
try:
    from keywords import KEYWORDS_20, KEYWORDS_STR, DOMAIN_FILTER
except ImportError:
    KEYWORDS_20 = ["文物数字化"]
    KEYWORDS_STR = "文物数字化"
    DOMAIN_FILTER = ["文物", "博物馆", "文化遗产"]

# ═════ Config ═════
TIMEOUT = 20
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]
BID_KEYWORDS = ["中标", "成交", "结果公告", "更正"]
ABORT_KEYWORDS = ["废标", "终止", "有效供应商不足三家", "流标", "取消"]

_lock = threading.Lock()
_stats = {}

def log(*a, **kw):
    with _lock:
        print(*a, **kw, flush=True)

def get_ua():
    return random.choice(UA_LIST)

def http_get(url, referer="", retries=3, delay=2):
    for i in range(retries):
        try:
            h = {"User-Agent": get_ua(), "Accept": "text/html,*/*;q=0.8",
                 "Accept-Language": "zh-CN,zh;q=0.9"}
            if referer:
                h["Referer"] = referer
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                for enc in ["utf-8", "gbk", "gb2312"]:
                    try:
                        return raw.decode(enc)
                    except:
                        continue
                return raw.decode("utf-8", "replace")
        except Exception:
            if i < retries - 1:
                time.sleep(delay * (i + 1))
    return ""

def http_post_form(url, data, referer="", retries=3):
    for i in range(retries):
        try:
            h = {"User-Agent": get_ua(), "Accept": "application/json, text/plain, */*",
                 "Content-Type": "application/x-www-form-urlencoded"}
            if referer:
                h["Referer"] = referer
            body = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=h, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i < retries - 1:
                time.sleep(2 * (i + 1))
    return ""

# ═════ Item ═════
class Item:
    __slots__ = ("title","url","date","bid_type","region","buyer","agent",
                 "supplier","supplier_addr","amount","source")

    def __init__(self):
        for f in self.__slots__:
            setattr(self, f, "")

    def fingerprint(self):
        t = self.title
        t = re.sub(r"[\s的及关于]", "", t)
        t = re.sub(r"[（(]", "", t)
        t = re.sub(r"[）)]", "", t)
        t = re.sub(r"中标|成交|结果|公告|公示|候选人", "", t)
        t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
        return hashlib.md5(t[:60].encode()).hexdigest()

    def to_dict(self):
        return {
            "标题": self.title, "原文链接": self.url, "发布时间": self.date,
            "公告类型": self.bid_type, "地区": self.region, "采购人": self.buyer,
            "代理机构": self.agent, "供应商": self.supplier,
            "供应商地址": self.supplier_addr, "中标金额(万)": self.amount,
            "数据来源": self.source,
        }

# ═════ Helpers ═════
def norm_date(s):
    if not s:
        return ""
    m = re.search(r"(\d{4})[/.年-](\d{1,2})[/.月-](\d{1,2})", str(s))
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}/{int(m.group(3))}"
    return str(s)[:20]

def parse_date_obj(s):
    """解析日期字符串为datetime对象, 失败返回None"""
    if not s:
        return None
    m = re.search(r"(\d{4})[/.年-](\d{1,2})[/.月-](\d{1,2})", str(s))
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except:
            pass
    return None

def norm_amount(s):
    if not s:
        return ""
    s = str(s).replace(",", "").replace(" ", "").replace("￥", "").strip()
    m = re.search(r"([\d.]+)\s*万", s)
    if m:
        v = float(m.group(1))
        return f"{v:.2f}" if v < 10000 else f"{v/10000:.2f}"
    m = re.search(r"([\d.]+)\s*元?", s)
    if m:
        v = float(m.group(1))
        return f"{v/10000:.2f}" if v >= 10000 else f"{v:.2f}"
    return ""

def clean_supplier(s):
    return re.sub(r"[（(].*$", "", s).strip()

def is_within_days(date_str, days=7):
    """检查日期是否在近N天内"""
    d = parse_date_obj(date_str)
    if not d:
        return True  # 无法解析的保留
    now = datetime.now()
    return (now - d).days <= days

# ═════ CCGP详情解析 — 正文优先 ═════
def parse_ccgp_detail(html, url=""):
    result = {}
    if not html or ("频繁" in html and len(html) < 3000):
        return result

    soup = BeautifulSoup(html, "html.parser")

    # 标题
    for tag in ["h2", "h3", "h1"]:
        h = soup.find(tag)
        if h and len(h.get_text(strip=True)) > 5:
            result["title"] = h.get_text(strip=True)
            break

    # ▶ 1. 先从公告正文(div.vF_detail_content)提取 — 正文更全面
    dc = soup.find("div", class_="vF_detail_content")
    if not dc:
        dc = soup.find("div", class_="vF_detail_main_content")
    if dc:
        text = dc.get_text(" ", strip=True)

        # 供应商名称 (纯文本格式: "供应商名称：XXX")
        m = re.search(r"供应商名称[：:]\s*([^\s,，。；;（(]{4,50})", text)
        if m:
            result["supplier"] = clean_supplier(m.group(1).strip())

        # 供应商地址 (纯文本: "供应商地址：XXX")
        m = re.search(r"供应商地址[：:]\s*([^\s,，。；;]{4,80})", text)
        if m:
            result["supplier_addr"] = m.group(1).strip()

        # 中标(成交)金额 (纯文本: "中标（成交）金额：1485000.00元")
        m = re.search(r"中标[（(]成交[)）]金额[：:]\s*￥?\s*([\d,.]+)\s*元?", text)
        if m:
            result["amount"] = norm_amount(m.group(0))
        if not result.get("amount"):
            m = re.search(r"总中标金额[：:]*\s*￥?\s*([\d.]+)\s*万", text)
            if m:
                result["amount"] = f"{float(m.group(1)):.2f}"

        # 如果正文纯文本没找到供应商, 从正文表格中找
        if not result.get("supplier"):
            for t in dc.find_all("table"):
                cls = " ".join(t.get("class", []))
                ths = [th.get_text(strip=True) for th in t.find_all("th")]
                # 找含"供应商名称"表头的表
                if any("供应商名称" in th for th in ths) or "winningSupplier" in cls.lower() or "中标" in cls or "成交" in cls:
                    header_idx = {}
                    for i, th in enumerate(t.find_all("th")):
                        header_idx[th.get_text(strip=True)] = i
                    for row in t.find_all("tr"):
                        cells = row.find_all("td")
                        if len(cells) < 2:
                            continue
                        for i, c in enumerate(cells):
                            txt = c.get_text(strip=True)
                            cls_c = " ".join(c.get("class", []))
                            hdr = ths[i] if i < len(ths) else ""
                            if ("winningSupplierName" in cls_c or "供应商名称" in hdr) and "地址" not in hdr:
                                if txt and len(txt) > 2 and "名称" not in txt:
                                    result["supplier"] = clean_supplier(txt)
                            elif "winningSupplierAddr" in cls_c or "供应商地址" in hdr:
                                if txt and len(txt) > 2 and "地址" not in txt[:3]:
                                    result["supplier_addr"] = txt
                            elif ("summaryPrice" in cls_c or "金额" in hdr) and not result.get("amount") and "元" in txt:
                                if not result.get("amount"):
                                    result["amount"] = norm_amount(txt)
                        if result.get("supplier"):
                            break
                    if result.get("supplier"):
                        break

    # ▶ 2. 再从公告概要(div.table)补充正文没有的字段
    tbl = soup.find("div", class_="table") or soup.find("table", bgcolor="#bfbfbf")
    if tbl:
        for td in tbl.find_all("td", class_="title"):
            label = td.get_text(strip=True)
            nxt = td.find_next_sibling("td")
            if not nxt:
                tr = td.find_parent("tr")
                if tr:
                    tds = tr.find_all("td", recursive=False)
                    for j, t2 in enumerate(tds):
                        if t2 is td and j + 1 < len(tds):
                            nxt = tds[j + 1]
                            break
            if nxt:
                val = nxt.get_text(strip=True)
                if label in ("采购单位", "采购人") and not result.get("buyer"):
                    result["buyer"] = val
                elif label == "代理机构名称" and not result.get("agent"):
                    result["agent"] = val
                elif label == "行政区域" and not result.get("region"):
                    result["region"] = val
                elif label == "公告时间" and not result.get("date"):
                    result["date"] = norm_date(val)
                elif label == "总中标金额" and not result.get("amount"):
                    result["amount"] = norm_amount(val)

    # ▶ 3. 从正文第九部分(联系人信息)补充采购人/代理机构
    if not result.get("buyer") or not result.get("agent"):
        full_text = soup.get_text(" ", strip=True)
        m = re.search(r"采购人信息\s*名?\s*称[：:]\s*([^\s地]{3,30})", full_text)
        if m and not result.get("buyer"):
            result["buyer"] = m.group(1).strip()
        m = re.search(r"采购代理机构信息\s*名?\s*称[：:]\s*([^\s地]{3,40})", full_text)
        if m and not result.get("agent"):
            result["agent"] = m.group(1).strip()

    # ▶ 4. 公告类型 + 废标检测
    title = result.get("title", "")
    full_text = soup.get_text(" ", strip=True)
    is_abort = any(k in title or k in full_text[:1000] for k in ABORT_KEYWORDS)
    if is_abort:
        result["bid_type"] = "废标公告"
    else:
        crumb = soup.find("div", class_="main")
        if crumb:
            bc = crumb.get_text(" ", strip=True)
            for kw in ["中标公告", "成交公告", "结果公告"]:
                if kw in bc:
                    result["bid_type"] = kw
                    break

    return result

# ═════ GGZY详情解析 — 独立双格式 ═════
def parse_ggzy_detail(html, url=""):
    result = {}
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")
    detail = soup.find("div", class_="detail")
    text = detail.get_text(" ", strip=True) if detail else soup.get_text(" ", strip=True)

    if len(text) < 200:
        return result

    title = ""
    h4 = soup.find("h4", class_="h4_o")
    if h4:
        title = h4.get_text(strip=True)
        result["title"] = title

    # ▶ 格式1: 青海类 — "中标单位:XXX,中标价格:1150000"
    m = re.search(r"中标单位[：:]\s*([^,，;；\s（(]{3,40})", text)
    if m:
        result["supplier"] = clean_supplier(m.group(1).strip())

    # ▶ 格式2: 山东/辽宁类 — "供应商名称：XXX 供应商地址：XXX 中标（成交）金额：XXX"
    if not result.get("supplier"):
        m = re.search(r"供应商名称[：:]\s*([^\s,，。；;（(]{4,50})", text)
        if m:
            result["supplier"] = clean_supplier(m.group(1).strip())

    if not result.get("supplier_addr"):
        m = re.search(r"供应商地址[：:]\s*([^\s,，。；;]{4,80})", text)
        if m:
            result["supplier_addr"] = m.group(1).strip()

    # 金额: 先找"成交总金额"(青海), 再找"中标（成交）金额"(山东/辽宁)
    m = re.search(r"成交总金额[：:\s]*￥?\s*([\d,.]+)\s*元?", text)
    if m:
        result["amount"] = norm_amount(m.group(0))
    if not result.get("amount"):
        m = re.search(r"中标[（(]成交[)）]金额[：:]\s*￥?\s*([\d,.]+)\s*元?", text)
        if m:
            result["amount"] = norm_amount(m.group(0))
    if not result.get("amount"):
        m = re.search(r"中标价格[：:\s]*([\d,.]+)", text)
        if m:
            v = float(m.group(1).replace(",",""))
            result["amount"] = f"{v/10000:.2f}" if v >= 10000 else f"{v:.2f}"
    if not result.get("amount"):
        m = re.search(r"(?:中标|成交)金额[：:\s]*￥?\s*([\d,.]+)\s*万?", text)
        if m:
            result["amount"] = norm_amount(m.group(0))

    # 采购单位 (GGZY格式: "采购单位：XXX 联系人")
    m = re.search(r"采购单位[：:]\s*([^联系人\s,，。；;]{3,30})", text)
    if m:
        result["buyer"] = m.group(1).strip()

    # 代理机构
    m = re.search(r"采购代理机构[：:]\s*([^联系人\s,，。；;]{3,40})", text)
    if m:
        result["agent"] = m.group(1).strip()

    # 日期
    m = re.search(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        result["date"] = norm_date(m.group(1))

    # 废标检测
    is_abort = any(k in text[:1000] for k in ABORT_KEYWORDS)
    if is_abort:
        result["bid_type"] = "废标公告"

    return result

# ═════ CCGP Scraper ═════
class CcgpScraper:
    NAME = "中国政府采购网"
    BASE = "https://search.ccgp.gov.cn/bxsearch"
    REF = "https://www.ccgp.gov.cn/"

    def search(self, kw, days=7):
        end_date = datetime.now() - timedelta(days=1)
        start_date = end_date - timedelta(days=days-1) if days > 1 else end_date
        params = {
            "searchtype": "2", "bidType": "0", "kw": kw,
            "timeType": "6",
            "start_time": start_date.strftime("%Y:%m:%d"),
            "end_time": end_date.strftime("%Y:%m:%d"),
            "page": "1",
        }
        url = self.BASE + "?" + urllib.parse.urlencode(params)

        html = ""
        for attempt in range(4):
            html = http_get(url, referer=self.REF, retries=1, delay=1)
            if not html or ("频繁" in html and len(html) < 3000):
                wait = 8 + attempt * 5
                log(f"  [CCGP] 频率限制, 等待{wait}s (尝试{attempt+1}/4)...")
                time.sleep(wait)
                continue
            break

        if not html or "频繁" in html:
            log("  [CCGP] 搜索失败(频率限制)")
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
                href = "https:" + href if href.startswith("//") else self.REF.rstrip("/") + "/" + href.lstrip("/")
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            item = Item()
            item.title = title
            item.url = href
            item.source = self.NAME

            text = li.get_text(" ", strip=True)
            m = re.search(r"(\d{4})[/.年-](\d{1,2})[/.月-](\d{1,2})", text)
            if m:
                item.date = norm_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
            # 检查日期是否在范围内
            if not is_within_days(item.date, days):
                continue
            for kw in BID_KEYWORDS:
                if kw in title or kw in text:
                    item.bid_type = kw + "公告" if not kw.endswith("公告") else kw
                    break
            items.append(item)
        return items

    def run(self, kw, days=7):
        log("  [CCGP] 搜索中...")
        items = self.search(kw, days)
        if not items:
            return []

        log(f"  [CCGP] 搜索到{len(items)}条, 爬取详情...")
        for i, item in enumerate(items, 1):
            html = ""
            for attempt in range(3):
                html = http_get(item.url, referer=self.REF, retries=1, delay=1)
                if html and not ("频繁" in html and len(html) < 3000):
                    break
                time.sleep(5)
            if html:
                d = parse_ccgp_detail(html, item.url)
                for k in ("buyer", "agent", "supplier", "supplier_addr", "amount", "date", "region", "bid_type"):
                    if d.get(k):
                        setattr(item, k, d[k])
            status = f"采购人:{item.buyer[:8] if item.buyer else '-'} 供应商:{item.supplier[:8] if item.supplier else '-'} 金额:{item.amount if item.amount else '-'}"
            log(f"    [{i}/{len(items)}] {item.title[:38]}... | {status}")
            time.sleep(0.8)

        with _lock:
            _stats[self.NAME] = len(items)
        return items

# ═════ GGZY Scraper ═════
class GgzyScraper:
    NAME = "全国公共资源交易平台"
    API = "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList"
    REF = "https://www.ggzy.gov.cn/deal/dealList.html"

    def search(self, kw, page=1):
        """DEAL_TIME=05搜索较宽范围, 后续代码过滤近7天"""
        resp = http_post_form(self.API, {
            "FINDTXT": kw,
            "DEAL_TIME": "05",
            "pageNum": page,
            "pageSize": 20,
        }, referer=self.REF, retries=3)

        if not resp:
            return [], 0

        items = []
        try:
            jdata = json.loads(resp)
            records = jdata.get("data", {}).get("records", [])
            total = jdata.get("data", {}).get("total", 0)
            for rec in records:
                item = Item()
                item.title = rec.get("title", "")
                url = rec.get("url", "")
                if url and not url.startswith("http"):
                    url = "https://www.ggzy.gov.cn" + url
                item.url = url.replace("/a/", "/b/") if url else ""
                item.date = norm_date(rec.get("publishTime", ""))
                item.region = rec.get("provinceText", "") or rec.get("cityText", "")

                itype = rec.get("informationTypeText", "")
                if "中标" in itype:
                    item.bid_type = "中标公告"
                elif "成交" in itype:
                    item.bid_type = "成交公告"
                elif "结果" in itype:
                    item.bid_type = "结果公告"
                else:
                    item.bid_type = itype or "其他"

                item.source = self.NAME
                if item.title:
                    items.append(item)
        except json.JSONDecodeError:
            pass
        return items, total

    def run(self, kw, days=7):
        all_items = []
        page = 1
        while page <= 3:
            log(f"  [GGZY] 搜索第{page}页...")
            items, total = self.search(kw, page)
            if not items:
                break
            log(f"  [GGZY] 第{page}页: {len(items)}条 (总计{total}条)")
            all_items.extend(items)
            if len(items) < 20:
                break
            page += 1
            time.sleep(0.5)

        # ▶ 日期过滤: 只保留近N天
        before = len(all_items)
        all_items = [it for it in all_items if is_within_days(it.date, days)]
        log(f"  [GGZY] 日期过滤: {before}条 → {len(all_items)}条(近{days}天)")

        # 先去重
        seen = set()
        unique = []
        for it in all_items:
            fp = it.fingerprint()
            if fp not in seen:
                seen.add(fp)
                unique.append(it)

        # 只对去重后的中标/成交公告爬详情页
        bid_items = [it for it in unique if any(k in it.bid_type for k in BID_KEYWORDS)]
        log(f"  [GGZY] 去重后{len(unique)}条, 中标/成交{len(bid_items)}条, 爬详情...")

        for i, item in enumerate(bid_items, 1):
            if not item.url:
                continue
            html = http_get(item.url, referer="https://www.ggzy.gov.cn/", retries=2, delay=1)
            if html:
                d = parse_ggzy_detail(html, item.url)
                for k in ("buyer", "agent", "supplier", "supplier_addr", "amount", "date", "bid_type"):
                    if d.get(k):
                        setattr(item, k, d[k])
            status = f"采购人:{item.buyer[:8] if item.buyer else '-'} 供应商:{item.supplier[:8] if item.supplier else '-'} 金额:{item.amount if item.amount else '-'}"
            log(f"    [{i}/{len(bid_items)}] {item.title[:38]}... | {status}")
            time.sleep(0.5)

        with _lock:
            _stats[self.NAME] = len(all_items)
        return all_items

# ═════ Scheduler ═════
class Scheduler:
    def __init__(s, kw, days=7):
        s.kw = kw
        s.days = days
        s.scrapers = [CcgpScraper()]  # GgzyScraper() 已注释 — CCGP含附件,GGZY不含

    def run(s):
        results = []
        with ThreadPoolExecutor(max_workers=1) as pool:  # 单站不需并发
            futs = {pool.submit(sc.run, s.kw, s.days): sc.NAME for sc in s.scrapers}
            for f in as_completed(futs):
                name = futs[f]
                try:
                    r = f.result()
                    results.extend(r)
                    log(f"  [OK] {name}: {len(r)}条")
                except Exception as e:
                    log(f"  [ERR] {name}: {e}")
        return results

# ═════ Pipeline ═════
class Pipe:
    @staticmethod
    def filter(items):
          out = []
          for it in items:
              if it.bid_type and any(k in it.bid_type for k in BID_KEYWORDS):
                  out.append(it)
              elif it.bid_type == "废标公告":
                  out.append(it)
              elif any(k in it.title for k in BID_KEYWORDS):
                  out.append(it)
          return out

    @staticmethod
    def dedup(items):
          fp_map = {}
          unique = []
          for it in items:
              fp = it.fingerprint()
              if fp not in fp_map:
                  fp_map[fp] = len(unique)
                  unique.append(it)
              else:
                  existing = unique[fp_map[fp]]
                  for k in Item.__slots__:
                      if not getattr(existing, k) and getattr(it, k):
                          setattr(existing, k, getattr(it, k))
                  for k in ("buyer","agent","supplier","supplier_addr","amount","date","region","bid_type"):
                      if not getattr(existing, k) and getattr(it, k):
                          setattr(existing, k, getattr(it, k))
          return unique

    @staticmethod
    def domain_filter(items):
        """域名筛选: 标题须含文物/博物馆/文化遗产等关键词"""
        if not DOMAIN_FILTER:
            return items
        return [it for it in items if any(k in it.title for k in DOMAIN_FILTER)]

    @staticmethod
    def sort(items):
        return sorted(items, key=lambda x: x.date or "0", reverse=True)

    @staticmethod
    def csv(items, path):
        fields = ["标题","原文链接","发布时间","公告类型","地区","采购人","代理机构",
                  "供应商","供应商地址","中标金额(万)","数据来源"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows([it.to_dict() for it in items])

    @staticmethod
    def json(items, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([it.to_dict() for it in items], f, ensure_ascii=False, indent=2)

# ═════ CLI ═════

def main():
    p = argparse.ArgumentParser(description="纯代码解析版多站爬虫 v5 — 多关键词+多站并发")
    p.add_argument("-k", "--keyword", default="")
    p.add_argument("-d", "--days", type=int, default=1)
    p.add_argument("-o", "--output", default="")
    p.add_argument("--all-types", action="store_true")
    a = p.parse_args()

    # 解析关键词: 逗号分隔 → 列表; 留空则用KEYWORDS_20
    if a.keyword.strip():
        keywords = [kw.strip() for kw in a.keyword.split(",") if kw.strip()]
    else:
        keywords = KEYWORDS_20

    kw_clean = re.sub(r'[\\\/:*?"<>|]', "_", keywords[0])[:20]

    # 输出目录: output/YYYY-MM-DD/
    today_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = os.path.join("output", today_str)
    os.makedirs(out_dir, exist_ok=True)
    prefix = a.output or os.path.join(out_dir, kw_clean)

    print("=" * 65)
    print("  纯代码解析版 v5 — 多关键词+多站并发, 无AI")
    print("=" * 65)
    print(f"  关键词: {', '.join(keywords[:5])}{'...' if len(keywords)>5 else ''} ({len(keywords)}个)")
    print(f"  时间: 近{a.days}天  |  日期: {today_str}")
    print(f"  数据源: 中国政府采购网 + 全国公共资源交易平台")
    print(f"  解析方式: 纯代码(BeautifulSoup+正则), 无AI, 无token")
    print(f"  输出目录: {out_dir}")
    print("=" * 65 + "\n")

    t0 = time.time()
    all_raw = []
    for ki, kw in enumerate(keywords, 1):
        print(f"\n{'─'*50}")
        print(f"  [{ki}/{len(keywords)}] 关键词: {kw}")
        print(f"{'─'*50}")
        sch = Scheduler(kw, a.days)
        raw = sch.run()
        all_raw.extend(raw)
        if ki < len(keywords):
            time.sleep(2)

    t1 = time.time()

    print(f"\n{'='*65}")
    print(f"  全部关键词搜索完成({t1-t0:.0f}s), 原始{len(all_raw)}条")
    print("[*] 去重(合并式)...")
    unique = Pipe.dedup(all_raw)
    print(f"[*] 去重后{len(unique)}条")

    if not a.all_types:
        print("[*] 域名筛选(标题须含文物/博物馆等)...")
        domain_filtered = Pipe.domain_filter(unique)
        print(f"[*] 域名筛选后{len(domain_filtered)}条")
        print("[*] 筛选中标/成交/废标/更正公告...")
        filtered = Pipe.filter(domain_filtered)
        print(f"[*] 筛选后{len(filtered)}条")
    else:
        filtered = unique

    if not filtered:
        print("\n[!] 无结果")
        return

    final = Pipe.sort(filtered)
    csv_path = f"{prefix}.csv"
    json_path = f"{prefix}.json"
    Pipe.csv(final, csv_path)
    Pipe.json(final, json_path)

    total = len(final)
    print(f"\n{'='*65}")
    print(f"  结果: {total}条 (原始{len(all_raw)} → 去重{len(unique)} → 筛选{len(filtered)})")
    print(f"  耗时: {t1-t0:.0f}s")
    print(f"{'='*65}")

    for name, cnt in sorted(_stats.items(), key=lambda x: -x[1]):
        print(f"  {name}: {cnt}条")

    fill = {
        "采购人": sum(1 for r in final if r.buyer),
        "代理机构": sum(1 for r in final if r.agent),
        "供应商": sum(1 for r in final if r.supplier),
        "供应商地址": sum(1 for r in final if r.supplier_addr),
        "中标金额": sum(1 for r in final if r.amount),
    }
    print("\n  字段填充率:")
    for k, v in fill.items():
        print(f"    {k}: {v}/{total} ({v/total*100:.0f}%)")

    for i, r in enumerate(final[:8], 1):
        print(f"\n  {i}. {r.title[:50]}")
        print(f"     {r.date} | {r.region} | {r.bid_type}")
        b = r.buyer[:18] if r.buyer else "N/A"
        ag = r.agent[:18] if r.agent else "N/A"
        sp = r.supplier[:18] if r.supplier else "N/A"
        print(f"     采购人:{b} | 代理:{ag}")
        print(f"     供应商:{sp} | 金额:{r.amount if r.amount else 'N/A'}万 | 来源:{r.source}")

    print(f"\n  CSV: {csv_path}")
    print(f"  JSON: {json_path}")
    print(f"  总耗时: {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
