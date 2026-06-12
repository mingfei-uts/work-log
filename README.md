# 📋 Work Log — 日系墨纸风格工作日志

纯本地的工作日志系统：任务管理 + 时间追踪 + AI 自动总结 + Claude Code 会话导入。

## 快速开始

```bash
# 1. 配置 DeepSeek API key
cp .work-log.env.example .work-log.env
# 编辑 .work-log.env，填入你的 key

# 2. 一键启动
./start-work-log.sh
```

浏览器会自动打开，服务器在 `http://localhost:19878`。

## 功能

- **任务管理** — 自然语言录入（`修bug 2h ✓ 项目名`），自动解析时长和状态
- **时间追踪** — 点击任务旁的计时点开始/停止计时
- **AI 自动总结** — 每天 18:00 自动调用 DeepSeek 生成今日要点
- **Claude Code 集成** — CC 会话结束自动提取工作内容，无需手动记录
- **Git diff 分析** — AI 总结自动包含 git 变更文件信息
- **周报** — 每周五自动生成结构化周报
- **项目维度** — 任务按项目归类，侧栏一键筛选
- **工具箱** — 管理常用工具链接，快速搜索复制

## 文件

| 文件 | 说明 |
|---|---|
| `daily-work-log.html` | 前端界面，浏览器打开 |
| `work-log-server.py` | 本地 HTTP 服务，管理数据 + AI 总结 |
| `work-log-cli.py` | 命令行工具 |
| `start-work-log.sh` | 一键启动 |

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 无 |
| `WORK_LOG_SCHEDULE` | 每日自动总结时间 | `18:00` |
| `WORK_LOG_PORT` | 服务器端口 | `19878` |

## 快捷键

| 键 | 功能 |
|---|---|
| `⌘S` | 保存 |
| `⌘I` | AI 生成总结 |
| `⌘1/2` | 切换日志/工具视图 |
| `⌘←/→` | 前一天/后一天 |
