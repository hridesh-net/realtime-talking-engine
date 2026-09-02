"""Report rendering — JSON and a self-contained HTML page.

The HTML carries no external assets so a report can be mailed, archived or
opened offline years later and still read the same way.

Two audiences, one document. The default render is the two-page development
report a hiring manager and their coach read: a readiness index, four competency
cards in plain language, strengths against gaps, and a numbered list of things
to do differently. Passing ``detail=True`` appends the working — every signal
with its measurement, every question act, the bias check, and the full basis
panel — for the trainer who needs to check a number rather than act on it.

The working is *appended*, never substituted, and the report is a pure function
of the stored JSON either way. That is what lets the detail be a query parameter
on the HTML endpoint instead of a second stored artifact: there is exactly one
set of numbers, shown at two depths.
"""

from __future__ import annotations

import html
import json

from report_engine.narrate import out_of_four
from report_engine.schema import AssessmentReport, CriterionScore, Finding, SignalResult

#: Glyph per rubric criterion. Text glyphs rather than an icon font because the
#: page has to survive being mailed as a single file with no external assets.
_ICONS = {
    "clarity": "◎",
    "structure": "▤",
    "fairness": "⚖",
    "communication": "◍",
    "communication_english": "◍",
}

#: What a question act's type is called in front of a reader, and whether it is
#: something to fix. The internal ids are the classifier's vocabulary, not the
#: manager's: nobody being coached should have to know what `double_barrelled`
#: means to read their own report.
_QUESTION_TYPE = {
    "behavioural": ("behavioural", ""),
    "situational": ("hypothetical", ""),
    "open_other": ("open", ""),
    "closed": ("closed", ""),
    "leading": ("leading", "bad"),
    "double_barrelled": ("two questions in one", "bad"),
}

#: What each measurement's provenance is called on the page, and the pill it
#: wears. A reader acting on a number is owed the difference between a count, a
#: model's reading of the audio, and a model's reading of the transcript.
_SOURCE_LABEL = {"measured": "counted", "assessed": "heard", "judged": "judged"}
_SOURCE_CLASS = {"measured": "", "assessed": "heard", "judged": "judged"}

_CSS = """
:root{--ink:#101828;--ink2:#475467;--ink3:#98a2b3;--line:#e4e7ec;--bg:#f9fafb;
--g:#12a150;--o:#e08700;--r:#d92d20;--b:#175cd3;--accent:#c2570c;--panel:#eff6ff}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:30px 24px 48px}
.g{color:var(--g)}.o{color:var(--o)}.r{color:var(--r)}
.muted{color:var(--ink2)}.tiny{color:var(--ink3);font-size:12px}

/* --- masthead ---------------------------------------------------------- */
.eyebrow{font-size:11px;font-weight:700;letter-spacing:.12em;
text-transform:uppercase;color:var(--b);margin-bottom:10px}
.masthead{display:flex;justify-content:space-between;align-items:flex-start;gap:24px}
h1{font-size:25px;margin:0;letter-spacing:-.01em}
h1 span{font-size:16px;color:var(--ink2);font-weight:600;letter-spacing:0}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.chip{border:1px solid var(--line);border-radius:6px;padding:5px 10px;
font-size:12px;color:var(--ink2);white-space:nowrap}

/* --- section headers --------------------------------------------------- */
.sec{display:flex;align-items:center;gap:9px;margin:16px 0 9px;font-size:11px;
font-weight:700;letter-spacing:.11em;text-transform:uppercase;color:var(--b)}
.sec::before{content:"";width:17px;height:2px;border-radius:2px;
background:var(--accent);flex:0 0 auto}
.sec.plain{color:var(--ink2)}

/* --- summary ----------------------------------------------------------- */
.summary{background:var(--panel);border-left:4px solid var(--b);
border-radius:0 8px 8px 0;padding:2px 20px 13px}
.summary .sec{margin:13px 0 8px}
.summary p{margin:0;font-weight:600;line-height:1.65}

/* --- competency cards -------------------------------------------------- */
.crit{background:#fff;border:1px solid var(--line);border-radius:10px;
padding:10px 14px;margin-bottom:7px}
.crit.flagged{border-color:#fecdca;background:#fffbfa}
.crit-top{display:flex;align-items:flex-start;gap:11px}
.ico{width:30px;height:30px;border-radius:8px;background:var(--panel);color:var(--b);
display:grid;place-items:center;font-size:15px;flex:0 0 auto}
.crit-name{flex:1 1 auto;min-width:0}
.crit-name b{font-size:15px}
.crit-name div{font-size:11.5px;color:var(--ink3);margin-top:2px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.crit-score{display:flex;align-items:center;gap:11px;flex:0 0 auto}
.wt{font-size:11.5px;color:var(--ink2);white-space:nowrap}
.pips{display:flex;gap:3px}
.pips i{width:21px;height:6px;border-radius:99px;background:var(--line);display:block}
.pips i.on{background:currentColor}
.out4{font-size:18px;font-weight:700;white-space:nowrap}
.narr{font-size:12.5px;color:var(--ink2);margin-top:7px;line-height:1.5}
.blist{margin:7px 0 0;padding:0;list-style:none}
.blist li{font-size:12.5px;padding:1px 0 1px 10px;border-left:2px solid var(--line);
margin-bottom:2px}
.blist li.positive{border-color:var(--g)}
.blist li.negative{border-color:var(--o)}
.strip{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.strip span{font-size:11px;padding:3px 8px;border-radius:5px;
border:1px solid var(--line);color:var(--ink2)}
.strip span.on{color:var(--g);border-color:#abefc6;background:#ecfdf3}
.strip span.off{color:var(--o);border-color:#fedf89;background:#fffaeb}

/* --- q and a ------------------------------------------------------------ */
.qcount{font-size:11px;letter-spacing:.03em;text-transform:uppercase;
color:var(--ink3);font-weight:700;padding-bottom:7px;border-bottom:1px solid var(--line)}
.qrow{display:flex;gap:10px;align-items:baseline;padding:7px 0;
border-bottom:1px solid var(--line);font-size:12.5px;line-height:1.45}
.qrow:last-child{border-bottom:0;padding-bottom:0}
.qat{flex:0 0 auto;color:var(--ink3);font-size:11.5px;font-variant-numeric:tabular-nums}
.qtext{flex:1 1 auto;min-width:0}
.qtag{flex:0 0 auto;display:flex;gap:4px}
.colhead+.card{margin-top:0}

/* --- strengths and gaps ------------------------------------------------ */
.cols{display:grid;grid-template-columns:1fr 1fr;gap:13px;align-items:start}
.colhead{font-size:11px;font-weight:700;letter-spacing:.1em;
text-transform:uppercase;margin-bottom:7px}
.colhead.s{color:var(--g)}.colhead.gp{color:var(--o)}
.item{background:#fff;border:1px solid var(--line);border-radius:8px;
padding:8px 11px;margin-bottom:6px;font-size:12.5px;line-height:1.5;color:var(--ink2)}
.item b{color:var(--ink)}
.item q{display:block;margin-top:6px;font-size:11.5px;color:var(--ink3);
font-style:italic;quotes:'"' '"'}

/* --- areas to improve -------------------------------------------------- */
.area{background:#fff;border:1px solid var(--line);border-radius:10px;
padding:10px 13px;margin-bottom:6px;display:flex;gap:10px;align-items:flex-start}
.num{width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;
font-size:12px;font-weight:700;display:grid;place-items:center;flex:0 0 auto}
.area h3{margin:0 0 2px;font-size:13.5px}
.area p{margin:0;font-size:12.5px;color:var(--ink2);line-height:1.55}
.try{margin-top:7px;background:var(--bg);border:1px solid var(--line);
border-radius:6px;padding:5px 10px;font-size:12.5px}
.try b{color:var(--g)}

/* --- footer ------------------------------------------------------------ */
.foot{margin-top:12px;padding-top:9px;border-top:1px solid var(--line);
text-align:center;font-size:10px;color:var(--ink3);line-height:1.55}
.foot b{color:var(--ink2)}

/* --- warnings ---------------------------------------------------------- */
.warn{background:#fffaeb;border:1px solid #fedf89;color:#93370d;padding:12px 16px;
border-radius:10px;margin-bottom:16px;font-size:13px;line-height:1.6}

/* --- the working (detail=True only) ------------------------------------ */
.card{background:#fff;border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin-bottom:12px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);
vertical-align:top}
th{color:var(--ink2);font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.04em}
.scroll{overflow-x:auto}
blockquote{margin:8px 0 0;padding:8px 12px;border-left:3px solid var(--line);
background:var(--bg);color:var(--ink2);font-size:12.5px;border-radius:0 6px 6px 0}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;
font-weight:600;border:1px solid var(--line);color:var(--ink2);background:#fff}
.pill.bad{color:var(--r);border-color:#fecdca;background:#fef3f2}
.pill.good{color:var(--g);border-color:#abefc6;background:#ecfdf3}
.pill.heard{color:#5925dc;border-color:#d9d6fe;background:#f4f3ff}
.pill.judged{color:#0e7490;border-color:#a5e8f0;background:#ecfeff}
.basis{background:#f8f9fc;border:1px solid var(--line);border-radius:10px;
padding:14px 18px;margin-bottom:12px;font-size:12.5px;color:var(--ink2);line-height:1.65}
.basis b{color:var(--ink)}
.basis ul{margin:8px 0 0;padding-left:18px}.basis li{margin-bottom:6px}
.alt{margin-top:8px;font-size:12.5px;background:var(--panel);
border:1px solid #b2ddff;border-radius:8px;padding:9px 12px}
.prov{font-size:11px;color:var(--ink3);margin-top:24px;line-height:1.8}

/* Print is a first-class output here: "download as PDF" is the browser's own
   print-to-PDF, so this stylesheet is what the saved document looks like.
   Keeping one renderer for screen and paper is why the report a trainer reads
   and the report they file cannot drift apart. */
@page{margin:13mm 11mm}
@media print{
  .wrap{max-width:none;padding:0}
  /* Sections flow rather than being pinned to a page. A forced break is only
     right if the content above it is guaranteed to fit, and it is not: a
     session where the judge writes a full narrative on all four cards needs
     slightly more than one page for the scorecard, and pinning the break there
     would leave a reader a page that is nine-tenths white. What is pinned is
     that nothing splits mid-card. */
  .break{break-before:auto}
  .pagebreak{break-before:page;page-break-before:always}
  /* A finding split across a page break loses its quote, which is the part
     that makes it checkable. */
  .crit,.item,.area,.card,blockquote,.alt,.summary{
    break-inside:avoid;page-break-inside:avoid}
  .sec{break-after:avoid;page-break-after:avoid}
  .scroll{overflow:visible}
  table{font-size:10.5px}
}
"""


def _e(text: str) -> str:
    return html.escape(str(text), quote=True)


def _md(text: str) -> str:
    """Escape, then honour the one bit of markup the basis lines use."""
    escaped = _e(text)
    while "**" in escaped:
        escaped = escaped.replace("**", "<b>", 1).replace("**", "</b>", 1)
    return escaped


def _tone(score: float | None) -> str:
    """Green, amber or red for a 0-10 score.

    Three bands, not the four a reader might expect from a 0-4 scorecard: the
    fourth would need a threshold no part of the spec sets, and inventing one in
    the renderer would make a colour say something the scoring does not.
    """
    if score is None:
        return ""
    if score >= 6.5:
        return "g"
    return "o" if score >= 4.5 else "r"


def _clock(ms: int) -> str:
    total = ms // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


# --------------------------------------------------------------- masthead ---


def _masthead(report: AssessmentReport) -> str:
    name = report.manager_name or "Interview report"
    # The control plane has no field for the manager's own name yet and passes
    # the job title through, so printing both would read "X · X". One is right.
    role = (
        f" <span>· {_e(report.job_title)}</span>"
        if report.job_title and report.job_title != report.manager_name
        else ""
    )
    chips = [f"{_clock(report.duration_ms)} · {_e(report.modality)} session"]
    if report.persona_label:
        chips.append(f"Candidate: {_e(report.persona_label)}")
    if report.started_at:
        chips.append(report.started_at.strftime("%d %b %Y · %H:%M"))
    # Only when it is a surprise: every English session carrying an "en" chip
    # would push the chip row onto a second line to say nothing.
    if report.language and report.language.detected not in ("en", ""):
        chips.append(f"Spoken: {_e(report.language.detected)}")
    return (
        f'<div class="eyebrow">Interviewer development report</div>'
        f'<div class="masthead"><div><h1>{_e(name)}{role}</h1>'
        f'<div class="chips">' + "".join(f'<span class="chip">{c}</span>' for c in chips) + "</div>"
        "</div></div>"
    )


# ------------------------------------------------------------- scorecard ---


def _pips(score: float | None, tone: str) -> str:
    """Four segments, filled to the nearest whole point of the 0-4 scale."""
    filled = 0 if score is None else round(score / 10 * 4)
    return (
        f'<span class="pips {tone}">'
        + "".join(f'<i class="{"on" if i < filled else ""}"></i>' for i in range(4))
        + "</span>"
    )


def _checklist(entry: CriterionScore) -> str:
    """The covered/missed strip, for criteria whose signals count over a list."""
    items = [item for signal in entry.signals for item in signal.checklist]
    if not items:
        return ""
    return (
        '<div class="strip">'
        + "".join(
            f'<span class="{"on" if i.covered else "off"}">'
            f"{_e(i.label.replace('_', ' '))} — {'covered' if i.covered else 'not covered'}</span>"
            for i in items
        )
        + "</div>"
    )


def _criterion_card(entry: CriterionScore, *, flagged: bool) -> str:
    tone = _tone(entry.score)
    icon = _ICONS.get(entry.id, "◆")
    # The rubric's own description of the competency, not a list of the
    # detectors under it: a reader is being told what this row measures.
    covers = " · ".join(entry.covers[:2])
    flag = '<span class="pill bad">flagged</span>' if flagged else ""
    narr = f'<div class="narr">{_e(entry.narrative)}</div>' if entry.narrative else ""
    bullets = (
        '<ul class="blist">'
        + "".join(f'<li class="{b.polarity}">{_e(b.text)}</li>' for b in entry.bullets)
        + "</ul>"
        if entry.bullets
        else ""
    )
    return f"""<div class="crit{" flagged" if flagged else ""}">
<div class="crit-top"><div class="ico">{icon}</div>
<div class="crit-name"><b>{_e(entry.label)}</b> {flag}<div>{_e(covers)}</div></div>
<div class="crit-score"><span class="wt">{entry.weight:.0%} weight</span>
{_pips(entry.score, tone)}
<span class="out4 {tone}">{out_of_four(entry.score)}/4</span></div></div>
{narr}{bullets}{_checklist(entry)}</div>"""


def _scorecard(report: AssessmentReport) -> str:
    flagged = {
        s.criterion
        for c in report.criteria
        for s in c.signals
        if s.id == "protected_topic_hits" and s.evidence
    }
    cards = "".join(_criterion_card(c, flagged=c.id in flagged) for c in report.criteria)
    return f'<div class="sec">Competency scorecard</div>{cards}'


# --------------------------------------------------------------- q and a ---


def _qna(report: AssessmentReport) -> str:
    """Every question the manager asked, in order, with what kind it was.

    A list rather than the five-column table this replaces. The table carried
    one more column and cost the section its readability, which is the whole
    complaint this report exists to answer.
    """
    acts = report.question_acts
    if not acts:
        return (
            '<div class="sec">Q&amp;A — every question asked</div>'
            '<div class="card tiny">No question was detected in this session.</div>'
        )

    counts = [f"{len(acts)} questions"]
    for key, label in (("behavioural", "behavioural"), ("situational", "hypothetical")):
        n = sum(1 for a in acts if a.type == key)
        if n:
            counts.append(f"{n} {label}")
    probes = sum(1 for a in acts if a.is_probe)
    if probes:
        counts.append(f"{probes} follow-up{'s' if probes != 1 else ''}")

    rows = ""
    for act in acts:
        label, tone = _QUESTION_TYPE.get(act.type, (act.type, ""))
        tags = f'<span class="pill {tone}">{_e(label)}</span>'
        if act.is_probe:
            tags += '<span class="pill good">follow-up</span>'
        if act.protected_topic:
            tags += f'<span class="pill bad">{_e(act.protected_topic.replace("_", " "))}</span>'
        rows += (
            f'<div class="qrow"><span class="qat">{_e(act.timestamp)}</span>'
            f'<span class="qtext">{_e(act.text)}</span>'
            f'<span class="qtag">{tags}</span></div>'
        )
    return (
        f'<div class="sec">Q&amp;A — every question asked</div>'
        f'<div class="card"><div class="qcount">{_e(" · ".join(counts))}</div>{rows}</div>'
    )


def _bei(report: AssessmentReport) -> str:
    """The behavioural questions asked, and the ones that came out hypothetical.

    Both lists come from the same classifier the score does — `behavioural` and
    `situational` are two of its six types — so this section adds a view, never
    a second opinion. A hypothetical is not wrong; it is weaker evidence, and
    naming the ones that could have been past-behaviour questions is the
    coachable moment.
    """
    asked = [a for a in report.question_acts if a.type == "behavioural"]
    instead = [a for a in report.question_acts if a.type == "situational"]
    if not asked and not instead:
        return (
            '<div class="sec">BEI questions</div>'
            '<div class="card tiny">No behavioural or hypothetical question was asked. '
            "Past behaviour is the strongest predictor available in an interview, and "
            "none was requested here.</div>"
        )

    def block(title: str, items: list, note: str, tone: str) -> str:
        if not items:
            return ""
        rows = "".join(
            f'<div class="qrow"><span class="qat">{_e(a.timestamp)}</span>'
            f'<span class="qtext">{_e(a.text)}</span></div>'
            for a in items
        )
        return (
            f'<div class="colhead {tone}">{_e(title)}</div>'
            f'<div class="card"><div class="qcount">{_e(note)}</div>{rows}</div>'
        )

    return (
        '<div class="sec">BEI questions</div>'
        + block(
            "Asked as behavioural",
            asked,
            "Past behaviour, asked directly — the strongest evidence an interview produces.",
            "s",
        )
        + block(
            "Asked as a hypothetical instead",
            instead,
            'These asked what the candidate would do. Ask what they did: swap "How would '
            'you handle a difficult shift?" for "Tell me about the last shift that went '
            'badly. What did you do?"',
            "gp",
        )
    )


# --------------------------------------------------- strengths and gaps ---


def _item(finding: Finding) -> str:
    quote = f"<q>{_e(finding.evidence[0].quote)}</q>" if finding.evidence else ""
    detail = f" {_e(finding.detail)}" if finding.detail else ""
    return f'<div class="item"><b>{_e(finding.headline)}</b>{detail}{quote}</div>'


def _strengths_and_gaps(report: AssessmentReport) -> str:
    if not report.strengths and not report.gaps:
        return ""
    left = "".join(_item(f) for f in report.strengths) or _nothing("No strength met the threshold.")
    right = "".join(_item(f) for f in report.gaps) or _nothing("No gap met the threshold.")
    return (
        f'<div class="sec">Strengths &amp; gaps</div>'
        f'<div class="cols"><div><div class="colhead s">Strengths</div>{left}</div>'
        f'<div><div class="colhead gp">Gaps</div>{right}</div></div>'
    )


def _nothing(text: str) -> str:
    return f'<div class="item tiny">{_e(text)}</div>'


def _areas(report: AssessmentReport) -> str:
    if not report.development_areas:
        return ""
    blocks = ""
    for n, area in enumerate(report.development_areas, start=1):
        try_line = (
            f'<div class="try"><b>Try:</b> {_e(area.alternative)}</div>' if area.alternative else ""
        )
        detail = f"<p>{_e(area.detail)}</p>" if area.detail else ""
        blocks += (
            f'<div class="area"><div class="num">{n}</div><div>'
            f"<h3>{_e(area.headline)}</h3>{detail}{try_line}</div></div>"
        )
    return f'<div class="sec">Areas to improve as an interviewer</div>{blocks}'


# ----------------------------------------------------------------- footer ---


def _footer(report: AssessmentReport) -> str:
    """The permanent basis line, plus what the reader must not conclude.

    This is the one part of the working that does not move behind `detail`. The
    counted/heard split is not a technicality: on a real session the counted
    fairness detector returned 10/10 on an interview containing salary-history
    and household questions asked in Hindi, because an English lexicon cannot
    match them. A reader who does not know which half of a number was heard can
    read that 10/10 as a clean result.
    """

    def count(source: str) -> int:
        return sum(
            1 for c in report.criteria for s in c.signals if s.measurable and s.source == source
        )

    counted, heard, judged = count("measured"), count("assessed"), count("judged")
    p = report.provenance
    basis = f"<b>{counted} signals counted</b> from the transcript by code"
    basis += (
        f" · <b>{heard} heard</b> from the recording by {_e(p.analysis_model or 'a model')}"
        if heard
        else " · <b>no audio analysis</b>, so tone, delivery and anything said in "
        "another language are not represented"
    )
    if judged:
        basis += f" · <b>{judged} read</b> out of the transcript by the judge"
    if p.judge_model:
        basis += (
            f" · prose written by {_e(p.judge_model)}, "
            "every quote checked word for word against the transcript"
        )
    nxt = (
        f"<b>Next practice.</b> {_e(report.next_practice_reason)}<br>"
        if report.next_practice_reason
        else ""
    )
    return (
        f'<div class="foot">{nxt}<b>SkillBrew · Interview Training.</b> The hiring manager was '
        f"scored against a locked interviewer rubric; the AI played the candidate. Readiness "
        f"is built only from the weighted competencies, and no criterion caps or fails "
        f"another.<br>{basis}.<br>"
        f"<b>This is a development report, not a performance rating</b> — use it to guide "
        f"coaching, not selection.</div>"
    )


# ------------------------------------------------------- the working ------


def _evidence(finding: Finding | SignalResult) -> str:
    return "".join(
        f"<blockquote><b>{_e(ev.timestamp)}</b> · {_e(ev.speaker)} — {_e(ev.quote)}</blockquote>"
        for ev in finding.evidence
    )


def _detail_criterion(entry: CriterionScore) -> str:
    score = "—" if entry.score is None else f"{entry.score}/10"
    conf = (
        f'<span class="pill">{_e(entry.confidence)} confidence</span>'
        if entry.confidence != "high"
        else ""
    )
    rows = "".join(
        f"<tr><td>{_e(s.label)} "
        f'<span class="pill {_SOURCE_CLASS.get(s.source, "")}">'
        f"{_SOURCE_LABEL.get(s.source, s.source)}</span></td>"
        f"<td>{_e(s.display)}</td>"
        f"<td>{'—' if s.sub_score is None else f'{s.sub_score:.1f}'}</td></tr>"
        for s in entry.signals
    )
    reason = (
        f'<div class="tiny" style="margin-top:6px">{_e(entry.confidence_reason)}</div>'
        if entry.confidence_reason
        else ""
    )
    return f"""<div class="card">
<div class="row"><b>{_e(entry.label)}</b>
<span><span class="muted">weight {entry.weight:.0%}</span> &nbsp;
<b class="{_tone(entry.score)}">{score}</b> {conf}</span></div>{reason}
<div class="scroll"><table style="margin-top:10px">
<tr><th>Signal</th><th>Measurement</th><th>Score</th></tr>{rows}</table></div></div>"""


def _working(report: AssessmentReport) -> str:
    """Every number with the measurement behind it. Appended, never substituted.

    The question acts are *not* here any more: the report itself now lists every
    question the manager asked, so a second rendering of the same acts would be
    two places for one fact to be wrong in.
    """
    basis = ""
    if report.basis.lines or report.basis.cautions:
        items = "".join(f"<li>{_md(line)}</li>" for line in report.basis.lines)
        cautions = "".join(f"<li>{_e(c)}</li>" for c in report.basis.cautions)
        basis = (
            f'<div class="sec plain">How this report was produced</div><div class="basis">'
            f"<ul>{items}</ul>"
            + (
                f'<div style="margin-top:10px"><b>Worth knowing</b><ul>{cautions}</ul></div>'
                if cautions
                else ""
            )
            + "</div>"
        )

    overview = ""
    if report.readiness_index is not None:
        tone = _tone(report.readiness_index / 10)
        overview = (
            f'<div class="sec plain">Overall</div><div class="card">'
            f'<div class="row"><b>Interview readiness</b>'
            f'<b class="{tone}">{report.readiness_index}/100 · {_e(report.band)}</b></div>'
            f'<div class="tiny" style="margin-top:6px">Computed and stored on every '
            f"report. It is not printed on the manager's pages, which carry the four "
            f"competencies rather than one number rolled up from them.</div></div>"
            + (
                f'<div class="summary"><div class="sec">Summary</div>'
                f"<p>{_e(report.summary)}</p></div>"
                if report.summary
                else ""
            )
        )

    criteria = '<div class="sec plain">Signals behind each score</div>' + "".join(
        _detail_criterion(c) for c in report.criteria
    )

    bias_signal = next(
        (s for c in report.criteria for s in c.signals if s.id == "protected_topic_hits"),
        None,
    )
    bias = ""
    if bias_signal:
        pill = (
            '<span class="pill bad">flagged</span>'
            if bias_signal.evidence
            else '<span class="pill good">pass</span>'
        )
        bias = (
            f'<div class="sec plain">Bias check</div><div class="card">'
            f'<div class="row"><b>Protected topics</b>{pill}</div>'
            f'<div class="muted">{_e(bias_signal.display)}</div>{_evidence(bias_signal)}</div>'
        )

    lang = ""
    if report.language:
        lang = (
            f'<div class="sec plain">Language</div><div class="card"><div class="muted">Detected '
            f"<b>{_e(report.language.detected)}</b> · "
            f"{report.language.english_token_share:.0%} English function words · "
            f"{_e(report.language.confidence)} confidence</div></div>"
        )

    p = report.provenance
    prov = (
        f"scoring {p.scoring_version} · bundle {p.bundle_version} · rubric {p.rubric_version} · "
        f"english_weight {p.english_weight if p.english_weight is not None else 'advisory'} · "
        f"language_gate {p.language_gate} · pack {p.pack_version}"
        + (
            f" · analysis {p.analysis_instructions_version} ({p.analysis_model})"
            if p.analysis_instructions_version
            else " · no audio analysis"
        )
        + (f" · judge {p.judge_version} ({p.judge_model})" if p.judge_model else " · no judge")
        + "<br>Reports are only comparable when every value above matches. "
        "Managers who know a trainer will read this interview more defensively than they "
        "otherwise would; that is a real limit on what these numbers mean."
    )
    return (
        f'<div class="pagebreak"></div>{overview}{basis}{criteria}{bias}{lang}'
        f'<div class="prov">{prov}</div>'
    )


# ------------------------------------------------------------------ page ---


def to_html(report: AssessmentReport, *, detail: bool = False) -> str:
    """A complete, self-contained HTML report.

    Args:
        report: The scored report.
        detail: Append the working — the readiness index, the summary, every
            signal with its measurement, the bias check and the full basis
            panel. Off by default: the report a manager acts on is the four
            competencies, the questions, strengths against gaps and the areas
            to improve, and the tables were what made the old one unreadable.
    """
    if report.unscoreable:
        body = (
            f'<div class="warn"><b>Not scored — {_e(report.unscoreable)}.</b><br>'
            f"The manager's speech was detected as "
            f"<b>{_e(report.language.detected if report.language else 'unknown')}</b>. "
            "The English rule set does not hold for this session, so no numbers were "
            "produced. Turn the language gate off to score it anyway with a stamped "
            "validity warning.</div>"
        )
        return _page(report, _masthead(report) + body + _footer(report))

    warnings = "".join(f'<div class="warn">{_e(w)}</div>' for w in report.validity_warnings)

    # The section list, and nothing else, is what the hiring manager who reads
    # this asked for: the four competencies, the questions, strengths against
    # gaps, and what to do differently. The readiness index and the summary
    # paragraph are computed and stored exactly as before — they are printed in
    # the working, where the reader who wants an overall number will look.
    body = (
        _masthead(report)
        + warnings
        + _scorecard(report)
        + _qna(report)
        + _bei(report)
        + '<div class="break"></div>'
        + _strengths_and_gaps(report)
        + _areas(report)
        + _footer(report)
        + (_working(report) if detail else "")
    )
    return _page(report, body)


def _page(report: AssessmentReport, body: str) -> str:
    return (
        f"<title>Interview report — {_e(report.manager_name or report.session_id)}</title>"
        f"<style>{_CSS}</style><div class='wrap'>{body}</div>"
    )


def to_json(report: AssessmentReport) -> str:
    """The full report as indented JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
