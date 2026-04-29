# IdeaScout

Local-first scouting infrastructure that monitors 15-30 sources daily, classifies posts via local LLM, and produces a Friday digest of profitable web app ideas.

## What it does

- **Polls** from Reddit subreddits, HackerNews, IndieHackers RSS, ProductHunt, GitHub Trending, and any RSS/JSON source you add
- **Classifies** every post using Ollama (local, free) on demand-signal dimensions: is this someone asking for a tool, what domain, urgency, solo-buildable?
- **Digests** weekly into a markdown file ranking the top candidates with the supporting evidence
- **Stores** everything in SQLite for cross-source synthesis later

## Stack

- Python 3.13 (stdlib-first)
- SQLite for storage
- Ollama (qwen2.5:14b) for classification — runs locally
- Next.js + Tailwind for the dashboard (Day 3)
- Windows Task Scheduler for automation (Day 4)

## Quick start

```bash
# install deps (only feedparser + pyyaml)
py -3.13 -m pip install -e .

# initialize the database
py -3.13 -m ideascout init

# poll all enabled sources
py -3.13 -m ideascout poll

# classify newly-ingested posts (Day 2)
py -3.13 -m ideascout classify

# generate this week's digest (Day 3)
py -3.13 -m ideascout digest
```

## Adding a new source

Edit `config/sources.yaml` — no code changes needed for any RSS or Reddit/HN-supported source.

```yaml
- name: r/SaaS
  type: reddit
  enabled: true
  config:
    subreddit: SaaS
    intent_phrases:
      - "does anyone know"
      - "I need a tool"
      - "alternative to"
```

## Project structure

```
IdeaScout/
├── ideascout/           # main package
│   ├── adapters/        # one per source type (reddit, rss, hn)
│   ├── db.py            # SQLite schema + queries
│   ├── ingest.py        # poll pipeline
│   └── cli.py           # argparse CLI
├── config/              # YAML config (sources, prefs, classifier)
├── data/                # SQLite DB + generated digests (gitignored)
├── dashboard/           # Next.js (Day 3)
└── tests/
```

## Status

- [x] Day 1 — scaffolding, schema, Reddit/HN/IH adapters, ingest pipeline
- [ ] Day 2 — Ollama classifier integration
- [ ] Day 3 — Friday digest generator + Next.js dashboard
- [ ] Day 4 — ProductHunt + GitHub Trending + PulseMCP adapters, Task Scheduler automation
