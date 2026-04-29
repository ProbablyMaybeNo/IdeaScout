# IdeaScout — Automation scripts

Windows Task Scheduler integration. After running the installer, IdeaScout
polls and classifies daily without intervention.

## Files

| File | Role |
|---|---|
| `run_poll_classify.bat`  | Daily wrapper. Calls `poll`, then `classify`. Logs to `data\logs\YYYY-MM-DD-poll-classify.log`. |
| `run_digest.bat`         | Weekly wrapper. Calls `digest` (stub until Day 3). Logs to `data\logs\YYYY-MM-DD-digest.log`. |
| `install_schedule.ps1`   | Registers two tasks under `\IdeaScout\` in Task Scheduler. Idempotent. |
| `uninstall_schedule.ps1` | Removes both tasks and the `\IdeaScout\` folder. |

## Install

From PowerShell at the project root (no admin needed):

```powershell
.\scripts\install_schedule.ps1
```

Defaults:
- **Daily Poll And Classify** — every day at 06:00
- **Weekly Digest** — every Friday at 07:00

Override times:

```powershell
.\scripts\install_schedule.ps1 -PollHour 7 -DigestHour 8 -DigestDayOfWeek Saturday
```

## Verify

```powershell
# List the tasks
Get-ScheduledTask -TaskPath '\IdeaScout\'

# Run the poll/classify task immediately (test run)
Start-ScheduledTask -TaskPath '\IdeaScout\' -TaskName 'Daily Poll And Classify'

# Watch the log it produces
Get-Content (Join-Path "data\logs" ((Get-Date -Format yyyy-MM-dd) + "-poll-classify.log")) -Tail 30 -Wait
```

## Uninstall

```powershell
.\scripts\uninstall_schedule.ps1
```

## What gets logged

Each run writes a single dated log file in `data\logs\`. Format:

```
=== Run started Tue 04/29/2026 06:00:01.42 ===
Polling enabled sources...
  [ok]   r/SaaS: fetched=12 new=3 dup=9
  [ok]   r/microsaas: fetched=8 new=1 dup=7
  ...
Poll complete: 13 sources, ... fetched, ... new, ... duplicates, 0 errors.
Classifier v1.0 model=qwen2.5:14b url=http://localhost:11434
Classifying 4 post(s)...
Classify complete: 4 ok, 0 failed. Total at version v1.0: 58.
=== Run finished Tue 04/29/2026 06:08:14.81 ===
```

Failure modes are noisy on purpose — every step that fails leaves a clear
breadcrumb.

## Troubleshooting

**Task fires but nothing happens** — check the log file for the day. If empty,
the wrapper couldn't find Python. Verify `py -3.13` resolves at the user level.

**Ollama unreachable in the log** — the classify step needs Ollama running.
On Windows, Ollama auto-starts at login by default; verify by visiting
http://localhost:11434/api/tags in a browser.

**Repeated "no posts to classify" after Day 1** — that's normal. Reddit/HN
intent-phrase filters are strict; you'll see 0-5 new matching posts on most
days. Volume picks up on weekdays after big releases or during conference
weeks.

**Battery drain concerns** — qwen2.5:14b classification at 6:00 AM on battery
will spin a GPU for ~5-15 minutes. The installer sets `AllowStartIfOnBatteries`
true — change it to false in the task's properties or re-run the installer
with edited settings if you'd rather skip on battery.
