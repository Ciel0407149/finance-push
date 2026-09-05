# 财经买方研究日报 自动推送（GitHub Actions 版）

把「联网搜索 → 买方框架研究 → 生成报告 → 推送微信」搬到 GitHub 云端定时跑，**不需要你的电脑开机**。

## 推送内容
- **工作日 09:00（北京）晨报**：隔夜美股 + 盘前要点
- **工作日 21:00（北京）晚报**：A股收盘 + 美股盘前（完整买方研究框架）
- **周日 21:00（北京）周报**：本周复盘 + 财报日历
- 周六不推送

报告由 **Tavily 联网搜索 + 大模型**按买方投资研究框架生成（降噪、持仓影响、风险/机会/操作判断、财报日历），再以 Markdown 推送至微信（PushPlus）。默认用硅基流动 SiliconFlow（DeepSeek-V3）；另提供 GitHub Models（GPT-4o）方案，**零成本、零新密钥**，用 GitHub 账号即可调。两个方案各自定时推送，微信每天收两份（标题标「DeepSeek版」「GPT版」），可对比质量、互为备份。

## 部署步骤（一次性）
1. 在 GitHub 新建一个仓库（如 `finance-push`），把本目录（`main.py`、`PROMPT_EVENING.md`、`.github/workflows/daily.yml`）推上去。
2. 仓库 → Settings → Secrets and variables → Actions → **New repository secret**，添加 3 个（GitHub Models 方案用 Actions 自动的 `GITHUB_TOKEN`，无需额外密钥）：
   - `PUSHPLUS_TOKEN`：你的 PushPlus Token（https://www.pushplus.plus 「我的」→ 个人中心 复制）
   - `TAVILY_API_KEY`：Tavily 搜索 API Key（https://tavily.com 注册，免费额度 1000 次/月）
   - `SILICONFLOW_API_KEY`：硅基流动 SiliconFlow API Key（https://cloud.siliconflow.cn 注册，新用户送 2000 万 token 免费额度）
3. 打开仓库 → Actions 页，确认两个 workflow（**财经推送** / **财经推送-GitHubModels**）均已启用。
4. 首次建议手动跑一次验证：Actions → 该 workflow → Run workflow → 选 `evening`（绕开周六跳过），看微信是否收到。

## 定时说明
GitHub Actions 的 cron 使用 **UTC**：
- `0 1 * * 1-5` → 北京 09:00（周一~周五 晨报）
- `0 13 * * 1-5` → 北京 21:00（周一~周五 晚报）
- `0 13 * * 0` → 北京 21:00（周日 周报）

脚本内部也按北京时间判断（周六自动跳过、周日走周报、工作日按上午/晚间区分）。

## 本地调试
```bash
# 需要三个环境变量
export TAVILY_API_KEY=xxx
export SILICONFLOW_API_KEY=xxx
export PUSHPLUS_TOKEN=xxx

python3 main.py auto
python3 main.py morning
python3 main.py evening
python3 main.py weekly
```

## 注意事项
- 免费额度：GitHub Actions 每月 2000 分钟（两个 workflow 共享）；Tavily 免费 1000 次/月（每日约 16 次搜索）；硅基流动送 2000 万 token（DeepSeek-V3 约 ¥2/百万输入、¥3/百万输出）；GitHub Models 用 GitHub 账号免费调 GPT-4o（限 50 次/天、输出 4K token，长报告日 GPT 版可能截断）。
- 买方研究框架（含你的持仓、筛选规则、10 段输出结构）保存在 `PROMPT_EVENING.md`，可随时修改。
- 财报日期为公开一致预期 / 推算，标注「待官方确认」者以公司公告为准。
