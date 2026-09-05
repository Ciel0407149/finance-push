#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财经买方研究日报推送（GitHub Actions 版，LLM + 联网搜索）
流程：Tavily 联网搜索 -> LLM(Google Gemini 免费版，或硅基流动 DeepSeek-V3.2) 按买方框架生成报告 -> PushPlus 推送微信
用法：python main.py [morning|evening|weekly|auto]
环境变量：LLM_PROVIDER=gemini(默认) | siliconflow
需要 Secret：
  - 公共：TAVILY_API_KEY / PUSHPLUS_TOKEN
  - gemini 方案：GEMINI_API_KEY（https://aistudio.google.com/apikey 免费获取）
  - siliconflow 方案：SILICONFLOW_API_KEY（免费额度单次上限较低，长报告可能 402）
"""
import os
import sys
import json
import urllib.request
import urllib.parse
import datetime

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

MORNING_SEGMENT = """━━━━━━━━━━━【时段：工作晨报 09:00（A股港股盘前、美股隔夜收盘）】━━━━━━━━━━━
当前为交易日早上09:00（北京时间，美股已收盘、A股/港股盘前）。请真实执行：
1. 用联网搜索采集：①隔夜美股收盘（指数/板块/NVDA/MU/SKH/ASML/TSLA/GOOG/PDD 涨跌与原因）；②美联储/美债/美元/黄金隔夜动向；③当日中国宏观政策/行业重大事件；④今日A股港股盘前要点；⑤明日及本周重大事件；⑥持仓财报日历与预期更新。
2. 按日报结构输出（用今天北京时间真实日期，标注"晨"）：①一句话②市场环境③3-5件事④持仓影响⑤风险⑥机会⑦操作⑧验证指标⑨今日重点⑩财报日历（结构同晚报）。
3. 请直接输出完整 Markdown 报告正文（以「━━━━ 📅 每日投资情报 | {日期}（周X）晨 ━━━━」开头），推送由系统自动完成。
"""

WEEKLY_SEGMENT = """━━━━━━━━━━━【时段：周报 周日21:00（本周复盘 + 下周红点）】━━━━━━━━━━━
当前为周日21:00。请真实执行：
1. 用联网搜索采集本周重大事件复盘与下周红点事项（宏观数据时点/FOMC/持仓财报窗口/行业催化）。
2. 输出结构侧重：①本周一句话②本周市场环境复盘③本周最重要3-5件事（含验证/是否被证伪）④持仓影响与逻辑是否被证伪(A/B/C/D)⑤组合风险评分⑥下周最大风险⑦下周最大机会⑧是否需要操作⑨下周验证指标⑩持仓财报日历与预期(未来2-4周)。
3. 请直接输出完整 Markdown 报告正文（以「━━━━ 📅 每日投资情报 | {日期}（周日）周报 ━━━━」开头），推送由系统自动完成。
"""

SEARCHES = [
    ("A股港股收盘", "A股 港股 今日收盘 上证 深证 创业板 恒生 板块 异动 成交 北向资金", 1, "news"),
    ("宏观政策", "美联储 FOMC 美债收益率 美元 CPI PCE 非农 今日 宏观 政策", 2, "news"),
    ("AI半导体", "Nvidia ASML Micron SK Hynix HBM DRAM AI semiconductor news today stock", 1, "news"),
    ("重点美股个股", "Tesla Google Alphabet PDD Meituan earnings news today", 1, "news"),
    ("中国互联网", "美团 拼多多 京东 阿里 外卖 即时零售 Temu 今日 竞争 补贴", 1, "news"),
    ("新能源光伏", "通威 光伏 硅料 产能出清 反内卷 减产 涨价 今日", 2, "news"),
    ("黄金", "gold price real yields dollar central bank buying today safe haven", 2, "news"),
    ("持仓财报日历", "Nvidia PDD Meituan earnings date estimates revenue EPS guidance next weeks", 3, "news"),
]


def bj_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)


def load_prompt():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PROMPT_EVENING.md")
    with open(p, encoding="utf-8") as f:
        return f.read()


def split_prompt(full):
    i = full.find("【时段：工作日晚报")
    if i < 0:
        return full, ""
    return full[:i], full[i:]


def tavily_search(api_key, query, days=2, topic="news", max_results=5, content_chars=600):
    body = json.dumps({
        "api_key": api_key,
        "query": query,
        "topic": topic,
        "search_depth": "advanced",
        "days": days,
        "max_results": max_results,
        "include_answer": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        results = d.get("results", [])[:max_results]
        if not results:
            return "（无检索结果）"
        out = []
        for it in results:
            c = (it.get("content") or "")[:content_chars]
            out.append(f"- {it.get('title', '')}（{it.get('url', '')}）\n  {c}")
        return "\n".join(out)
    except Exception as e:
        return f"（检索失败：{e}）"


def _chat(base_url, api_key, model, system, user, max_tokens=None, extra_hint=None, timeout=300):
    sys_content = system + (extra_hint or "")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]


def call_siliconflow(api_key, system, user):
    return _chat(
        "https://api.siliconflow.cn/v1/chat/completions",
        api_key,
        "deepseek-ai/DeepSeek-V3.2",
        system, user,
    )


def call_gemini(api_key, system, user, model="gemini-2.0-flash", timeout=300):
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + model + ":generateContent?key=" + api_key)
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4000},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    try:
        return d["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return "（Gemini 未返回内容: " + json.dumps(d, ensure_ascii=False)[:600] + "）"


def push(token, title, content):
    body = urllib.parse.urlencode({
        "token": token,
        "title": title,
        "content": content,
        "template": "markdown",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "ignore")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    bj = bj_now()
    wd = bj.weekday()
    if mode == "auto":
        if wd == 5:
            print("周六，跳过推送")
            return
        mode = "weekly" if wd == 6 else ("morning" if 8 <= bj.hour < 12 else "evening")

    tag = {"morning": "晨", "evening": "晚", "weekly": "周报"}[mode]
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()

    tavily = os.environ.get("TAVILY_API_KEY")
    token = os.environ.get("PUSHPLUS_TOKEN")

    if provider == "gemini":
        gm = os.environ.get("GEMINI_API_KEY")
        missing = [n for n, v in (("TAVILY_API_KEY", tavily),
                                  ("GEMINI_API_KEY", gm),
                                  ("PUSHPLUS_TOKEN", token)) if not v]
        if missing:
            sys.exit("缺少环境变量(请在 GitHub Secrets 配置): " + ", ".join(missing))
        provider_label = "Gemini版"
        gen = lambda s, u: call_gemini(gm, s, u)
        print("调用 Google Gemini 生成报告 ...")
    else:
        sf = os.environ.get("SILICONFLOW_API_KEY")
        missing = [n for n, v in (("TAVILY_API_KEY", tavily),
                                  ("SILICONFLOW_API_KEY", sf),
                                  ("PUSHPLUS_TOKEN", token)) if not v]
        if missing:
            sys.exit("缺少环境变量(请在 GitHub Secrets 配置): " + ", ".join(missing))
        provider_label = "DeepSeek版"
        gen = lambda s, u: call_siliconflow(sf, s, u)
        print("调用 SiliconFlow(DeepSeek-V3.2) 生成报告 ...")

    framework, evening_seg = split_prompt(load_prompt())
    seg = evening_seg if mode == "evening" else (
        MORNING_SEGMENT if mode == "morning" else WEEKLY_SEGMENT)
    system = framework + "\n\n" + seg

    print(f"模式={mode} 开始联网检索 {len(SEARCHES)} 个主题 ...")
    # Gemini 上下文极大(1M token)，无需压缩搜索素材
    content_cap = 600
    res_cap = 5
    blocks = []
    for label, q, days, topic in SEARCHES:
        blocks.append(f"### {label}\n" + tavily_search(tavily, q, days, topic, res_cap, content_cap))

    user = (f"以下是北京时间 {bj.strftime('%Y-%m-%d')}（{WEEKDAYS[wd]}）"
            f"通过联网检索得到的素材，每条标注来源。请基于你的系统提示词，生成《{tag}》报告：\n\n"
            + "\n\n".join(blocks))

    report = gen(system, user)

    title = f"📊 投资情报 · {bj.strftime('%Y-%m-%d')}（{WEEKDAYS[wd]}）{tag} · {provider_label}"
    resp = push(token, title, report)
    print("PushPlus 返回:", resp)
    print(f"已推送{tag}（{provider_label}），约 {len(report)} 字")


if __name__ == "__main__":
    main()
