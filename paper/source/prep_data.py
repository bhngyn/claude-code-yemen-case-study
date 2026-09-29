#!/usr/bin/env python3
"""Reads the Claude Code session logs for the Yemen project and writes data.json
(sessions, prompt ledger, stats) plus PROMPTS.md. Secrets are redacted here."""
import json, glob, os, re, collections
ROOTS = [('/Users/brian/.claude/projects/-Users-brian-Documents-yemen-maps/', 'A'),
         ('/Users/brian/.claude/projects/-Volumes-T7-yemen-maps/', 'B')]
SKIP_SID = {'9d05dca0'}            # the session that wrote this paper
WINDOW_END = '2026-09-24T00:00:00'  # the study window closes at the end of 23 Sep (UTC); later sessions are out of scope
REDACT = [(r'applied-might-\d+-n\d+', '[GCP_PROJECT_ID]'),
          (r'https://accounts\.google\.com/o/oauth2/auth\S*', '[OAUTH_URL]')]
def redact(t):
    for pat, rep in REDACT: t = re.sub(pat, rep, t)
    return t
HARNESS = ('<task-notification', '<system-reminder', '<local-command-caveat', 'Base directory for this skill',
           '## Page contract', 'Your response above was cut off', 'Continue from where you left off', '[Image')
sessions, ledger = [], []
stats = collections.Counter()
for root, grp in ROOTS:
    for f in glob.glob(root + '*.jsonl'):
        sid = os.path.basename(f)[:8]
        if sid in SKIP_SID: continue
        try: title = json.load(open(f[:-6] + '/custom-title.json'))['customTitle']
        except Exception: title = ''
        first = last = None; tools = collections.Counter(); models = collections.Counter(); out_tok = 0; c_read = 0; c_make = 0; seen = set()
        rows = []; pend = {}
        for line in open(f):
            try: o = json.loads(line)
            except Exception: continue
            ts = o.get('timestamp')
            if ts: first = first or ts; last = ts
            m = o.get('message') or {}; c = m.get('content')
            if o.get('type') == 'assistant':
                mid = m.get('id')
                if mid and mid not in seen:
                    seen.add(mid); u = m.get('usage') or {}; out_tok += u.get('output_tokens', 0); c_read += u.get('cache_read_input_tokens', 0); c_make += u.get('cache_creation_input_tokens', 0); models[m.get('model')] += 1
                if isinstance(c, list):
                    for b in c:
                        if b.get('type') == 'tool_use':
                            tools[b['name']] += 1
                            if b['name'] == 'AskUserQuestion': pend[b['id']] = b['input']
            if o.get('type') == 'user' and isinstance(c, list):
                for b in c:
                    if b.get('type') == 'tool_result' and b.get('tool_use_id') in pend:
                        res = b.get('content')
                        if isinstance(res, list): res = '\n'.join(x.get('text', '') for x in res if isinstance(x, dict))
                        qs = ' | '.join(q['question'] for q in pend.pop(b['tool_use_id']).get('questions', []))
                        rows.append((ts, 'form', 'QUESTIONS: ' + qs + '\nANSWERS: ' + re.sub(r'^.*?answered: ?', '', str(res), flags=re.S).split(' You can now continue')[0].split(' Read the answers')[0]))
            if o.get('type') == 'user' and not o.get('isSidechain') and not o.get('isMeta'):
                txt = None
                if isinstance(c, str): txt = c
                elif isinstance(c, list):
                    if any(b.get('type') == 'tool_result' for b in c): continue
                    txt = '\n'.join(b.get('text', '') for b in c if b.get('type') == 'text')
                if not txt or not txt.strip(): continue
                t = txt.strip()
                if t.startswith(HARNESS): continue
                if t.startswith('<local-command-stdout>'): continue
                if t.startswith('<command-name>'):
                    name = re.search(r'<command-name>(.*?)</command-name>', t, re.S).group(1).strip()
                    args = re.search(r'<command-args>(.*?)</command-args>', t, re.S)
                    rows.append((ts, 'slash', f'{name} {args.group(1).strip() if args else ""}'.strip())); continue
                if t.startswith('<bash-input>'):
                    cmd = re.search(r'<bash-input>(.*?)</bash-input>', t, re.S).group(1).strip()
                    rows.append((ts, 'terminal', cmd)); continue
                if '<pasted_content' in t:
                    pre = re.sub(r'<pasted_content.*', '', t, flags=re.S).strip()
                    rows.append((ts, 'paste', pre + ' [pasted terminal error output omitted]')); continue
                rows.append((ts, 'typed', t))
        if first and first[:19] >= WINDOW_END: continue
        sessions.append(dict(sid=sid, group=grp, title=title, first=first, last=last, tool_calls=sum(tools.values()),
                             tools=dict(tools), models=dict(models), output_tokens=out_tok, cache_read=c_read, cache_create=c_make, n_rows=len(rows)))
        for ts, kind, text in rows:
            ledger.append(dict(sid=sid, ts=ts, kind=kind, text=redact(text)))
sessions.sort(key=lambda s: s['first']); ledger.sort(key=lambda r: r['ts'])
# drop the fork's duplicate first prompt (7c12864d is a 2-turn fork stub of 3981a117)
seen_txt = set(); clean = []
for r in ledger:
    key = (r['kind'], r['text'])
    if r['sid'] == '7c12864d' and key in {(x['kind'], x['text']) for x in ledger if x['sid'] == '3981a117'}: continue
    clean.append(r)
ledger = clean
for i, r in enumerate(ledger, 1): r['n'] = i
json.dump(dict(sessions=sessions, ledger=ledger), open('data.json', 'w'), indent=1)
kinds = collections.Counter(r['kind'] for r in ledger)
print(kinds, len(ledger)); 
for s in sessions: print(s['sid'], s['first'][5:16], s['last'][5:16], s['tool_calls'], s['output_tokens'], s['models'], s['title'])
with open('PROMPTS.md', 'w') as fh:
    fh.write('# Prompt ledger\n\nEvery human input in the 12 logged sessions, in time order (UTC). `typed` = typed into the chat; `terminal` = shell command the user ran themselves; `slash` = app command; `paste` = pasted output. Secrets are redacted (see notes in the paper).\n\n')
    cur = None
    for r in ledger:
        s = next(x for x in sessions if x['sid'] == r['sid'])
        if r['sid'] != cur:
            cur = r['sid']; fh.write(f"\n## Session {cur}: {s['title']}\n\n")
        fh.write(f"**#{r['n']} · {r['ts'][5:16].replace('T',' ')}Z · {r['kind']}**\n\n")
        fh.write('> ' + r['text'].replace('\n', '\n> ') + '\n\n')
