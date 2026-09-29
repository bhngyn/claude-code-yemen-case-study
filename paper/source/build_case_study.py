#!/usr/bin/env python3
"""Assemble claude_code_case_study.html from body.html + data.json + the analysis-paper CSS.
Run prep_data.py first (reads the session logs). Then:  python3 build_case_study.py
PDF:  python3 build_case_study.py --pdf   (headless Chrome)"""
import json, html, re, sys, subprocess, statistics, datetime as dt, os
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
D = json.load(open('data.json' if os.path.exists('data.json') else '../../prompts/ledger.json'))
S, L = D['sessions'], D['ledger']
css = open('base.css').read()   # design tokens + components (analysis-paper house style)
extra_css = open('extra.css').read()

# ---------- numbers (all computed from data.json, none typed by hand) ----------
typed = [r for r in L if r['kind'] == 'typed']
words = [len(r['text'].split()) for r in typed]
tot_tools = sum(s['tool_calls'] for s in S)
tot_out = sum(s['output_tokens'] for s in S)
NUM = dict(
    N_SESS=len(S), N_WORK=len(S) - 1, N_TYPED=len(typed), N_LEDGER=len(L), TOOLS=f'{tot_tools:,}',
    PER_PROMPT=f'{tot_tools / len(typed):.0f}', MED_WORDS=int(statistics.median(words)), MAX_WORDS=max(words),
    OUT_TOK=f'{tot_out:,}', OUT_TOK_M=f'{tot_out / 1e6:.2f} million',
    CACHE_READ=f"{sum(s['cache_read'] for s in S):,}", CACHE_READ_M=f"{sum(s['cache_read'] for s in S) / 1e6:.0f} million", CACHE_CREATE=f"{sum(s['cache_create'] for s in S):,}",
)
t0 = dt.datetime.fromisoformat(S[0]['first'].replace('Z', '+00:00'))
t1 = max(dt.datetime.fromisoformat(s['last'].replace('Z', '+00:00')) for s in S)
NUM['FILES_SENT'] = sum(s['tools'].get('SendUserFile', 0) for s in S)
NUM['ELAPSED_H'] = f'{(t1 - t0).total_seconds() / 3600:.0f}'

PHASES = [  # (key, label, session ids)
    ('P0', 'Phase 0: one coordinate to a candidate map', ['d86eefd2']),
    ('P1', 'Phase 1: retune, review, first analyst paper', ['007112a8', '75b23107', '448c7361', 'c66378c1']),
    ('P2', 'Phase 2: the analyst\'s hand labels', ['8d05f04e', '264fa09b']),
    ('P3', 'Phase 3: Earth Engine, the September front', ['7c12864d', '3981a117', 'a4e8eb74']),
    ('P4', 'Phase 4: Marib and the review tool', ['044a49f0', '7e6be4f9']),
]
sid2ph = {sid: k for k, _, sids in PHASES for sid in sids}
for k, _, sids in PHASES:
    NUM[k + '_TYPED'] = sum(1 for r in typed if r['sid'] in sids)
    NUM[k + '_TOOLS'] = sum(s['tool_calls'] for s in S if s['sid'] in sids)

def hrs(ts):
    return (dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) - dt.datetime(2026, 9, 21, 20, 0, tzinfo=dt.timezone.utc)).total_seconds() / 3600

SHORT = {  # short labels for the timeline
    'd86eefd2': 'Irrigation → timelapse → NDVI → scan', '007112a8': 'Move project to SSD',
    '75b23107': 'Latest Wayback pull, before/after', '448c7361': 'Retune the detection signature',
    'c66378c1': 'Analyst paper (asks questions)', '8d05f04e': 'Wayback before/after (hand KMZ)',
    '264fa09b': 'Labels → trenchkit package', '7c12864d': 'Earth Engine key (stub, forked)',
    '3981a117': 'Earth Engine → Sep 2026 front', 'a4e8eb74': 'Rerun on original region',
    '044a49f0': 'Marib front earthworks', '7e6be4f9': 'Wayback tile pack + review page'}

def fig_timeline():
    left, right, top, rh = 292, 800, 46, 24
    x = lambda h: left + (right - left) * h / 52.0
    H = top + rh * len(S) + 34
    o = [f'<svg viewBox="0 0 880 {H}" role="img" aria-label="Timeline of the twelve logged sessions between 21 and 23 September 2026, coloured by phase">']
    for h, lab in [(3.3, 'Mon 22 Sep 00:00Z'), (27.3, 'Tue 23 Sep 00:00Z'), (51.3, 'Wed 24 Sep')]:
        pass
    for h, lab in [(4, '22 Sep'), (28, '23 Sep')]:
        o.append(f'<line class="axis" x1="{x(h):.1f}" y1="{top - 8}" x2="{x(h):.1f}" y2="{H - 26}" stroke-dasharray="3 4"/>')
        o.append(f'<text class="faint" font-family="JetBrains Mono, monospace" font-size="10" x="{x(h) + 4:.1f}" y="{top - 14}">{lab} 00:00Z</text>')
    for i, s in enumerate(S):
        y = top + i * rh
        a, b = hrs(s['first']), hrs(s['last'])
        ph = sid2ph[s['sid']]
        w = max(x(b) - x(a), 3)
        o.append(f'<text x="{left - 8}" y="{y + 15}" text-anchor="end" font-family="Iowan Old Style, Georgia, serif" font-size="13.5">{html.escape(SHORT[s["sid"]])}</text>')
        o.append(f'<rect x="{x(a):.1f}" y="{y + 4}" width="{w:.1f}" height="15" rx="3" fill="var(--{ph.lower()})"/>')
        o.append(f'<text class="faint" x="{x(a) + w + 5:.1f}" y="{y + 15}" font-family="JetBrains Mono, monospace" font-size="10.5">{s["tool_calls"]} calls</text>')
    ly = H - 12
    lx = left
    for k, lab, _ in PHASES:
        o.append(f'<rect x="{lx}" y="{ly - 9}" width="11" height="11" rx="2" fill="var(--{k.lower()})"/>')
        short = lab.split(':')[0]
        o.append(f'<text x="{lx + 16}" y="{ly}" font-family="Iowan Old Style, Georgia, serif" font-size="11.5">{short}</text>')
        lx += 22 + len(short) * 6.4 + 22
    o.append('</svg>')
    return '\n'.join(o)

def fig_tools():
    tools = {}
    for s in S:
        for k, v in s['tools'].items(): tools[k] = tools.get(k, 0) + v
    nice = {'Bash': 'Bash (run commands, scripts)', 'Read': 'Read (files and its own images)', 'mcp__Claude_Browser__browser_batch': 'Browser pane (check rendered pages)',
            'SendUserFile': 'SendUserFile (deliver a file)', 'WebFetch': 'WebFetch (read a page)', 'WebSearch': 'WebSearch', 'Write': 'Write (new files)',
            'mcp__Claude_Browser__preview_start': 'Preview server start', 'ToolSearch': 'ToolSearch (load a tool)', 'Monitor': 'Monitor (wait on a job)'}
    top = sorted(tools.items(), key=lambda kv: -kv[1])[:10]
    rest = tot_tools - sum(v for _, v in top)
    top.append(('other', rest)); nice['other'] = 'All others (11 kinds)'
    left, wmax, rh = 262, 520, 25
    H = 20 + rh * len(top) + 14
    o = [f'<svg viewBox="0 0 880 {H}" role="img" aria-label="Tool calls by type across all sessions">']
    for i, (k, v) in enumerate(top):
        y = 14 + i * rh
        w = wmax * v / top[0][1]
        o.append(f'<text x="{left - 10}" y="{y + 15}" text-anchor="end" font-family="Iowan Old Style, Georgia, serif" font-size="14.5">{html.escape(nice.get(k, k))}</text>')
        o.append(f'<rect x="{left}" y="{y + 3}" width="{max(w, 2):.1f}" height="17" rx="2" fill="var(--accent)" opacity="{0.95 if i == 0 else 0.62}"/>')
        o.append(f'<text class="muted" x="{left + w + 7:.1f}" y="{y + 16}" font-family="JetBrains Mono, monospace" font-size="12.5">{v}</text>')
    o.append('</svg>')
    return '\n'.join(o), sum(1 for k in tools) - 10

def fig_recall():
    o = ['<svg viewBox="0 0 880 340" role="img" aria-label="Two bar panels: recall gains from retuning, and which sensor maps found the hand-labelled trenches">']
    def panel(x0, title, rows, maxv, lab_w, note):
        o.append(f'<text x="{x0}" y="18" font-family="Iowan Old Style, Georgia, serif" font-size="14.5" font-style="italic" class="muted">{title}</text>')
        for i, (lab, v, accent, txt) in enumerate(rows):
            y = 34 + i * 48
            o.append(f'<text x="{x0}" y="{y + 12}" font-family="Iowan Old Style, Georgia, serif" font-size="13.5">{html.escape(lab)}</text>')
            w = (190) * v / maxv
            o.append(f'<rect x="{x0}" y="{y + 17}" width="{max(w, 2):.1f}" height="11" rx="2" fill="{"var(--accent)" if accent else "var(--ink-faint)"}" opacity="{0.9 if accent else 0.55}"/>')
            o.append(f'<text class="muted" x="{x0 + w + 6:.1f}" y="{y + 27}" font-family="JetBrains Mono, monospace" font-size="12">{txt}</text>')
        o.append(f'<text class="faint" x="{x0}" y="{34 + len(rows) * 48 + 4}" font-family="Iowan Old Style, Georgia, serif" font-size="12.5" font-style="italic">{note}</text>')
    panel(10, 'A. Site B main trench: share found at 0.5 % false alarms', [
        ('Radar, old 1-pixel kernel', 0.15, False, '0.15'),
        ('Radar, multi-width bank, registered', 0.54, True, '0.54'),
        ('Optical, 3-scene composites', 0.22, False, '0.22'),
        ('Optical, 25-scene composites (strip test)', 0.53, True, '0.53'),
        ('Optical, best step over 144 frames (strip test)', 0.63, True, '0.63')], 0.65, 0, 'Source: session 448c7361, 22 Sep 06:38Z summary table.')
    panel(455, 'B. 185 km of hand labels: share of label km found', [
        ('Radar change (61 px bar)', 0.34, True, '0.34 / 0.44 / 0.53'),
        ('Radar static brightness, 2026', 0.21, True, '0.21 / 0.30 / 0.44'),
        ('Optical appearance', 0.06, False, '0.06 / 0.10 / 0.19'),
        ('Optical red-band change', 0.01, False, '0.01 / 0.02 / 0.03')], 0.65, 0, 'Bar = 0.5 % false alarms; text = 0.5 / 1 / 2 %. Source: session 264fa09b summary.')
    o.append('</svg>')
    return '\n'.join(o)

def fig_loop():
    nodes = [  # id, cx, cy, who, title, sub
        (1, 440, 50, 'a', 'Frame', 'A coordinate, a file or a short question'),
        (2, 730, 126, 'c', 'Explore and build', 'Reads project and memory, writes scripts, runs jobs'),
        (3, 730, 274, 'c', 'Check itself', 'Looks at its own images; lists what it did not verify'),
        (4, 440, 350, 'c', 'Deliver a file', 'KML, offline HTML, contact sheet, GeoTIFF'),
        (5, 150, 274, 'a', 'Review and label', 'Verdicts, hand-traced lines, corrections'),
        (6, 150, 126, 'c', 'Persist', 'Memory notes, rebuild kit, updated README')]
    o = ['<svg viewBox="0 0 880 400" role="img" aria-label="Six-step working loop between analyst and Claude">',
         '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--ink-soft)"/></marker></defs>']
    bw, bh = 250, 76
    import math
    for i, n in enumerate(nodes):
        a, b = n, nodes[(i + 1) % 6]
        dx, dy = b[1] - a[1], b[2] - a[2]
        # clip the segment to the boxes
        def edge(c, dxu, dyu):
            tx = (bw / 2 + 4) / abs(dxu) if dxu else 1e9
            ty = (bh / 2 + 4) / abs(dyu) if dyu else 1e9
            t = min(tx, ty); return c[1] + dxu * t, c[2] + dyu * t
        ln = math.hypot(dx, dy); ux, uy = dx / ln, dy / ln
        sx, sy = edge(a, ux, uy); ex, ey = edge(b, -ux, -uy)
        o.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="var(--ink-soft)" stroke-width="1.6" marker-end="url(#arr)"/>')
    for i, cx, cy, who, t, sub in nodes:
        fill = 'var(--accent-soft)' if who == 'a' else 'var(--surface-2)'
        stroke = 'var(--accent)' if who == 'a' else 'var(--rule)'
        o.append(f'<rect x="{cx - bw / 2}" y="{cy - bh / 2}" width="{bw}" height="{bh}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
        import textwrap
        o.append(f'<text x="{cx}" y="{cy - 14}" text-anchor="middle" font-family="Iowan Old Style, Georgia, serif" font-size="16" font-weight="600">{i}. {t}</text>')
        for j, ln in enumerate(textwrap.wrap(sub, 36)[:2]):
            o.append(f'<text x="{cx}" y="{cy + 5 + j * 16}" text-anchor="middle" class="muted" font-family="Iowan Old Style, Georgia, serif" font-size="13">{html.escape(ln)}</text>')
    o.append('<text x="440" y="190" text-anchor="middle" font-family="Iowan Old Style, Georgia, serif" font-size="15" font-style="italic" class="muted">one lap = one short prompt</text>')
    o.append('<text x="440" y="214" text-anchor="middle" font-family="Iowan Old Style, Georgia, serif" font-size="12" class="faint">green boxes: analyst acts · grey boxes: Claude acts</text>')
    o.append('</svg>')
    return '\n'.join(o)

def kind_badge(k):
    cls = {'typed': '', 'terminal': ' warn', 'paste': ' warn', 'slash': ' warn', 'form': ''}[k]
    label = {'typed': 'typed', 'terminal': 'terminal', 'paste': 'paste', 'slash': 'slash', 'form': 'form answer'}[k]
    return f'<span class="badge{cls}">{label}</span>'

def esc_br(t): return html.escape(t).replace('\n', '<br>')

def ledger_html():
    rows = []
    for r in L:
        rows.append(f'<tr><td class="num mono">{r["n"]}</td><td class="mono nowrap">{r["ts"][5:16].replace("T", " ")}Z</td><td class="mono">{r["sid"]}</td><td>{kind_badge(r["kind"])}</td><td class="ledger-text">{esc_br(r["text"])}</td></tr>')
    return '<table class="ledger"><thead><tr><th class="num">#</th><th>Time (UTC)</th><th>Session</th><th>Kind</th><th>Verbatim text</th></tr></thead><tbody>' + '\n'.join(rows) + '</tbody></table>'

def sessions_html():
    rows = []
    for s in S:
        n_t = sum(1 for r in typed if r['sid'] == s['sid'])
        models = ', '.join(sorted({('Opus 5.5' if 'opus' in m else 'Fable 5.1') for m in s['models'] if m != '<synthetic>'}))
        rows.append(f'<tr><td class="mono">{s["sid"]}</td><td>{html.escape(s["title"])}</td><td class="mono nowrap">{s["first"][5:16].replace("T", " ")}</td><td class="mono nowrap">{s["last"][5:16].replace("T", " ")}</td>'
                    f'<td class="num">{n_t}</td><td class="num">{s["tool_calls"]}</td><td class="num">{s["output_tokens"]:,}</td><td>{models}</td></tr>')
    tt = f'<tr><td colspan="4"><strong>Total</strong></td><td class="num">{len(typed)}</td><td class="num">{tot_tools:,}</td><td class="num">{tot_out:,}</td><td></td></tr>'
    return ('<table class="sess-table"><thead><tr><th>Session</th><th>Title (as logged)</th><th>Start</th><th>End</th><th class="num">Typed</th><th class="num">Tool calls</th><th class="num">Output tokens</th><th>Model</th></tr></thead><tbody>'
            + '\n'.join(rows) + '</tbody><tfoot class="totals">' + tt + '</tfoot></table>')

def fmt(ts):
    d = dt.datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return d.strftime('%d %b %H:%M').lstrip('0') + 'Z'

def phases_html():
    rows = []
    for k, lab, sids in PHASES:
        first = min(s['first'] for s in S if s['sid'] in sids); last = max(s['last'] for s in S if s['sid'] in sids)
        rows.append(f'<tr><td><span class="dot" style="background:var(--{k.lower()})"></span><strong>{lab}</strong></td><td class="mono nowrap">{fmt(first)} → {fmt(last)}</td>'
                    f'<td class="num">{len(sids)}</td><td class="num">{NUM[k + "_TYPED"]}</td><td class="num">{NUM[k + "_TOOLS"]}</td></tr>')
    return '<table><thead><tr><th>Phase</th><th>Window (UTC)</th><th class="num">Sessions</th><th class="num">Typed prompts</th><th class="num">Tool calls</th></tr></thead><tbody>' + '\n'.join(rows) + '</tbody></table>'

def build():
    body = open('body.html').read()
    tools_svg, n_other = fig_tools()
    subs = {'FIG_TIMELINE': fig_timeline(), 'FIG_TOOLS': tools_svg, 'FIG_RECALL': fig_recall(), 'FIG_LOOP': fig_loop(),
            'LEDGER': ledger_html(), 'SESSIONS': sessions_html(), 'PHASES': phases_html()}
    for k, v in subs.items(): body = body.replace('{{' + k + '}}', v)
    for k, v in NUM.items(): body = body.replace('{{' + k + '}}', str(v))
    left = re.findall(r'\{\{([A-Z0-9_]+)\}\}', body)
    if left: sys.exit(f'unfilled placeholders: {sorted(set(left))}')
    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>One Coordinate, Three Days: a Claude Code case study</title>\n<style>' + css + '\n' + extra_css + '</style>\n</head>\n<body>\n' + body + '\n</body>\n</html>\n')
    out = '../claude_code_case_study.html'
    open(out, 'w').write(page)
    print('wrote', out, f'{len(page) / 1e6:.2f} MB')

if __name__ == '__main__':
    build()
    if '--pdf' in sys.argv:
        chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        src = 'file://' + os.path.abspath('../claude_code_case_study.html')
        pdf = os.path.abspath('../claude_code_case_study.pdf')
        subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-pdf-header-footer', '--print-to-pdf=' + pdf, src], check=True, capture_output=True)
        print('wrote', pdf, f'{os.path.getsize(pdf) / 1e6:.2f} MB')
