# -*- coding: utf-8 -*-
"""周状态管理模块 + CLI
用法:
  python week_manager.py add <date> --data-dir week_cache
  python week_manager.py trend <date> --data-dir week_cache
"""

import os, json, csv, shutil, re, urllib.request
from datetime import datetime, timedelta

STATE_FILE = "week_state.json"

def load_state(data_dir="data"):
    path = os.path.join(data_dir, STATE_FILE)
    if not os.path.exists(path):
        return {"week_start": "", "days_collected": 0, "folders": [], "trend_generated": False}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state, data_dir="data"):
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, STATE_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_day7(state):
    return state.get("days_collected", 0) >= 7

def should_reset(state):
    return state.get("trend_generated", False) and state.get("days_collected", 0) >= 7

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def yesterday_str():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

def start_week(date_str=None):
    d = date_str or today_str()
    return {"week_start": d, "days_collected": 0, "folders": [], "trend_generated": False}

def add_day(date_str, data_dir="data"):
    state = load_state(data_dir)
    if should_reset(state):
        _clean_old_week(state, data_dir)
        state = start_week(date_str)
    if not state.get("week_start"):
        state = start_week(date_str)
    folders = state.get("folders", [])
    if date_str not in folders:
        folders.append(date_str)
    state["folders"] = folders
    state["days_collected"] = len(folders)
    state["week_start"] = state["week_start"] or date_str
    save_state(state, data_dir)
    return is_day7(state), state

def mark_trend_done(data_dir="data"):
    state = load_state(data_dir)
    state["trend_generated"] = True
    save_state(state, data_dir)
    return state

def _clean_old_week(state, data_dir="data"):
    output_dir = os.path.join(data_dir, "output")
    if not os.path.isdir(output_dir):
        return
    for folder in state.get("folders", []):
        path = os.path.join(output_dir, folder)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

def merge_weekly_csv(state, data_dir="data"):
    output_dir = os.path.join(data_dir, "output")
    folders = state.get("folders", [])
    if len(folders) < 2:
        return None
    all_rows = []
    header = None
    for folder in folders:
        csv_path = os.path.join(output_dir, folder, "文物数字化.csv")
        if not os.path.exists(csv_path):
            continue
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            lines = list(reader)
        if not lines:
            continue
        if header is None:
            header = lines[0]
        for row in lines[1:]:
            if row and any(c.strip() for c in row):
                all_rows.append(row)
    if not header or not all_rows:
        return None
    last_folder = folders[-1]
    merge_path = os.path.join(output_dir, last_folder, "本周文物数字化汇总.csv")
    with open(merge_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(all_rows)
    return merge_path

def get_zip_name(date_str, day7):
    if day7:
        return f"{date_str}_文物数字化本周汇总.zip"
    return f"{date_str}_文物数字化中标信息.zip"

def get_output_dir(data_dir="data"):
    return os.path.join(data_dir, "output", today_str())

def run_trend(date_str, data_dir="data"):
    """第7天: 合并CSV + AI行业趋势分析(含token截断保护)"""
    state = load_state(data_dir)
    merge_result = merge_weekly_csv(state, data_dir)
    if merge_result:
        print(f"  [OK] 合并CSV: {merge_result}")

    output_dir = os.path.join(data_dir, "output")
    last_folder = state["folders"][-1]
    out_dir = os.path.join(output_dir, last_folder)

    # 收集7天所有summaries
    all_s = []
    for fld in state["folders"]:
        sp = os.path.join(output_dir, fld, "summaries.json")
        if os.path.exists(sp):
            with open(sp, encoding="utf-8") as f:
                all_s.extend(json.load(f))

    if not all_s:
        print("  [!] 无AI总结数据, 跳过行业趋势分析")
        mark_trend_done(data_dir)
        return

    print(f"  [*] 行业趋势分析: {len(all_s)}条公告数据")

    try:
        from keywords import PROMPT_TREND_RADAR
    except ImportError:
        PROMPT_TREND_RADAR = "Analyze the following procurement announcements and generate a trend report in Chinese."

    # Token截断: 最多30条, 每条200字符, 总计4000字符
    all_s = all_s[:30]
    inp = '\n\n'.join([f"标题:{s['标题']}\n{s.get('AwardInsight','')[:200]}" for s in all_s])[:4000]

    api_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not api_key:
        print("  [!] SILICONFLOW_API_KEY 未设置")
        mark_trend_done(data_dir)
        return

    payload = json.dumps({
        'model': 'deepseek-ai/DeepSeek-V4-Flash',
        'messages': [{'role': 'user', 'content': PROMPT_TREND_RADAR + inp}],
        'max_tokens': 4096,
        'temperature': 0.3
    }).encode()

    req = urllib.request.Request('https://api.siliconflow.cn/v1/chat/completions', data=payload, method='POST')
    req.add_header('Authorization', f"Bearer {api_key}")
    req.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            trend = json.loads(resp.read()).get('choices',[{}])[0].get('message',{}).get('content','')
    except Exception as e:
        print(f"  [ERROR] AI趋势分析失败: {e}")
        mark_trend_done(data_dir)
        return

    html_path = os.path.join(out_dir, '行业趋势分析.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>行业趋势分析</title><style>body{{font-family:Microsoft YaHei,sans-serif;max-width:900px;margin:40px auto;line-height:1.8}}</style></head><body><h1>行业趋势分析</h1>{trend}</body></html>')
    print(f"  [OK] 行业趋势分析: {html_path}")

    mark_trend_done(data_dir)
    print("  Day 7 complete")


# ═════ CLI ═════
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="周状态管理")
    sp = p.add_subparsers(dest="cmd", required=True)

    sp_add = sp.add_parser("add", help="追加一天")
    sp_add.add_argument("date", help="日期 YYYY-MM-DD")
    sp_add.add_argument("--data-dir", default="data", help="数据目录")

    sp_trend = sp.add_parser("trend", help="第7天合并CSV和行业趋势")
    sp_trend.add_argument("date", help="日期 YYYY-MM-DD")
    sp_trend.add_argument("--data-dir", default="data", help="数据目录")

    args = p.parse_args()

    if args.cmd == "add":
        is_day7_flag, state = add_day(args.date, args.data_dir)
        print(f"day7={is_day7_flag}")
        print(f"week_start={state['week_start']}")
        print(f"days_collected={state['days_collected']}")

    elif args.cmd == "trend":
        state = load_state(args.data_dir)
        if not is_day7(state):
            print("[!] 不是第7天, 跳过")
            print("day7=False")
        else:
            run_trend(args.date, args.data_dir)
            print("day7=True")
