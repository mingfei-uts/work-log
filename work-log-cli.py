#!/usr/bin/env python3
"""
Work Log CLI — 命令行工具
==========================
与 work-log-server.py 配合，也可独立读取 JSON 文件。

用法:
  python3 work-log-cli.py today              查看今日任务和笔记
  python3 work-log-cli.py summary [--date D]  生成每日总结 (含 git log)
  python3 work-log-cli.py stats [--month M]   月度统计
  python3 work-log-cli.py gitlog [--date D]   查看 git 提交
  python3 work-log-cli.py write-summary <text>  将总结写入笔记
  python3 work-log-cli.py generate-summary [--date D]  调用 AI 自动生成总结
  python3 work-log-cli.py path                打印数据文件路径

所有命令优先通过 HTTP 服务器 (localhost:19876) 执行；
若服务器未运行则直接读写 JSON 文件。
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

SERVER = os.environ.get("WORK_LOG_SERVER", "http://127.0.0.1:19878")
DATA_FILE = Path(os.environ.get("WORK_LOG_FILE",
    os.path.expanduser("~/Desktop/Research/work-log-data.json"))).resolve()

def server_ok():
    """Check if server is reachable."""
    try:
        req = urllib.request.Request(f"{SERVER}/ping")
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except:
        return False

def server_get(path):
    """GET from server. Returns parsed JSON or None."""
    try:
        req = urllib.request.Request(f"{SERVER}{path}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [server error: {e}]", file=sys.stderr)
        return None

def server_post(path, data):
    """POST to server. Returns parsed JSON or None."""
    try:
        body = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(f"{SERVER}{path}", data=body,
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [server error: {e}]", file=sys.stderr)
        return None

def file_read():
    """Read JSON file directly."""
    if not DATA_FILE.exists():
        return {"version": 1, "log": {}, "tools": []}
    with open(DATA_FILE) as f:
        return json.load(f)

def file_write(data):
    """Write JSON file directly (atomic)."""
    import tempfile
    data['updatedAt'] = datetime.now().isoformat()
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(DATA_FILE.parent),
        prefix='.' + DATA_FILE.name + '.', suffix='.tmp')
    try:
        with os.fdopen(tmp_fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(DATA_FILE))
    except:
        os.unlink(tmp_path)
        raise


# ---- Commands ----
def today(date_str=None):
    if date_str is None: date_str = datetime.now().strftime('%Y-%m-%d')

    if server_ok():
        data = server_get(f"/summary/{date_str}")
    else:
        data = file_read()
        day = data.get('log', {}).get(date_str, {})
        tasks = day.get('tasks', [])
        d = datetime.strptime(date_str, '%Y-%m-%d')
        w = ['一','二','三','四','五','六','日'][d.weekday()]
        data = {
            "date": date_str, "weekday": w, "tasks": tasks,
            "notes": day.get('notes', ''),
            "stats": {
                "total_seconds": sum(t.get('seconds',0) for t in tasks),
                "done_count": sum(1 for t in tasks if t.get('done')),
                "total_count": len(tasks),
                "pending_count": sum(1 for t in tasks if not t.get('done'))
            }
        }

    if not data:
        print("❌ 无法获取数据"); return 1

    tasks = data.get('tasks', [])
    stats = data.get('stats', {})
    notes = data.get('notes', '')
    total_sec = stats.get('total_seconds', 0)
    h, m = total_sec // 3600, (total_sec % 3600) // 60

    print(f"\n📅 {data['date']} 星期{data['weekday']} 工作日志\n{'='*40}")
    if not tasks:
        print("\n📝 (今日暂无任务)")
    else:
        print(f"\n📝 任务 ({stats.get('done_count',0)}/{stats.get('total_count',0)}):")
        for t in tasks:
            s = '✓' if t.get('done') else '○'
            sec = t.get('seconds', 0)
            ts = ''
            if sec > 0:
                th, tm = sec // 3600, (sec % 3600) // 60
                ts = f' [{th}h{tm}m]' if th > 0 else f' [{tm}m]'
            print(f"   {s} {t['text']}{ts}")

    if total_sec > 0:
        print(f"\n⏱ 追踪时长: {h}h{m}m")

    if notes:
        print(f"\n📄 笔记:\n   {notes[:500]}{'...' if len(notes)>500 else ''}")
    print()
    return 0

def summary(date_str=None):
    if date_str is None: date_str = datetime.now().strftime('%Y-%m-%d')

    if server_ok():
        data = server_get(f"/summary/{date_str}")
        if not data:
            print("❌ 服务器返回错误"); return 1
        # Server already includes git log
        all_commits = data.get('git_commits', {})
    else:
        raw = file_read()
        day = raw.get('log', {}).get(date_str, {})
        tasks = day.get('tasks', [])
        notes = day.get('notes', '')
        d = datetime.strptime(date_str, '%Y-%m-%d')
        w = ['一','二','三','四','五','六','日'][d.weekday()]
        all_commits = _get_git_log(date_str)
        data = {
            "date": date_str, "weekday": w, "tasks": tasks, "notes": notes,
            "stats": {
                "total_seconds": sum(t.get('seconds',0) for t in tasks),
                "done_count": sum(1 for t in tasks if t.get('done')),
                "total_count": len(tasks),
                "pending_count": sum(1 for t in tasks if not t.get('done'))
            },
            "git_commits": all_commits,
            "git_total": sum(len(v) for v in all_commits.values())
        }

    tasks = data.get('tasks', [])
    stats = data.get('stats', {})
    notes = data.get('notes', '')
    done = [t for t in tasks if t.get('done')]
    pending = [t for t in tasks if not t.get('done')]
    total_sec = stats.get('total_seconds', 0)
    h, m = total_sec // 3600, (total_sec % 3600) // 60
    git_total = data.get('git_total', 0)

    d = datetime.strptime(date_str, '%Y-%m-%d')
    w = ['一','二','三','四','五','六','日'][d.weekday()]
    print(f"\n📅 {date_str} 星期{w} 工作总结\n{'='*50}")

    if tasks:
        if done:
            print(f"\n✅ 已完成 ({len(done)}/{len(tasks)}):")
            for t in done:
                sec = t.get('seconds', 0)
                th, tm = sec // 3600, (sec % 3600) // 60
                ts = f' ({th}h{tm}m)' if th > 0 else (f' ({tm}m)' if tm > 0 else '')
                print(f"   ✓ {t['text']}{ts}")
        if pending:
            print(f"\n🔄 进行中 ({len(pending)}):")
            for t in pending:
                sec = t.get('seconds', 0)
                th, tm = sec // 3600, (sec % 3600) // 60
                ts = f' ({th}h{tm}m)' if th > 0 else (f' ({tm}m)' if tm > 0 else '')
                print(f"   ○ {t['text']}{ts}")
    else:
        print("\n📝 今日暂无任务")

    if total_sec > 0: print(f"\n⏱ 总时长: {h}小时{m}分钟")
    if git_total > 0:
        print(f"\n📦 Git 提交 ({git_total} 个):")
        for repo, commits in all_commits.items():
            print(f"   📁 {repo}")
            for c in commits[:8]: print(f"      {c}")

    if notes: print(f"\n📄 笔记:\n   {notes[:500]}{'...' if len(notes)>500 else ''}")

    # Summary line
    parts = []
    if done: parts.append(f"完成了 {len(done)} 项任务")
    if pending: parts.append(f"{len(pending)} 项进行中")
    if total_sec > 0: parts.append(f"耗时 {h}h{m}m")
    if git_total > 0: parts.append(f"提交了 {git_total} 个 commit")
    print(f"\n{'─'*50}")
    print(f"📌 {'，'.join(parts) if parts else '暂无工作记录'}")
    print()
    return 0

def stats(month=None, year=None):
    now = datetime.now()
    if month is None: month = now.month
    if year is None: year = now.year

    if server_ok():
        data = server_get(f"/stats?month={month}&year={year}")
    else:
        raw = file_read()
        log = raw.get('log', {})
        days = sec = done = total = 0
        for ds, day in log.items():
            try: d = datetime.strptime(ds, '%Y-%m-%d')
            except: continue
            if d.year == year and d.month == month:
                tasks = day.get('tasks', [])
                if tasks or day.get('notes','').strip(): days += 1
                total += len(tasks)
                done += sum(1 for t in tasks if t.get('done'))
                sec += sum(t.get('seconds',0) for t in tasks)
        h, m = sec // 3600, (sec % 3600) // 60
        data = {"year":year,"month":month,"days":days,"total_tasks":total,"done":done,"total_seconds":sec,"hours":h,"minutes":m}

    if not data: print("❌ 无法获取数据"); return 1

    m_names = ['','一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月']
    h, m = data.get('hours',0), data.get('minutes',0)
    days = data.get('days', 0)
    total_t = data.get('total_tasks', 0)
    done = data.get('done', 0)

    print(f"\n📊 {data['year']}年 {m_names[data['month']]} 工作统计\n{'='*40}")
    print(f"  记录天数: {days} 天")
    print(f"  总任务数: {total_t}")
    print(f"  已完成:   {done}")
    if total_t: print(f"  完成率:   {done*100//total_t}%")
    print(f"  总时长:   {h}小时{m}分钟")
    if days > 0:
        avg = data.get('total_seconds',0) / days
        ah, am = int(avg)//3600, (int(avg)%3600)//60
        print(f"  日均时长: {ah}h{am}m")
    print()
    return 0

def gitlog(date_str=None):
    if date_str is None: date_str = datetime.now().strftime('%Y-%m-%d')
    commits = _get_git_log(date_str)
    total = sum(len(v) for v in commits.values())
    if not total:
        print(f"\n📦 {date_str} — 无 git 提交\n"); return 0
    print(f"\n📦 {date_str} — {total} 个 commit")
    for repo, cs in commits.items():
        print(f"   📁 {repo}")
        for c in cs: print(f"      {c}")
    print()
    return 0

def write_summary(text, date_str=None, mode='append'):
    if date_str is None: date_str = datetime.now().strftime('%Y-%m-%d')
    if server_ok():
        r = server_post(f"/summary/{date_str}", {"text": text, "mode": mode})
        if r: print(f"✅ 已写入 {date_str} 笔记 (server)"); return 0
        print("⚠ 服务器写入失败，尝试直接写文件...")

    # Direct file write
    data = file_read()
    data.setdefault('log', {}).setdefault(date_str, {'tasks': [], 'notes': ''})
    day = data['log'][date_str]
    if mode == 'replace':
        day['notes'] = text
    else:
        ts = datetime.now().strftime('%H:%M')
        day['notes'] = (day.get('notes','') + f"\n\n### 🤖 自动总结 ({ts})\n{text}")
    file_write(data)
    print(f"✅ 已写入 {date_str} 笔记 (file)")
    return 0

def generate_summary(date_str=None, save=True):
    """Call the AI to generate a daily summary via the server."""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    if server_ok():
        print(f"🤖 正在调用 AI 生成 {date_str} 的工作总结...\n")
        result = server_post(f"/generate-summary/{date_str}", {"save": save})
        if result and result.get('summary'):
            print(result['summary'])
            if result.get('saved'):
                print(f"\n✅ 已保存到笔记 (model: {result.get('model', '?')})")
            return 0
        elif result and result.get('error'):
            print(f"❌ {result['error']}")
            if result.get('hint'):
                print(f"   {result['hint']}")
            return 1
        else:
            print("❌ 服务器返回为空")
            return 1
    else:
        print("❌ 服务器未运行，无法调用 AI 总结")
        print("   请先启动: python3 work-log-server.py &")
        return 1

def cmd_path():
    if server_ok():
        r = server_get("/ping")
        if r: print(r.get('file', str(DATA_FILE))); return 0
    print(str(DATA_FILE))
    return 0

def _get_git_log(date_str):
    """Get git log across repos under ~/Desktop/Research."""
    base = Path(os.path.expanduser("~/Desktop/Research"))
    repos = []
    if base.exists():
        for d in base.iterdir():
            if d.is_dir() and (d/'.git').exists(): repos.append(str(d))
        for d in base.iterdir():
            if d.is_dir() and not (d/'.git').exists():
                for sd in d.iterdir():
                    if sd.is_dir() and (sd/'.git').exists() and str(sd) not in repos:
                        repos.append(str(sd))
    all_commits = {}
    for repo in sorted(repos):
        try:
            r = subprocess.run(['git','-C',repo,'log','--since',f'{date_str} 00:00:00',
                '--until',f'{date_str} 23:59:59','--pretty=format:%h %s','--all','--no-merges'],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                lines = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
                if lines: all_commits[os.path.basename(repo)] = lines
        except: pass
    return all_commits


def usage():
    print(__doc__)
    return 1

def main():
    args = sys.argv[1:]
    if not args: return usage()
    cmd = args[0]

    if cmd == 'today':
        ds = args[1] if len(args)>1 and not args[1].startswith('--') else None
        return today(ds)
    elif cmd == 'summary':
        ds = None
        for i,a in enumerate(args):
            if a == '--date' and i+1 < len(args): ds = args[i+1]
        return summary(ds)
    elif cmd == 'stats':
        m = y = None
        for i,a in enumerate(args):
            if a == '--month' and i+1 < len(args): m = int(args[i+1])
            if a == '--year' and i+1 < len(args): y = int(args[i+1])
        return stats(m, y)
    elif cmd == 'gitlog':
        ds = args[1] if len(args)>1 else None
        return gitlog(ds)
    elif cmd == 'write-summary':
        if len(args) < 2: print("❌ 需要提供总结文本"); return 1
        text = args[1]; ds = None
        for i,a in enumerate(args):
            if a == '--date' and i+1 < len(args): ds = args[i+1]
        return write_summary(text, ds)
    elif cmd == 'generate-summary':
        ds = None; save = True
        for i, a in enumerate(args):
            if a == '--date' and i+1 < len(args): ds = args[i+1]
            if a == '--no-save': save = False
        return generate_summary(ds, save)
    elif cmd == 'path': return cmd_path()
    else:
        print(f"❌ 未知命令: {cmd}")
        return usage()

if __name__ == '__main__':
    sys.exit(main())
