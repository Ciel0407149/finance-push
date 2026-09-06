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
import re
import sys
import json
import time
import urllib.request
import urllib.parse
import datetime

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 持仓标的新浪行情代码（用于报告中的「市场反应 / 已定价多少」分析）
QUOTE_CODES = {
    "英伟达 NVDA": "gb_nvda",
    "ASML": "gb_asml",
    "美光 MU": "gb_mu",
    "特斯拉 TSLA": "gb_tsla",
    "谷歌 GOOGL": "gb_goog",
    "拼多多 PDD": "gb_pdd",
    "美团 3690.HK": "rt_hk03690",
    "青岛啤酒 600600": "sh600600",
    "通威股份 600438": "sh600438",
    "沪深300指数": "sh000300",
    "COMEX黄金": "hf_GC",
}

MORNING_SEGMENT = """━━━━━━━━━━━【时段：工作晨报 09:00（A股港股盘前、美股隔夜收盘）】━━━━━━━━━━━
当前为交易日早上09:00（北京时间，美股已收盘、A股/港股盘前）。请真实执行：
1. 用联网搜索采集：①隔夜美股收盘（指数/板块/NVDA/MU/SKH/ASML/TSLA/GOOG/PDD 涨跌与原因）；②美联储/美债/美元/黄金隔夜动向；③当日中国宏观政策/行业重大事件；④今日A股港股盘前要点；⑤明日及本周重大事件；⑥持仓财报日历与预期更新。
2. 按日报结构输出（用今天北京时间真实日期，标注"晨"）：①一句话②市场环境③3-5件事④持仓影响⑤风险⑥机会⑦操作⑧验证指标⑨今日重点⑩财报日历（结构同晚报）。每件事必须含：【事件(含日期)】【事实(含数据日期)】【市场反应(隔夜美股/相关标的的价格变化，用下方【行情快照】佐证)】【为什么重要】【对我的持仓】【影响时间(注明起算点)】【市场是否已经定价(以价格反应为依据)】【下一步验证】。
3. 【时效性与行情铁律】所有事件与数据必须标注日期(YYYY-MM-DD)及时效标签(今日/24小时内/本周内/更早)，禁止引用无日期的信息。系统会在素材末尾提供【行情快照】，必须用它回答【市场反应】并判断【市场是否已经定价】；行情缺失须明写"行情数据缺失"，严禁编造价格数字。
4. 请直接输出完整 Markdown 报告正文（以「━━━━ 📅 每日投资情报 | {日期}（周X）晨 ━━━━」开头），推送由系统自动完成。
"""

WEEKLY_SEGMENT = """━━━━━━━━━━━【时段：周报 周日21:00（本周复盘 + 下周红点）】━━━━━━━━━━━
当前为周日21:00。请真实执行：
1. 用联网搜索采集本周重大事件复盘与下周红点事项（宏观数据时点/FOMC/持仓财报窗口/行业催化）。
2. 输出结构侧重：①本周一句话②本周市场环境复盘③本周最重要3-5件事（含验证/是否被证伪）④持仓影响与逻辑是否被证伪(A/B/C/D)⑤组合风险评分⑥下周最大风险⑦下周最大机会⑧是否需要操作⑨下周验证指标⑩持仓财报日历与预期(未来2-4周)。每件事必须含【事件(本周具体日期)】【事实(含数据日期)】【市场反应(本周相关标的价格/涨跌幅变化)】【为什么重要】【对我的持仓】【影响时间】【市场是否已经定价(以价格反应为依据)】。
3. 【时效性与行情铁律】所有事件与数据必须标注具体日期，禁止引用无日期信息；系统会在素材末尾提供【行情快照】，须用其周内涨跌幅变化佐证【市场反应】与【市场是否已经定价】；行情缺失须明写"行情数据缺失"，严禁编造价格。
4. 请直接输出完整 Markdown 报告正文（以「━━━━ 📅 每日投资情报 | {日期}（周日）周报 ━━━━」开头），推送由系统自动完成。
"""

SEARCHES = [
    ("A股港股收盘", "A股 港股 今日收盘 上证 深证 创业板 恒生 板块 异动 成交 北向资金", 1, "news"),
    ("宏观政策", "美联储 FOMC 美债收益率 美元 CPI PCE 非农 今日 宏观 政策", 2, "news"),
    ("AI半导体", "Nvidia ASML Micron SK Hynix HBM DRAM AI semiconductor news today stock", 1, "news"),
    ("重点美股个股", "Tesla Google Alphabet PDD Meituan earnings news today", 1, "news"),
    ("中国互联网", "美团 拼多多 京东 阿里 外卖 即时零售 Temu 今日 竞争 补贴", 1, "news"),
    ("新能源光伏", "通威 光伏 硅料 产能出清 反内卷 减产 涨价 今日", 2, "news"),
    ("黄金", "gold price real yields dollar central bank buying today safe haven", 2, "news"),
    # 财报日历：覆盖全部持仓，时间窗放宽到 30 天（财报公告不会每天都有）
    ("持仓财报日历-海外", "upcoming earnings date schedule NVIDIA ASML Micron \"SK Hynix\" Tesla Alphabet PDD Q3 2026 official announcement", 30, "news"),
    ("持仓财报日历-中国", "美团 拼多多 青岛啤酒 通威股份 财报发布日期 业绩公告 三季度 预约披露时间", 30, "news"),
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
            # 带上发布日期，确保报告能判断时效性
            pub = it.get("published_date") or it.get("publishedDate") or ""
            date_tag = f"[{pub[:10]}] " if pub else "[日期未知] "
            out.append(f"- {date_tag}{it.get('title', '')}（{it.get('url', '')}）\n  {c}")
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


# Gemini 模型候选：实测只有 *-latest 官方别名有效（具体版本号如 2.5-flash/2.0-flash 已 404 下线）
GEMINI_MODELS = [
    os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
    "gemini-pro-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]
# 视为临时过载、值得退避重试的状态码
RETRY_CODES = (500, 502, 503, 504)
# 退避等待（秒）
RETRY_DELAYS = [10, 25, 45]
# 总时间预算（秒）。必须留够时间让回退链走到最后一个模型——
# 2026-09-06 周报失败就是因为预算只剩 240s，前两个模型耗光后没轮到可用的 lite 模型就放弃了。
# job timeout 为 20 分钟，这里给 8 分钟安全。
GEMINI_BUDGET = 480


def call_gemini(api_key, system, user, timeout=300):
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4000},
    }
    body = json.dumps(payload).encode("utf-8")
    last_err = None
    started = time.time()

    def over_budget():
        return (time.time() - started) > GEMINI_BUDGET

    for model in GEMINI_MODELS:
        if over_budget():
            print(f"[Gemini] 已达总时间预算 {GEMINI_BUDGET}s，停止尝试")
            break
        for attempt in range(len(RETRY_DELAYS) + 1):  # 每个模型最多 4 次尝试
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   + model + ":generateContent?key=" + api_key)
            req = urllib.request.Request(url, data=body,
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read())
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 404:
                    print(f"[Gemini] {model}: HTTP 404 模型不可用，换下一个")
                    break  # 换模型
                if e.code == 429:
                    # 配额耗尽/限流：等待无意义，立刻换下一个模型，把预算留给可能还能用的模型
                    print(f"[Gemini] {model}: HTTP 429 配额耗尽，立即换下一个模型")
                    break
                if e.code in RETRY_CODES:
                    if attempt >= len(RETRY_DELAYS) or over_budget():
                        print(f"[Gemini] {model}: 不再等待，"
                              f"{'已达时间预算' if over_budget() else '重试次数用尽'}")
                        break
                    wait = RETRY_DELAYS[attempt]
                    print(f"[Gemini] {model}: HTTP {e.code} 过载，等待 {wait}s 后重试"
                          f"（第 {attempt + 1}/{len(RETRY_DELAYS) + 1} 次）")
                    time.sleep(wait)
                    continue
                raise  # 其余错误（403 密钥无效等）直接抛出
            print(f"[Gemini] 使用模型: {model}")
            try:
                return d["candidates"][0]["content"]["parts"][0]["text"]
            except Exception:
                return "（Gemini 未返回内容: " + json.dumps(d, ensure_ascii=False)[:600] + "）"
    if last_err:
        raise last_err
    return "（Gemini 无可用模型）"


def _yahoo_quote(symbol, name):
    """Yahoo 兜底（新浪没有的标的，如 SK 海力士）"""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + symbol + "?interval=1d&range=5d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        meta = d["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        pct = (price - prev) / prev * 100 if prev else None
        return f"- {name}: {price}（{pct:+.2f}%）" if pct is not None else f"- {name}: {price}"
    except Exception:
        return f"- {name}: （行情获取失败）"


def fetch_quotes():
    """抓取持仓标的最新价与涨跌幅，供报告分析『市场反应/已定价多少』。
    行情不是主流程，失败只降级不中断。"""
    codes = ",".join(QUOTE_CODES.values())
    url = "https://hq.sinajs.cn/list=" + codes
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("gbk", "ignore")
    except Exception as e:
        return "（行情接口不可用：%s）" % e

    lines = []
    for name, code in QUOTE_CODES.items():
        m = re.search(r'hq_str_%s="([^"]*)"' % re.escape(code), raw)
        if not m or not m.group(1):
            continue
        f = m.group(1).split(",")
        try:
            if code.startswith("gb_"):          # 美股：名称,现价,涨跌幅%,时间
                lines.append(f"- {name}: {f[1]}（{f[2]}%） 数据时间 {f[3]}")
            elif code.startswith("rt_hk"):      # 港股：...,现价,涨跌额,涨跌幅%
                lines.append(f"- {name}: {f[6]}（{f[8]}%）")
            else:                                # A股/商品：名称,今开,昨收,现价...
                prev, now = float(f[2]), float(f[3])
                lines.append(f"- {name}: {now}（{(now - prev) / prev * 100:+.2f}%）")
        except Exception:
            lines.append(f"- {name}: （解析失败）")
    # SK 海力士新浪无，走 Yahoo
    lines.append(_yahoo_quote("000660.KS", "SK海力士 000660.KS"))
    return "\n".join(lines) if lines else "（行情无数据）"


def already_handled():
    """补跑专用：检查本次推送窗口内是否已有成功推送，或主跑仍在进行。
    返回 True 表示应当跳过（避免重复推送两条一样的报告，或与主跑撞车）。"""
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not (repo and token):
        return False  # 本地运行无这些变量，照常推送
    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=15"
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[补跑检查] 查询运行记录失败（{e}），按未推送处理")
        return False

    now = datetime.datetime.now(datetime.timezone.utc)
    for r in data.get("workflow_runs", []):
        if str(r.get("id")) == str(run_id):
            continue
        try:
            created = datetime.datetime.strptime(
                r["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc)
        except Exception:
            continue
        age_min = (now - created).total_seconds() / 60.0
        if age_min > 120:      # 只看近 2 小时内的运行
            continue
        st, con = r.get("status"), r.get("conclusion")
        if con == "success":
            print(f"[补跑检查] {age_min:.0f} 分钟前已成功推送过，本次跳过，避免重复")
            return True
        if st in ("in_progress", "queued", "waiting"):
            print(f"[补跑检查] {age_min:.0f} 分钟前启动的推送仍在进行（{st}），本次跳过")
            return True
    return False


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

    # 补跑（整点后 40 分钟那次）：先确认主跑是否失败，失败才补发
    if os.environ.get("IS_RETRY", "").lower() == "true":
        if already_handled():
            print("补跑结束：本次无需重复推送")
            return
        print("[补跑] 未发现成功推送记录，开始补发 ...")

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
    # 注入当前日期作为时间锚点：模型常因缺少"今天"而沿用提示词里的历史日期
    # （例如 8 月写死的财报窗口到 9 月仍在用），这里强制以当天为准。
    date_anchor = (
        f"【当前时间锚点】现在是北京时间 {bj.year} 年 {bj.month} 月 {bj.day} 日"
        f"（{WEEKDAYS[wd]}），此为全文唯一基准日期。"
        f"所有财报日历、事件时效、数据归属的判断都必须以该日期为准；"
        f"任何早于该日期且已过期的历史信息（尤其是历史财报日期）"
        f"只能作为回顾引用，绝不能当作当期或未来事项。\n\n")
    system = date_anchor + framework + "\n\n" + seg

    print(f"模式={mode} 开始联网检索 {len(SEARCHES)} 个主题 ...")
    # Gemini 上下文极大(1M token)，无需压缩搜索素材
    content_cap = 600
    res_cap = 5
    blocks = []
    for label, q, days, topic in SEARCHES:
        blocks.append(f"### {label}\n" + tavily_search(tavily, q, days, topic, res_cap, content_cap))

    print("抓取持仓行情快照（用于分析市场对消息的反应）...")
    quotes = fetch_quotes()
    print(quotes)

    now_str = bj.strftime("%Y-%m-%d %H:%M")
    user = (f"以下是北京时间 {now_str}（{WEEKDAYS[wd]}）"
            f"通过联网检索得到的素材，每条已标注来源与发布日期。请基于你的系统提示词，生成《{tag}》报告：\n\n"
            + "\n\n".join(blocks)
            + f"\n\n### 行情快照（北京时间 {now_str} 抓取，用于分析市场对消息的反应）\n"
            + quotes
            + "\n\n【输出硬要求】①每条事件必须带具体日期与时效标签；②每条事件必须有【市场反应】，"
              "用上方行情快照或检索到的价格变化说明消息出来后市场怎么走；③【市场是否已经定价】"
              "必须以价格反应为依据，禁止凭空判断；④行情数据缺失时明写，严禁编造价格。")

    report = gen(system, user)

    title = f"📊 投资情报 · {bj.strftime('%Y-%m-%d')}（{WEEKDAYS[wd]}）{tag} · {provider_label}"
    resp = push(token, title, report)
    print("PushPlus 返回:", resp)
    print(f"已推送{tag}（{provider_label}），约 {len(report)} 字")


if __name__ == "__main__":
    main()
