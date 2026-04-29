"""Static HTML dashboard generator.

Renders current DB state into a single self-contained HTML file with
embedded CSS and minimal vanilla JS for table filtering/sort. No build step,
no server, no node_modules — open the file in any browser.

If/when a richer Next.js dashboard is needed, this static generator becomes
the print-friendly export view and the Next.js app reads from the same DB.
"""
from __future__ import annotations

import html
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ideascout.classifier import load_classifier_config
from ideascout.db import (
    classification_counts_since,
    domain_breakdown_since,
    get_latest_digest,
    list_demand_signals,
    list_enabled_sources,
    post_count_since,
    source_health_since,
)

DEFAULT_DASHBOARD_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "dashboard.html"
)
WINDOW_DAYS = 7


@dataclass(slots=True)
class DashboardResult:
    output_path: Path
    posts_in_window: int
    signals_in_window: int


def _esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def _render_signal_card(row: sqlite3.Row) -> str:
    tags = json.loads(row["domain_tags"] or "[]")
    score = row["total_score"]
    score_class = "score-high" if score >= 15 else ("score-mid" if score >= 12 else "score-low")
    tag_html = "".join(
        f'<span class="tag">{_esc(t)}</span>' for t in tags
    )
    summary = _esc(row["summary"]) or "<em>no summary</em>"
    posted = _esc(row["posted_at"] or row["scraped_at"])
    return f"""
    <article class="signal-card" data-tags="{_esc(','.join(tags))}" data-score="{score}">
      <header>
        <span class="score {score_class}">{score}/25</span>
        <span class="source">{_esc(row['source_name'])}</span>
        <span class="posted">{posted[:16]}</span>
      </header>
      <h3>{_esc(row['title'])}</h3>
      <p class="summary">{summary}</p>
      <div class="scores">
        <span title="urgency">u {row['urgency_score']}</span>
        <span title="solo-buildable">b {row['solo_buildable_score']}</span>
        <span title="workaround pain">w {row['workaround_pain']}</span>
        <span title="payment evidence">p {row['payment_evidence']}</span>
        <span title="niche specificity">n {row['niche_specificity']}</span>
        <span class="conf">conf {row['demand_confidence']:.2f}</span>
      </div>
      <div class="tags">{tag_html}</div>
      <a class="link" href="{_esc(row['url'])}" target="_blank" rel="noopener">view post →</a>
    </article>
    """


def _render_domain_bars(domain_rows: list[sqlite3.Row]) -> str:
    if not domain_rows:
        return "<p><em>No demand signals classified yet this week.</em></p>"
    max_count = max(int(r["signal_count"]) for r in domain_rows) or 1
    bars = []
    for r in domain_rows:
        n = int(r["signal_count"])
        pct = (n / max_count) * 100
        bars.append(
            f"""
            <div class="bar-row">
              <span class="bar-label">{_esc(r['domain'])}</span>
              <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>
              <span class="bar-value">{n}  <em>(avg {r['avg_score']})</em></span>
            </div>
            """
        )
    return "\n".join(bars)


def _render_source_table(source_rows: list[sqlite3.Row]) -> str:
    rows = []
    for r in source_rows:
        last = _esc(r["last_polled_at"] or "never")
        if r["last_error"]:
            status = f'<span class="status-err">err</span>'
        else:
            status = '<span class="status-ok">ok</span>'
        rows.append(
            f"""
            <tr>
              <td>{_esc(r['source_name'])}</td>
              <td>{_esc(r['source_type'])}</td>
              <td class="num">{r['posts_in_window']}</td>
              <td class="num">{r['signals_in_window'] or 0}</td>
              <td class="dim">{last[:19]}</td>
              <td>{status}</td>
            </tr>
            """
        )
    if not rows:
        return "<p><em>No sources enabled.</em></p>"
    return f"""
    <table class="src-table">
      <thead><tr>
        <th>Source</th><th>Type</th><th>Posts (7d)</th><th>Signals (7d)</th>
        <th>Last polled</th><th>Status</th>
      </tr></thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
    """


def generate_dashboard(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    output_path: Path = DEFAULT_DASHBOARD_PATH,
    signal_limit: int = 50,
) -> DashboardResult:
    cfg = load_classifier_config()
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    since_iso = since.isoformat()

    posts_in_window = post_count_since(conn, since_iso)
    counts = classification_counts_since(conn, cfg.version, since_iso)
    signals = list_demand_signals(
        conn,
        cfg.version,
        min_confidence=0.5,
        limit=signal_limit,
        since_iso=since_iso,
    )
    domain_rows = domain_breakdown_since(conn, cfg.version, since_iso)
    source_rows = source_health_since(conn, cfg.version, since_iso)
    enabled_sources = len(list_enabled_sources(conn))
    latest_digest = get_latest_digest(conn)

    signal_cards = "\n".join(_render_signal_card(r) for r in signals)
    if not signals:
        signal_cards = (
            '<p class="empty">No demand signals in the last 7 days. '
            'Check back tomorrow — corpus accumulates daily.</p>'
        )

    domain_bars = _render_domain_bars(domain_rows)
    source_table = _render_source_table(source_rows)

    if latest_digest:
        digest_link = f"data/digests/{_esc(latest_digest['week_iso'])}.md"
        digest_meta = (
            f"Latest digest: <strong>{_esc(latest_digest['week_iso'])}</strong> "
            f"<span class=\"dim\">(generated {_esc(latest_digest['generated_at'])})</span>"
        )
    else:
        digest_link = ""
        digest_meta = '<em>No digest generated yet — run `ideascout digest`.</em>'

    generated_iso = now.strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>IdeaScout Dashboard — {_esc(generated_iso)}</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    :root {{
      --bg:        #0d1117;
      --panel:     #161b22;
      --border:    #30363d;
      --text:      #e6edf3;
      --dim:       #8b949e;
      --accent:    #58a6ff;
      --score-hi:  #3fb950;
      --score-mid: #d29922;
      --score-lo:  #6e7681;
      --tag-bg:    #1f6feb22;
      --tag-fg:    #58a6ff;
      --err:       #f85149;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "JetBrains Mono", monospace;
      background: var(--bg); color: var(--text);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px 64px; }}
    h1 {{ font-size: 24px; margin: 0 0 4px; font-weight: 600; }}
    h2 {{ font-size: 18px; margin: 32px 0 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
    h3 {{ font-size: 15px; margin: 8px 0; font-weight: 500; }}
    .dim {{ color: var(--dim); }}
    .meta {{ color: var(--dim); font-size: 12px; margin-bottom: 24px; }}

    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }}
    .stat {{ padding: 12px 16px; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; }}
    .stat .num {{ font-size: 24px; font-weight: 600; }}
    .stat .label {{ color: var(--dim); font-size: 12px; }}

    .controls {{ display: flex; gap: 8px; align-items: center; margin: 16px 0; }}
    .controls input, .controls select {{
      background: var(--panel); border: 1px solid var(--border); color: var(--text);
      padding: 6px 10px; border-radius: 4px; font: inherit;
    }}

    .signals {{ display: grid; gap: 12px; }}
    .signal-card {{
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 6px; padding: 14px 16px;
    }}
    .signal-card header {{
      display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
      font-size: 12px; color: var(--dim); margin-bottom: 6px;
    }}
    .score {{
      font-weight: 600; padding: 2px 8px; border-radius: 4px;
      background: var(--panel); border: 1px solid var(--border);
    }}
    .score-high {{ color: var(--score-hi); border-color: var(--score-hi); }}
    .score-mid  {{ color: var(--score-mid); border-color: var(--score-mid); }}
    .score-low  {{ color: var(--score-lo); border-color: var(--border); }}
    .source {{ font-weight: 500; color: var(--text); }}
    .posted {{ font-family: "JetBrains Mono", monospace; }}
    .summary {{ margin: 4px 0 8px; }}
    .scores {{ display: flex; gap: 12px; flex-wrap: wrap; font-family: "JetBrains Mono", monospace; font-size: 12px; color: var(--dim); margin-bottom: 8px; }}
    .scores .conf {{ color: var(--accent); }}
    .tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }}
    .tag {{
      background: var(--tag-bg); color: var(--tag-fg); border: 1px solid var(--tag-fg);
      padding: 1px 8px; border-radius: 999px; font-size: 11px;
    }}
    .link {{ font-size: 12px; }}

    .bar-row {{ display: grid; grid-template-columns: 160px 1fr 120px; gap: 12px; align-items: center; margin: 4px 0; }}
    .bar-label {{ font-family: "JetBrains Mono", monospace; font-size: 12px; }}
    .bar-track {{ height: 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }}
    .bar-fill {{ height: 100%; background: var(--accent); }}
    .bar-value {{ font-size: 12px; color: var(--dim); }}

    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); font-size: 13px; }}
    th {{ color: var(--dim); font-weight: 500; }}
    td.num {{ text-align: right; font-family: "JetBrains Mono", monospace; }}
    td.dim {{ color: var(--dim); font-family: "JetBrains Mono", monospace; font-size: 12px; }}
    .status-ok {{ color: var(--score-hi); }}
    .status-err {{ color: var(--err); }}

    .empty {{ color: var(--dim); padding: 24px; text-align: center; background: var(--panel); border: 1px dashed var(--border); border-radius: 6px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>IdeaScout Dashboard</h1>
    <div class="meta">Generated {_esc(generated_iso)} · classifier {_esc(cfg.version)} · window: last {WINDOW_DAYS} days</div>

    <div class="stats">
      <div class="stat"><div class="num">{posts_in_window}</div><div class="label">posts ingested (7d)</div></div>
      <div class="stat"><div class="num">{counts['classified']}</div><div class="label">classified</div></div>
      <div class="stat"><div class="num">{counts['demand']}</div><div class="label">demand signals</div></div>
      <div class="stat"><div class="num">{counts['high_conviction']}</div><div class="label">high-conviction</div></div>
      <div class="stat"><div class="num">{enabled_sources}</div><div class="label">sources enabled</div></div>
    </div>

    <h2>Top demand signals</h2>
    <div class="controls">
      <input id="filter" placeholder="filter by tag or text…">
      <select id="min-score">
        <option value="0">all scores</option>
        <option value="12">score ≥ 12</option>
        <option value="15" selected>score ≥ 15 (high conviction)</option>
        <option value="18">score ≥ 18</option>
      </select>
    </div>
    <section class="signals" id="signals">
      {signal_cards}
    </section>

    <h2>Domain breakdown</h2>
    {domain_bars}

    <h2>Source health</h2>
    {source_table}

    <h2>Latest digest</h2>
    <p>{digest_meta}</p>
    {f'<p><a href="{digest_link}">open digest markdown →</a></p>' if digest_link else ''}
  </div>

  <script>
    (function () {{
      const filter = document.getElementById('filter');
      const minScore = document.getElementById('min-score');
      const cards = Array.from(document.querySelectorAll('#signals .signal-card'));

      function apply() {{
        const q = (filter.value || '').toLowerCase();
        const min = parseInt(minScore.value, 10) || 0;
        let visible = 0;
        for (const c of cards) {{
          const score = parseInt(c.dataset.score, 10) || 0;
          const tags = (c.dataset.tags || '').toLowerCase();
          const text = c.textContent.toLowerCase();
          const ok = score >= min && (q === '' || tags.includes(q) || text.includes(q));
          c.style.display = ok ? '' : 'none';
          if (ok) visible++;
        }}
      }}
      filter.addEventListener('input', apply);
      minScore.addEventListener('change', apply);
      apply();
    }})();
  </script>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")

    return DashboardResult(
        output_path=output_path,
        posts_in_window=posts_in_window,
        signals_in_window=len(signals),
    )
