"""Phase C — the one-page AI Rework Report.

Self-contained HTML: inline CSS, inline SVG brand mark, system font stack,
zero external resources (local-first guardrail — the only outbound link is
the commensa.ai CTA, and it's a plain <a>).

Structure (SPEC.md + Gate B decisions, reviews/gateB_redteam.md):
- waste headline = TWO lines side by side — rework tax and superseded work —
  never merged into one number (Matt, 2026-06-09)
- three evidence panels: churn clusters, supersession, survival
- honest-limits footer sourced FROM rework.py's module docstring at render
  time (single source of truth, can't drift)
- the Durable = strip: the brand mark drawn with the repo's real numbers
- CTA: "want this continuously, with the cost side? commensa.ai"
"""

from __future__ import annotations

import html
from datetime import date

from jinja2 import Environment

from . import __version__
from . import rework

# Brand (../marketing/brand.md, vendored so the report stays self-contained):
INK = "#1d2b4d"
INK_DEEP = "#152138"
TEAL = "#18a06b"
MUTED = "#5b6770"
BG = "#f6f7f9"
TAGLINE = "measure the durable work, not the noise."

# ../marketing/commensa_mark.svg (the Durable =), resized for the header.
MARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="40" height="40" role="img" aria-label="Commensa — the Durable Equals">
  <defs><linearGradient id="t" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22325a"/><stop offset="1" stop-color="#152138"/></linearGradient></defs>
  <rect width="200" height="200" rx="44" fill="url(#t)"/>
  <g fill="#ffffff">
    <rect x="46" y="74" width="26" height="18" rx="9" fill-opacity="0.92"/>
    <rect x="80" y="74" width="30" height="18" rx="9" fill-opacity="0.55"/>
    <rect x="118" y="74" width="14" height="18" rx="7" fill-opacity="0.35"/>
    <rect x="140" y="74" width="14" height="18" rx="7" fill-opacity="0.20"/>
  </g>
  <rect x="46" y="108" width="108" height="18" rx="9" fill="#18a06b"/>
</svg>"""


def honest_limits() -> list[str]:
    """The 'Honest limits' bullets straight out of rework.py's docstring —
    the footer can never drift from the method's own documentation."""
    lines, capture = [], False
    for raw in (rework.__doc__ or "").splitlines():
        s = raw.strip()
        if s.startswith("Honest limits"):
            capture = True
            continue
        if capture:
            if s.startswith("- "):
                lines.append(s[2:])
            elif lines and s and not s.startswith("-"):
                lines[-1] += " " + s
            elif not s and lines:
                break
    return lines


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Rework Report — {{ repo }}</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; margin: 0; }
  body { background:{{ BG }}; color:{{ INK }}; font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif; padding:28px 16px; }
  .page { max-width:860px; margin:0 auto; }
  header { display:flex; align-items:center; gap:14px; margin-bottom:6px; }
  .word { font-size:22px; font-weight:600; letter-spacing:-0.02em; }
  .tag  { color:{{ MUTED }}; font-size:13px; }
  .meta { margin-left:auto; text-align:right; color:{{ MUTED }}; font-size:12.5px; }
  .meta b { color:{{ INK }}; font-size:14px; }
  h1 { font-size:19px; margin:22px 0 10px; letter-spacing:-0.01em; }
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:0.06em; color:{{ MUTED }}; margin-bottom:8px; }
  .cards2 { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  @media (max-width:640px){ .cards2 { grid-template-columns:1fr; } }
  .card { background:#fff; border:1px solid #e4e7ec; border-radius:14px; padding:18px 20px; }
  .big { font-size:40px; font-weight:700; letter-spacing:-0.03em; line-height:1.1; }
  .big small { font-size:17px; font-weight:600; color:{{ MUTED }}; letter-spacing:0; }
  .sub { color:{{ MUTED }}; font-size:13.5px; margin-top:6px; }
  .est { margin-top:10px; padding:8px 12px; background:{{ BG }}; border-radius:9px; font-size:13.5px; }
  .est b { color:{{ INK }}; }
  .norms { margin-top:10px; padding-top:8px; border-top:1px dashed #e4e7ec; color:{{ MUTED }}; font-size:12px; }
  .strip { margin-top:14px; background:#fff; border:1px solid #e4e7ec; border-radius:12px; padding:12px 16px; display:grid; gap:6px; font-size:13.5px; }
  .strip b { font-size:16px; }
  .durable { background:linear-gradient(135deg,#22325a,{{ INK_DEEP }}); border-radius:14px; padding:20px 24px; margin-top:14px; color:#fff; }
  .durable .lbl { font-size:12px; letter-spacing:0.05em; text-transform:uppercase; opacity:.75; margin-bottom:6px; }
  .barrow { display:flex; gap:6px; height:16px; margin:6px 0 4px; }
  .frag { border-radius:8px; min-width:8px; }
  .solid { height:16px; border-radius:8px; background:{{ TEAL }}; margin-top:12px; }
  .panel3 { display:grid; grid-template-columns:1fr; gap:14px; margin-top:14px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; color:{{ MUTED }}; font-weight:600; padding:4px 8px 4px 0; border-bottom:1px solid #e4e7ec; }
  td { padding:5px 8px 5px 0; border-bottom:1px solid #f0f2f5; vertical-align:top; }
  .pct { font-variant-numeric:tabular-nums; white-space:nowrap; }
  .pill { display:inline-block; padding:1px 8px; border-radius:99px; font-size:11.5px; font-weight:600; }
  .pill.c { background:#fdeeee; color:#b33; }
  .pill.g { background:#e9f6f0; color:{{ TEAL }}; }
  .quiet { color:{{ MUTED }}; }
  .ctx { display:flex; flex-wrap:wrap; gap:18px; font-size:13px; color:{{ MUTED }}; margin-top:14px; padding:12px 16px; background:#fff; border:1px solid #e4e7ec; border-radius:12px; }
  .ctx b { color:{{ INK }}; display:block; font-size:16px; }
  details { margin-top:14px; }
  summary { cursor:pointer; color:{{ MUTED }}; font-size:13px; }
  footer { margin-top:22px; font-size:12.5px; color:{{ MUTED }}; }
  footer ul { margin:6px 0 0 18px; padding:0; }
  footer li { margin-bottom:3px; }
  .cta { margin-top:16px; background:{{ INK }}; color:#fff; border-radius:14px; padding:16px 20px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  .cta a { color:#7be0b4; font-weight:700; text-decoration:none; font-size:16px; }
  .cta .fine { font-size:12px; opacity:.75; flex-basis:100%; }
</style></head><body><div class="page">

<header>
  {{ mark|safe }}
  <div><div class="word">commensa</div><div class="tag">{{ tagline }}</div></div>
  <div class="meta"><b>AI Rework Report</b><br>{{ repo }}<br>{{ generated }} · {{ total_prs }} PRs · {{ window }}-day window</div>
</header>

<h1>The waste, in two lines</h1>
<div class="cards2">
  <div class="card">
    <h2>1 · Rework tax — correcting its own work</h2>
    <div class="big">{{ rt.pct_prs_corrective }}%<small> of PRs</small></div>
    <div class="sub"><b>{{ rt.corrective_prs }} of {{ rt.total_prs }}</b> PRs — {{ rt.pct_changed_lines_corrective }}% of all changed lines — were corrective:
      {{ rt.by_signal.get('explicit', 0) }} said so in the title, {{ rt.by_signal.get('self_correction', 0) }} mostly deleted week-old work, {{ rt.by_signal.get('churn_cluster', 0) }} sat in churn chains.</div>
    {% if rt.estimated_rework_cost_usd %}<div class="est">≈ <b>${{ "{:,.0f}".format(rt.estimated_rework_cost_usd) }}</b> of effort — <i>estimate</i>, basis: {{ rt.estimate_basis }}</div>{% endif %}
    <div class="norms">How to read this: external research on the related <i>{{ norms.metric }}</i> calls {{ norms.healthy }} healthy; {{ norms.ai_vs_human }}. <b>{{ norms.label }}.</b></div>
  </div>
  <div class="card">
    <h2>2 · Superseded — work that didn't last</h2>
    <div class="big">{{ superseded|length }}<small> PRs replaced</small></div>
    <div class="sub">Entirely or mostly rewritten by later PRs within {{ window }} days{% if superseded %} — {{ superseded_lines }} lines of finished, merged work discarded{% endif %}.
      A different failure mode than correction; the two numbers are shown together, never merged.</div>
  </div>
</div>

<div class="strip">
  <div><b>{{ abandoned.count }}</b> attempt{{ "s" if abandoned.count != 1 }} shipped nothing
    <span class="quiet">— PRs closed without merging ({{ abandoned.pct_of_prs }}% of all PRs; the waste merge-based metrics never see{% if abandoned.in_flight_open_prs %}; {{ abandoned.in_flight_open_prs }} open PRs in flight, not counted{% endif %})</span></div>
  <div><b>at least {{ ai.pct_of_prs_lower_bound }}%</b> agent-marked
    <span class="quiet">— {{ ai.count }} of {{ total_prs }} PRs carry agent markers (Co-Authored-By trailers / body signatures); lower bound, absence of a marker ≠ human</span></div>
</div>

<div class="durable">
  <div class="lbl">what the agents generated</div>
  <div class="barrow">
    {% for f in fragments %}<div class="frag" style="flex:{{ f.share }};background:#fff;opacity:{{ f.opacity }}" title="{{ f.label }}: {{ f.pct }}%"></div>{% endfor %}
  </div>
  <div style="font-size:12px;opacity:.8">{% for f in fragments %}{{ f.label }} {{ f.pct }}%{% if not loop.last %} · {% endif %}{% endfor %}</div>
  <div class="lbl" style="margin-top:14px">what survived</div>
  <div class="solid" style="width:{{ survival_pct }}%"></div>
  <div style="font-size:12px;opacity:.8;margin-top:4px">{% if has_lines %}{{ survival_pct }}% of attributable merged lines still live at measurement{% else %}no merged PR lines to measure yet{% endif %}</div>
</div>

<div class="panel3">
  <div class="card">
    <h2>Evidence · churn clusters — N PRs to get one thing right</h2>
    {% if clusters %}{% for c in clusters %}
      <p style="margin-bottom:6px"><b>{{ c.members|length }} PRs</b> rewriting each other around <code>{{ c.top_files[0] }}</code> ({{ c.internal_rework_lines }} lines of internal rework):</p>
      <table><tr><th>PR</th><th>title</th></tr>
      {% for m in c.members %}<tr><td class="pct">{{ m }}</td><td>{{ titles.get(m, '') }}</td></tr>{% endfor %}</table>
      {% if not loop.last %}<hr style="border:none;border-top:1px solid #f0f2f5;margin:10px 0">{% endif %}
    {% endfor %}{% else %}<p class="quiet">No churn clusters — no chains of PRs substantially rewriting each other inside the window.</p>{% endif %}
  </div>

  <div class="card">
    <h2>Evidence · supersession — who replaced whom</h2>
    {% if superseded %}<table><tr><th>PR</th><th>title</th><th>replaced</th><th>mainly by</th></tr>
    {% for uid, s in superseded.items() %}<tr><td class="pct">{{ uid }}</td><td>{{ titles.get(uid, '') }}</td><td class="pct">{{ (s.frac * 100)|round|int }}%</td><td class="pct">{{ s.mainly }}</td></tr>{% endfor %}
    </table>{% else %}<p class="quiet">No PR had a majority of its lines replaced within the window.</p>{% endif %}
  </div>

  <div class="card">
    <h2>Evidence · hotspots — where the rework concentrates</h2>
    {% if hotspots.top %}<table><tr><th>module (top-level dir)</th><th>PRs touching</th><th>corrective</th><th>vs repo-wide {{ rt.pct_prs_corrective }}%</th></tr>
    {% for h in hotspots.top %}<tr><td><code>{{ h.dir }}</code></td><td class="pct">{{ h.prs }}</td><td class="pct">{{ h.pct_corrective }}%</td>
      <td class="pct">{{ "+" if h.pct_corrective > rt.pct_prs_corrective }}{{ (h.pct_corrective - rt.pct_prs_corrective)|round(1) }} pts</td></tr>{% endfor %}
    </table>
    <p class="quiet" style="margin-top:6px;font-size:12.5px">PRs are evidence; modules are decisions — a PR counts in every top-level directory it touches{% if hotspots.suppressed_dirs %}; {{ hotspots.suppressed_dirs }} dir{{ "s" if hotspots.suppressed_dirs != 1 }} with &lt;{{ hotspots.min_prs }} PRs suppressed as noise{% endif %}.</p>
    {% else %}<p class="quiet">No directory has ≥{{ hotspots.min_prs }} PRs — repo too small for module-level hotspots.</p>{% endif %}
  </div>

  <div class="card">
    <h2>Evidence · survival — durability of merged lines</h2>
    <p><b>{{ survival_pct }}%</b> overall · median per-PR {{ median_pct }}{% if evaporated %} — lowest survivors:{% endif %}</p>
    {% if evaporated %}<table><tr><th>PR</th><th>title</th><th>added</th><th>survived</th></tr>
    {% for e in evaporated %}<tr><td class="pct">{{ e.uid }}</td><td>{{ e.title }}</td><td class="pct">{{ e.added }}</td><td class="pct">{{ e.pct }}%</td></tr>{% endfor %}
    </table>{% endif %}
    <p class="quiet" style="margin-top:6px;font-size:12.5px">{{ survival_method }}</p>
  </div>
</div>

<div class="ctx">
  <div><b>{{ vel.prs_per_week }}</b>PRs / week</div>
  <div><b>{{ vel.merge_rate }}%</b>merge rate</div>
  <div><b>{{ vel.size_lines_added.median }}</b>median PR (+lines)</div>
  <div><b>{{ vel.size_lines_added.p75 }}</b>p75 (+lines)</div>
  <div style="align-self:center">{{ vel.note }}</div>
</div>

<details><summary>Every PR, every verdict ({{ total_prs }} rows — transparency: each carries the signal that fired)</summary>
  <div class="card" style="margin-top:8px"><table>
  <tr><th>PR</th><th>title</th><th>verdict</th><th>why</th><th>survival</th></tr>
  {% for u in unit_rows %}<tr><td class="pct">{{ u.uid }}</td><td>{{ u.title }}</td>
    <td><span class="pill {{ 'c' if u.cls == 'corrective' else 'g' }}">{{ u.cls }}</span>{% if u.superseded_by %} <span class="quiet" style="font-size:11px">superseded by {{ u.superseded_by }}</span>{% endif %}</td>
    <td class="quiet">{{ u.why }}</td><td class="pct">{{ u.survival }}</td></tr>{% endfor %}
  </table></div>
</details>

<footer>
  <b>Method &amp; confidence — we grade our own certainty; no false precision.</b>
  <ul>
    <li>Classification is heuristic and transparent: every PR above carries the objective signal that fired (explicit title · self-correction · churn chain). No hand labels, no model attribution, no token or energy claims — git does not record them.</li>
    {% for l in limits %}<li>{{ l }}</li>{% endfor %}
    <li>Abandoned attempts: {{ abandoned.method }}</li>
    <li>Hotspots: {{ hotspots.method }}</li>
    <li>Agent-marked share: {{ ai.method }}</li>
    <li>The "how to read this" norms under the rework tax are {{ norms.label }}.</li>
    <li>Generated locally by commensa-audit v{{ version }} (read-only GitHub access; your data never left this machine).</li>
  </ul>
</footer>

<div class="cta">
  <div>Want this continuously, with the cost side?</div><a href="https://commensa.ai">commensa.ai</a>
  <div class="fine">This one-page audit is the free, open-source snapshot. The continuous version adds the spend numerator — cost per durable line, trending week over week.</div>
</div>

</div></body></html>"""


def render(audit: dict, units: list[dict]) -> str:
    env = Environment(autoescape=True)
    titles = {u["unit_id"]: _clip(u.get("raw_title") or u["title"], 80) for u in units}
    cls = audit["classifications"]
    surv = audit["survival"]["per_unit"]

    churn = lambda u: u["lines_added"] + u["lines_deleted"]  # noqa: E731
    total_added = sum(u["lines_added"] for u in units) or 1
    sup = audit["supersessions"]
    sup_ids = set(sup)
    corrective_added = sum(u["lines_added"] for u in units
                           if cls[u["unit_id"]]["classification"] == "corrective")
    sup_added = sum(u["lines_added"] for u in units
                    if u["unit_id"] in sup_ids and cls[u["unit_id"]]["classification"] != "corrective")
    rest = max(total_added - corrective_added - sup_added, 0)
    fragments = [
        dict(label="kept (generative)", share=rest, opacity=0.92,
             pct=round(100 * rest / total_added, 1)),
        dict(label="superseded only", share=sup_added, opacity=0.45,
             pct=round(100 * sup_added / total_added, 1)),
        dict(label="corrective", share=corrective_added, opacity=0.22,
             pct=round(100 * corrective_added / total_added, 1)),
    ]
    fragments = [f for f in fragments if f["share"] > 0] or fragments[:1]

    evaporated = sorted(
        (dict(uid=k, title=titles.get(k, ""), pct=round(100 * v),
              added=next((u["lines_added"] for u in units if u["unit_id"] == k), 0))
         for k, v in surv.items() if v is not None and v < 0.5
         and next((u["lines_added"] for u in units if u["unit_id"] == k), 0) >= 20),
        key=lambda e: e["pct"])[:5]

    unit_rows = []
    for u in units:
        c = cls[u["unit_id"]]
        s = surv.get(u["unit_id"])
        unit_rows.append(dict(
            uid=u["unit_id"], title=titles[u["unit_id"]],
            cls=c["classification"],
            why=c.get("detail") or ("no corrective signal" if u["merged"] else "not merged"),
            superseded_by=c.get("superseded_by"),
            survival=f"{round(100 * s)}%" if s is not None else "—"))

    med = audit["survival"]["median_rate"]
    return env.from_string(TEMPLATE).render(
        INK=INK, INK_DEEP=INK_DEEP, TEAL=TEAL, MUTED=MUTED, BG=BG,
        mark=MARK_SVG, tagline=TAGLINE, version=__version__,
        repo=audit["repo"], generated=date.today().isoformat(),
        window=audit["window_days"], total_prs=audit["rework_tax"]["total_prs"],
        rt=audit["rework_tax"], superseded=sup,
        superseded_lines=sum(s["lines"] for s in sup.values()),
        clusters=audit["churn_clusters"], titles=titles,
        fragments=fragments,
        survival_pct=round(100 * audit["survival"]["overall_rate"], 1),
        has_lines=any(v is not None for v in audit["survival"]["per_unit"].values()),
        median_pct=f"{round(100 * med)}%" if med is not None else "—",
        survival_method=audit["survival"]["method"],
        evaporated=evaporated, vel=audit["velocity_context"],
        abandoned=audit["abandoned"], hotspots=audit["hotspots"],
        ai=audit["ai_marked"], norms=audit["external_norms"],
        unit_rows=unit_rows, limits=honest_limits(),
    )


def _clip(s: str, n: int) -> str:
    s = html.unescape(s)
    return s if len(s) <= n else s[: n - 1] + "…"
