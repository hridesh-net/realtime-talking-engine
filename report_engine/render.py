"""Report rendering — JSON and a self-contained HTML page.

The HTML carries no external assets so a report can be mailed, archived or
opened offline years later and still read the same way.
"""

from __future__ import annotations

import html
import json

from report_engine.schema import AssessmentReport, CriterionScore, Finding, SignalResult

_CSS = """
:root{--ink:#101828;--ink2:#475467;--ink3:#98a2b3;--line:#e4e7ec;--bg:#f9fafb;
--g:#12a150;--o:#e08700;--r:#d92d20;--b:#175cd3}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.sub{color:var(--ink2);margin-bottom:22px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;
padding:20px;margin-bottom:14px}
.head{display:flex;gap:20px;align-items:center}
.dial{width:88px;height:88px;border-radius:50%;display:grid;place-items:center;
font-size:26px;font-weight:700;border:6px solid var(--line);flex:0 0 auto}
.g{color:var(--g);border-color:var(--g)}.o{color:var(--o);border-color:var(--o)}
.r{color:var(--r);border-color:var(--r)}
.band{font-size:19px;font-weight:700}
.muted{color:var(--ink2);font-size:13px}
.tiny{color:var(--ink3);font-size:12px}
.bar{height:7px;background:var(--line);border-radius:99px;overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;background:var(--b)}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--ink2);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.scroll{overflow-x:auto}
blockquote{margin:8px 0 0;padding:8px 12px;border-left:3px solid var(--line);
background:var(--bg);color:var(--ink2);font-size:13px;border-radius:0 6px 6px 0}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;
font-weight:600;border:1px solid var(--line);color:var(--ink2);background:#fff}
.pill.bad{color:var(--r);border-color:#fecdca;background:#fef3f2}
.pill.good{color:var(--g);border-color:#abefc6;background:#ecfdf3}
.warn{background:#fffaeb;border:1px solid #fedf89;color:#93370d;padding:12px 16px;
border-radius:10px;margin-bottom:14px;font-size:14px}
.alt{margin-top:8px;font-size:13px;color:var(--ink);background:#eff8ff;
border:1px solid #b2ddff;border-radius:8px;padding:9px 12px}
.prov{font-size:11px;color:var(--ink3);margin-top:28px;line-height:1.8}
li{margin-bottom:10px}ul{padding-left:18px}
"""


def _e(text: str) -> str:
    return html.escape(str(text), quote=True)


def _tone(score: float | None) -> str:
    if score is None:
        return ""
    if score >= 6.5:
        return "g"
    return "o" if score >= 4.5 else "r"


def _evidence(finding: Finding | SignalResult) -> str:
    return "".join(
        f"<blockquote><b>{_e(ev.timestamp)}</b> · {_e(ev.speaker)} — {_e(ev.quote)}</blockquote>"
        for ev in finding.evidence
    )


def _criterion(entry: CriterionScore) -> str:
    score = "—" if entry.score is None else f"{entry.score}/10"
    pct = 0 if entry.score is None else int(entry.score * 10)
    conf = (
        f'<span class="pill">{_e(entry.confidence)} confidence</span>'
        if entry.confidence != "high"
        else ""
    )
    rows = "".join(
        f"<tr><td>{_e(s.label)}</td><td>{_e(s.display)}</td>"
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
<b class="{_tone(entry.score)}">{score}</b> {conf}</span></div>
<div class="bar"><i style="width:{pct}%"></i></div>{reason}
<div class="scroll"><table style="margin-top:12px">
<tr><th>Signal</th><th>Measured</th><th>Score</th></tr>{rows}</table></div></div>"""


def _findings(title: str, items: list[Finding], *, with_alt: bool) -> str:
    if not items:
        return ""
    blocks = ""
    for item in items:
        alt = (
            f'<div class="alt"><b>Say instead:</b> {_e(item.alternative)}</div>'
            if with_alt and item.alternative
            else ""
        )
        blocks += (
            f'<div class="card"><b>{_e(item.headline)}</b>'
            f'<div class="muted">{_e(item.detail)}</div>{_evidence(item)}{alt}</div>'
        )
    return f"<h2>{_e(title)}</h2>{blocks}"


def to_html(report: AssessmentReport) -> str:
    """A complete, self-contained HTML report."""
    if report.unscoreable:
        body = (
            f'<div class="warn"><b>Not scored — {_e(report.unscoreable)}.</b><br>'
            f"The manager's speech was detected as "
            f"<b>{_e(report.language.detected if report.language else 'unknown')}</b>. "
            "The English rule set does not hold for this session, so no numbers were "
            "produced. Turn the language gate off to score it anyway with a stamped "
            "validity warning.</div>"
        )
        return _page(report, body)

    warnings = "".join(f'<div class="warn">{_e(w)}</div>' for w in report.validity_warnings)
    tone = _tone((report.readiness_index or 0) / 10)
    mins = report.duration_ms // 60000

    head = f"""<div class="card head">
<div class="dial {tone}">{report.readiness_index}</div>
<div><div class="band {tone}">{_e(report.band)}</div>
<div class="muted">{_e(report.job_title)} · candidate: {_e(report.persona_label)}
· {_e(report.modality)} session · {mins} min</div></div></div>"""

    criteria = "<h2>Category scorecard</h2>" + "".join(_criterion(c) for c in report.criteria)

    qna_rows = "".join(
        f"<tr><td>{_e(a.timestamp)}</td><td>{_e(a.text)}</td>"
        f'<td><span class="pill{" bad" if a.type in ("leading", "double_barrelled") else ""}">'
        f"{_e(a.type)}</span></td><td>{'probe ' + str(a.probe_depth) if a.is_probe else '—'}</td>"
        f"<td>{_e(a.segment)}</td></tr>"
        for a in report.question_acts
    )
    qna = (
        "<h2>Question analysis</h2><div class='card scroll'><table>"
        "<tr><th>At</th><th>Question</th><th>Type</th><th>Depth</th><th>Segment</th></tr>"
        f"{qna_rows or '<tr><td colspan=5>No questions detected.</td></tr>'}</table></div>"
    )

    bias_signal = next(
        (s for c in report.criteria for s in c.signals if s.id == "protected_topic_hits"),
        None,
    )
    bias = ""
    if bias_signal:
        flagged = bool(bias_signal.evidence)
        pill = (
            '<span class="pill bad">flagged</span>'
            if flagged
            else '<span class="pill good">pass</span>'
        )
        bias = (
            f'<h2>Bias check</h2><div class="card"><div class="row"><b>Protected topics</b>'
            f"{pill}</div><div class='muted'>{_e(bias_signal.display)}</div>"
            f"{_evidence(bias_signal)}</div>"
        )

    lang = ""
    if report.language:
        lang = (
            f'<h2>Language</h2><div class="card"><div class="muted">Detected '
            f"<b>{_e(report.language.detected)}</b> · "
            f"{report.language.english_token_share:.0%} English function words · "
            f"{_e(report.language.confidence)} confidence</div></div>"
        )

    nxt = (
        f'<h2>Next practice</h2><div class="card"><b>Target: '
        f"{_e(report.next_practice)}</b><div class='muted'>"
        f"{_e(report.next_practice_reason)}</div></div>"
        if report.next_practice
        else ""
    )

    body = (
        warnings
        + head
        + _findings("What went well", report.strengths, with_alt=False)
        + _findings("Focus areas", report.development_areas, with_alt=True)
        + criteria
        + qna
        + bias
        + lang
        + nxt
    )
    return _page(report, body)


def _page(report: AssessmentReport, body: str) -> str:
    p = report.provenance
    prov = (
        f"scoring {p.scoring_version} · bundle {p.bundle_version} · rubric {p.rubric_version} · "
        f"english_weight {p.english_weight if p.english_weight is not None else 'advisory'} · "
        f"language_gate {p.language_gate} · pack {p.pack_version} · judge {p.judge}<br>"
        "Reports are only comparable when every value above matches. "
        "This is an analytical estimate of how the manager interviewed - "
        "no pass, no fail, no gate. "
        "Managers who know a trainer will read this interview more defensively than they "
        "otherwise would; that is a real limit on what these numbers mean."
    )
    return (
        f"<title>Interview report — {_e(report.manager_name or report.session_id)}</title>"
        f"<style>{_CSS}</style><div class='wrap'>"
        f"<h1>{_e(report.manager_name or 'Interview report')}</h1>"
        f"<div class='sub'>Session {_e(report.session_id)}</div>"
        f"{body}<div class='prov'>{prov}</div></div>"
    )


def to_json(report: AssessmentReport) -> str:
    """The full report as indented JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
