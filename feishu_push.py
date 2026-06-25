# -*- coding: utf-8 -*-
"""飞书推送模块 — 卡片消息 + zip附件(AI总结HTML+附件PDF+Day7本周汇总)
环境变量: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID
用法: python feishu_push.py --date 2026-06-23
"""

import os, json, argparse, urllib.request, urllib.error, zipfile, glob
from datetime import datetime, timezone
BJ_TZ = timezone(timedelta(hours=8))  # 北京时间

FEISHU_BASE = "https://open.feishu.cn/open-apis"

def log(*a):
    print(*a, flush=True)

def _post(url, data=None, headers=None, method="POST"):
    h = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        h.update(headers)
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _get_token():
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        log("[ERROR] FEISHU_APP_ID 或 FEISHU_APP_SECRET 未设置")
        return None
    result = _post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal", {
        "app_id": app_id, "app_secret": app_secret
    })
    if result.get("code") != 0:
        log(f"[ERROR] 获取token失败: {result}")
        return None
    return result["tenant_access_token"]

def _send_message(token, chat_id, msg_type, content):
    result = _post(
        f"{FEISHU_BASE}/im/v1/messages?receive_id_type=chat_id",
        {"receive_id": chat_id, "msg_type": msg_type, "content": json.dumps(content)},
        {"Authorization": f"Bearer {token}"}
    )
    return result

def _upload_file(token, file_path):
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext in ("pdf","doc","docx","xls","xlsx","ppt","pptx","mp4","jpg","jpeg","png","mp3","wav"):
        file_type = ext
    else:
        file_type = "stream"

    with open(file_path, "rb") as f:
        file_data = f.read()

    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_type"\r\n\r\n'
        f"{file_type}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_name"\r\n\r\n'
        f"{filename}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{FEISHU_BASE}/im/v1/files",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("code") != 0:
            log(f"[ERROR] 文件上传失败: {result.get('msg','')}")
            return None
        return result.get("data", {}).get("file_key")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")
        log(f"[ERROR] 文件上传HTTP {e.code}: {err_body[:200]}")
        return None

def build_card(date_str, items, is_day7=False):
    """构建飞书卡片"""
    total = len(items)
    elements = []

    if is_day7:
        title_text = f"**📋 文物数字化中标信息日报 {date_str} (本周第7天)**\n\n共 {total} 条中标/成交公告"
    else:
        title_text = f"**📋 文物数字化中标信息日报 {date_str}**\n\n共 {total} 条中标/成交公告"

    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": title_text}
    })
    elements.append({"tag": "hr"})

    for i, item in enumerate(items[:10], 1):
        title = item.get("标题", "")
        buyer = item.get("采购人", "N/A")
        supplier = item.get("供应商", "N/A")
        amount = item.get("中标金额(万)", "N/A")
        region = item.get("地区", "")
        bid_type = item.get("公告类型", "")
        url = item.get("原文链接", "")

        content = f"**{i}. {title}**\n"
        content += f"📍 {region} | {bid_type} | 💰 {amount}万\n"
        content += f"🏢 采购人: {buyer}\n"
        content += f"🏭 供应商: {supplier}\n"
        content += f"🤖 AI总结: 见附件zip\n"
        content += f"🔗 [查看原文公告]({url})"

        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})
        elements.append({"tag": "hr"})

    if total > 10:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"📊 还有 {total-10} 条, 完整数据见附件zip"}
        })

    if is_day7:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                "content": "📊 **本周行业趋势分析已生成**\n包含7天汇总CSV + 行业趋势分析报告, 见附件zip"}
        })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"文物数字化中标日报 {date_str}"},
            "template": "blue"
        },
        "elements": elements
    }

def _pack_zip(out_dir, zip_name, day7=False):
    """打包zip: CSV+AI总结HTML+附件子文件夹
    常规日: 排除 json
    第7天: 额外确保 本周文物数字化汇总.csv + 行业趋势分析.html 已打包"""
    zip_path = os.path.join(out_dir, zip_name)
    # 排除自身zip(动态名称) + 静态排除列表
    skip_names = {"attachments.json", "文物数字化.json", "summaries.json",
                  "文物数字化_new.csv", "daily-report.zip", zip_name}
    skip_prefixes = ("~$", ".~")

    if day7:
        log("  [Day7] 本周汇总CSV + 行业趋势HTML 将一并打包")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(out_dir):
            for f in files:
                if f in skip_names or f.startswith(skip_prefixes):
                    continue
                fp = os.path.join(root, f)
                arcname = os.path.relpath(fp, os.path.dirname(out_dir))
                try:
                    zf.write(fp, arcname)
                except Exception as e:
                    log(f"  SKIP {arcname}: {e}")

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    log(f"  zip: {zip_name} ({size_mb:.1f}MB)")
    return zip_path

def run(date_str=None):
    if not date_str:
        date_str = datetime.now(BJ_TZ).strftime("%Y-%m-%d")

    chat_id = os.environ.get("FEISHU_CHAT_ID", "")
    if not chat_id:
        log("[ERROR] FEISHU_CHAT_ID 未设置")
        return

    token = _get_token()
    if not token:
        return

    # 读取周状态: 优先从 week_cache, 回退到 data
    from week_manager import load_state, is_day7, get_zip_name
    state = load_state("week_cache")
    if not state.get("folders"):
        state = load_state("data")
    day7 = is_day7(state)
    zip_name = get_zip_name(date_str, day7)

    # 查找JSON: 依次搜索 week_cache/ > data/ > output/
    search_dirs = [
        os.path.join("week_cache", "output", date_str),
        os.path.join("data", "output", date_str),
        os.path.join("output", date_str),
    ]
    json_path = ""
    for d in search_dirs:
        p = os.path.join(d, "文物数字化.json")
        if os.path.exists(p):
            json_path = p
            break
    if not json_path:
        log(f"[!] 未找到JSON in {search_dirs}")
        return
    work_out = os.path.dirname(json_path)
    log(f"  数据源: {work_out}")

    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    log(f"[*] 推送飞书: {len(items)}条公告 | 第{state.get('days_collected',0)}天 | day7={day7}")

    # 1. 发送卡片
    card = build_card(date_str, items, day7)
    result = _send_message(token, chat_id, "interactive", card)
    if result.get("code") == 0:
        log("  ✅ 卡片消息发送成功")
    else:
        log(f"  ❌ 卡片消息失败: {result.get('msg', '')}")

    # 2. 打包zip
    zip_path = _pack_zip(work_out, zip_name, day7=day7)

    # 3. 发送zip
    file_key = _upload_file(token, zip_path)
    if file_key:
        result = _send_message(token, chat_id, "file", {"file_key": file_key})
        if result.get("code") == 0:
            log("  ✅ 附件发送成功")
        else:
            log(f"  ❌ 附件发送失败: {result.get('msg', '')}")
    else:
        log("  ❌ 附件上传失败")

    log(f"\n[*] 飞书推送完成")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="飞书推送模块")
    p.add_argument("--date", default=None, help="日期 YYYY-MM-DD")
    a = p.parse_args()
    run(a.date)
