# -*- coding: utf-8 -*-
"""周状态管理模块 — 追踪7天循环, 合并CSV, 清理旧数据
数据持久化在 data/ 目录下 (Git data分支同步)
"""

import os, json, csv, shutil, re
from datetime import datetime, timedelta

STATE_FILE = "week_state.json"

def load_state(data_dir="data"):
    """读取周状态文件"""
    path = os.path.join(data_dir, STATE_FILE)
    if not os.path.exists(path):
        return {"week_start": "", "days_collected": 0, "folders": [], "trend_generated": False}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state, data_dir="data"):
    """保存周状态文件"""
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, STATE_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_day7(state):
    """判断当前是否第7天"""
    return state.get("days_collected", 0) >= 7

def should_reset(state):
    """判断是否需要重置(第8天: 已生成趋势且已收集满7天)"""
    return state.get("trend_generated", False) and state.get("days_collected", 0) >= 7

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def yesterday_str():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

def start_week(date_str=None):
    """开始新的一周"""
    d = date_str or today_str()
    state = {"week_start": d, "days_collected": 0, "folders": [], "trend_generated": False}
    return state

def add_day(date_str, data_dir="data"):
    """追加一天数据, 返回 (is_day7, state)"""
    state = load_state(data_dir)

    # 检查是否需要重置
    if should_reset(state):
        _clean_old_week(state, data_dir)
        state = start_week(date_str)

    # 如果week_start为空(首次运行), 初始化
    if not state.get("week_start"):
        state = start_week(date_str)

    # 追加日期
    folders = state.get("folders", [])
    if date_str not in folders:
        folders.append(date_str)
    state["folders"] = folders
    state["days_collected"] = len(folders)
    state["week_start"] = state["week_start"] or date_str

    save_state(state, data_dir)
    return is_day7(state), state

def mark_trend_done(data_dir="data"):
    """标记趋势分析已完成"""
    state = load_state(data_dir)
    state["trend_generated"] = True
    save_state(state, data_dir)
    return state

def _clean_old_week(state, data_dir="data"):
    """清理上一周的所有数据文件夹"""
    output_dir = os.path.join(data_dir, "output")
    if not os.path.isdir(output_dir):
        return
    for folder in state.get("folders", []):
        path = os.path.join(output_dir, folder)
        if os.path.isdir(path):
            # 可选: 移到 week_archive/
            shutil.rmtree(path, ignore_errors=True)
    # 也清理 weekly summary 文件
    for f in os.listdir(output_dir):
        if "本周汇总" in f or "行业趋势分析" in f:
            os.remove(os.path.join(output_dir, f))

def merge_weekly_csv(state, data_dir="data"):
    """合并7天CSV为本周汇总"""
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

    # 写入合并文件到最新日期的文件夹
    last_folder = folders[-1]
    merge_path = os.path.join(output_dir, last_folder, "本周文物数字化汇总.csv")
    with open(merge_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(all_rows)

    return merge_path

def get_zip_name(date_str, is_day7):
    """获取zip包文件名"""
    if is_day7:
        return f"{date_str}_文物数字化本周汇总.zip"
    return f"{date_str}_文物数字化中标信息.zip"

def get_output_dir(data_dir="data"):
    """获取当前日期的输出目录"""
    return os.path.join(data_dir, "output", today_str())
