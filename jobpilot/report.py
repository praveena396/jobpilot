"""Daily job list as an HTML page with clickable Apply links."""

from datetime import date
from html import escape
from pathlib import Path

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JobPilot — {title}</title>
<style>
  :root {{ --bg:#fff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --row:#f6f8fa;
          --link:#0969da; --good:#1a7f37; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#8d96a0; --line:#30363d; --row:#161b22;
            --link:#4493f8; --good:#3fb950; }}
  }}
  body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
         font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  p.sub {{ color:var(--muted); margin:0 0 16px; }}
  code {{ background:var(--row); padding:1px 5px; border-radius:4px; }}
  .wrap {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; min-width:760px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
           vertical-align:top; }}
  th {{ position:sticky; top:0; background:var(--bg); font-weight:600; }}
  tr:hover td {{ background:var(--row); }}
  td.id, td.fit {{ font-variant-numeric:tabular-nums; white-space:nowrap; }}
  td.fit {{ font-weight:600; }}
  a {{ color:var(--link); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  a.apply {{ display:inline-block; padding:4px 12px; border:1px solid var(--link);
            border-radius:6px; white-space:nowrap; }}
  tr.done td {{ opacity:.45; }}
  .yes {{ color:var(--good); font-weight:600; }}
  .muted {{ color:var(--muted); }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="sub">{done}/{target} applied today · {count} jobs · After applying, run
<code>jobpilot applied &lt;ID&gt;</code> (clicked rows are dimmed as a reminder)</p>
<div class="wrap"><table>
<thead><tr><th>ID</th><th>Fit</th><th>Company</th><th>Role</th><th>Location</th>
<th>Grad</th><th>Your skills it asks for</th><th></th></tr></thead>
<tbody>
{rows}
</tbody></table></div>
<script>
  // Dim rows whose Apply link was clicked (remembered in this browser only)
  const key = "jobpilot-clicked";
  let clicked = [];
  try {{ clicked = JSON.parse(localStorage.getItem(key) || "[]"); }} catch (e) {{}}
  document.querySelectorAll("tr[data-url]").forEach(tr => {{
    if (clicked.includes(tr.dataset.url)) tr.classList.add("done");
    tr.querySelectorAll("a").forEach(a => a.addEventListener("click", () => {{
      tr.classList.add("done");
      if (!clicked.includes(tr.dataset.url)) clicked.push(tr.dataset.url);
      try {{ localStorage.setItem(key, JSON.stringify(clicked.slice(-2000))); }} catch (e) {{}}
    }}));
  }});
</script>
</body>
</html>
"""

_GRAD = {"yes": '<span class="yes">yes</span>', "likely": "likely",
         "unknown": '<span class="muted">?</span>'}


def write_daily_html(rows: list[dict], path: Path, done: int, target: int, scope: str) -> Path:
    body = []
    for r in rows:
        url = escape(r["url"] or "", quote=True)
        skills = ", ".join(r["skills"]) if r.get("description") else (
            '<span class="muted">title only</span>')
        body.append(
            f'<tr data-url="{url}">'
            f'<td class="id">{r["id"]}</td>'
            f'<td class="fit">{r["match_score"]}</td>'
            f'<td>{escape(r["company"] or "")}</td>'
            f'<td><a href="{url}" target="_blank" rel="noopener">'
            f'{escape(r["title"] or "")}</a></td>'
            f'<td>{escape(r["location"] or "")}</td>'
            f'<td title="{escape(r.get("eligible_why") or "", quote=True)}">'
            f'{_GRAD.get(r.get("eligible", "unknown"), "?")}</td>'
            f"<td>{skills if not r.get('description') else escape(skills)}</td>"
            f'<td><a class="apply" href="{url}" target="_blank" rel="noopener">Apply ↗</a></td>'
            "</tr>"
        )
    title = f"Jobs to apply — {date.today().isoformat()} ({scope})"
    path.write_text(
        _PAGE.format(title=escape(title), done=done, target=target, count=len(rows),
                     rows="\n".join(body)),
        encoding="utf-8",
    )
    return path
