# One Coordinate, Three Days: a Claude Code case study

A methodology paper about how one analyst and [Claude Code](https://claude.com/claude-code) went from a single GPS coordinate to a repeatable satellite-imagery screening workflow for military earthworks in Yemen (21–23 September 2026). It includes the **exact prompts typed**, verbatim excerpts of the conversations that mattered, thirteen lessons, a catalogue of what went wrong, and a getting-started playbook.

**Read it:** [`paper/claude_code_case_study.pdf`](paper/claude_code_case_study.pdf) (34 pages) or [`paper/claude_code_case_study.html`](paper/claude_code_case_study.html) (self-contained, offline, light/dark, prints cleanly).

## At a glance

| | |
|---|---|
| Sessions logged | 12 (one is a 2-turn fork) |
| Typed prompts | 41 (median 17 words) |
| Tool calls | 989 (no subagents) |
| Elapsed | about 50 hours |
| Models | Claude Fable 5.1, then Claude Opus 5.5 from 22 Sep 22:41 UTC |

## What is in this repository

| Path | What it is |
|---|---|
| `paper/` | The paper in HTML and PDF. `paper/source/` rebuilds both. |
| `prompts/PROMPTS.md`, `prompts/ledger.json` | Every human input in time order, verbatim: typed prompts, terminal commands the analyst ran, slash commands, structured-question answers. |
| `trenchkit/` | The region-agnostic screening pipeline that came out of the project (16 modules, ~1,000 lines), its README and region configs. Code only. |

**Not included:** satellite data, imagery, hand-drawn label files (KMZ), generated maps and the project's other reports (about 32 GB in the working project).

## Rebuilding the paper

```bash
cd paper/source
python3 build_case_study.py          # writes ../claude_code_case_study.html (uses ../../prompts/ledger.json)
python3 build_case_study.py --pdf    # also prints the PDF with headless Google Chrome (macOS path in the script)
```

`prep_data.py` regenerates the ledger from local Claude Code session logs (`~/.claude/projects/...`); it only works on the machine that holds those logs, which is why the processed ledger is committed.

## Using trenchkit

See [`trenchkit/README.md`](trenchkit/README.md). Copy `regions/template.json`, set the bounding box and epochs, then run `python -m trenchkit.run regions/<region>.json --labels <labels>.kmz`. Earth Engine access is needed for fast fetching (`fetch_ee.py`). Paths in the configs and README point at the original working directory and should be edited.

## Read this before reusing anything

- **The imagery findings are not independently validated.** Confidence statements in the paper are Claude's own assessments at the time. Attribution of who built what rests on geography and timing and is rated moderate to low.
- **Exact locations and attribution are kept as recorded**, by the project owner's decision. Decide separately what you can responsibly publish if you adapt the method.
- **Redactions:** one Google Cloud project ID and one OAuth URL were removed from the prompt ledger, and pasted terminal output was omitted. File paths in prompts were left as typed.
- Screening output is a lead to be reviewed by a person, not proof.

## License

No license has been chosen, so all rights are reserved by default. Add one before inviting reuse.
