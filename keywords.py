# -*- coding: utf-8 -*-
"""文物数字化爬虫 — 20个关键词 + 3个AI Prompt模板
来源: 文物数字化中标信息Prompt与关键词库.docx
"""

# ═══ 第六部分: 优先级最高的20个监测关键词 ═══
KEYWORDS_20 = [
    "文物数字化", "馆藏数字化", "智慧博物馆", "数字孪生博物馆", "三维扫描",
    "三维建模", "三维重建", "摄影测量", "激光扫描", "数字展厅",
    "虚拟展馆", "数字资源平台", "文物数据库", "藏品管理系统", "数字资产管理系统",
    "AI讲解", "数字人讲解", "智慧导览", "文化遗产数字化", "考古数字化",
]

# ═══ 模板1: CHD-Award Insight (标准分析模板) ═══
PROMPT_AWARD_INSIGHT = """You are a senior cultural heritage digitalization analyst.

Analyze the following government procurement award announcement and extract the key information.

Requirements:

1. Project Overview
   - Project Name
   - Procuring Organization
   - Winning Bidder
   - Contract Amount
   - Award Date

2. Technical Scope
   - Main project objectives
   - Technologies involved
   - Deliverables

3. Digital Heritage Classification
   Categorize the project into one or more of the following areas:
   - 3D Scanning
   - Photogrammetry
   - Digital Archiving
   - GIS Mapping
   - Digital Twin
   - Virtual Exhibition
   - AR/VR/MR
   - AI Applications
   - Collection Management
   - Cultural Heritage Database
   - Smart Museum
   - Digital Preservation

4. Market Intelligence
5. Competitive Insights
6. Executive Summary

IMPORTANT: Please provide your entire response in Chinese (中文).\n\nInput:
"""

# ═══ 模板2: CHD-Market Intelligence (市场情报监测模板) ═══
PROMPT_MARKET_INTEL = """You are a cultural heritage market intelligence analyst.

Review the procurement award announcement and generate an intelligence report.

Output format:

# Basic Information
# Technical Tags
# Project Category
# Core Deliverables
# Market Signals
# Future Opportunities
# Strategic Value
# One-Sentence Summary

IMPORTANT: Please provide your entire response in Chinese (中文).\n\nInput:
"""

# ═══ 模板3: CHD-Trend Radar (行业趋势分析模板) ═══
PROMPT_TREND_RADAR = """You are a market research expert specializing in museum and cultural heritage digitalization.

Analyze all procurement award announcements provided below.

Tasks:
1. Identify recurring technologies.
2. Identify recurring suppliers.
3. Identify recurring government agencies.
4. Identify emerging technology trends.
5. Identify regions with the highest investment activity.
6. Rank the top project categories by frequency.
7. Generate a strategic industry report.

IMPORTANT: Please provide your entire response in Chinese (中文).\n\nInput:
"""


# ═══ 域名过滤词: 搜索结果标题必须包含至少一个才保留 ═══
DOMAIN_FILTER = [
    "文物", "博物馆", "博物苑", "文化遗产", "非遗",
    "考古", "藏品", "遗址", "石窟", "古建筑", "石刻",
    "文保", "文物保护", "纪念馆",
]

# ═══ 默认关键词字符串(逗号分隔, 供CLI和CI使用) ═══
KEYWORDS_STR = ",".join(KEYWORDS_20)
