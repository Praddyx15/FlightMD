"""
Report and airframe-record PDFs: Jinja2 templates rendered by WeasyPrint.

Lives in the core package so the CLI can write the same PDF as the API.
WeasyPrint (and Jinja2) come with the `pdf` extra; without them the render
functions raise RuntimeError saying what to install.

These are engineering review documents for the operator's own records, not
regulatory or compliance paperwork.
"""

import logging
import os
import threading
from datetime import datetime, timezone
from functools import lru_cache

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

INSTALL_HINT = (
    "PDF export needs WeasyPrint and Jinja2: pip install 'flightmd-core[pdf]' "
    "(WeasyPrint also needs the Pango system libraries)"
)

SEVERITY_COLOURS = {
    "critical": "#FF3D3D",
    "warning":  "#FF7A2F",
    "info":     "#3A9CF8",
    "good":     "#0DD97C",
}

SCORE_COLOURS = [
    (90, "#0DD97C"),   # excellent
    (75, "#3A9CF8"),   # good
    (60, "#E8A020"),   # caution
    (40, "#FF7A2F"),   # warning
    (0,  "#FF3D3D"),   # critical
]

# WeasyPrint isnt documented as thread-safe and one render can take a few
# hundred MB, so renders queue up one at a time
_render_lock = threading.Lock()

BASE_CSS = """
@page {
    size: A4;
    margin: 20mm 18mm 24mm 18mm;
    @bottom-center {
        content: "FlightMD · Pradum Behl · Page " counter(page) " of " counter(pages);
        font-size: 8pt;
        color: #666;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    @top-right {
        content: "CONFIDENTIAL — " string(report-id);
        font-size: 7pt;
        color: #999;
        font-family: monospace;
    }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10pt;
    color: #1a1a2e;
    line-height: 1.5;
}
h1 { font-size: 22pt; color: #1A3A5C; margin-bottom: 4px; }
h2 { font-size: 13pt; color: #1A3A5C; margin: 18px 0 8px; border-bottom: 1.5px solid #E8A020; padding-bottom: 4px; }
h3 { font-size: 11pt; color: #1A3A5C; margin: 12px 0 4px; }
p  { margin-bottom: 8px; }
.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 12px;
    border-bottom: 3px solid #1A3A5C;
    margin-bottom: 18px;
}
.logo { font-size: 11pt; color: #E8A020; font-weight: bold; letter-spacing: 2px; }
.tagline { font-size: 8pt; color: #666; }
.score-block {
    text-align: center;
    padding: 12px 20px;
    border-radius: 8px;
    background: #f8f9fc;
    border: 2px solid #e0e4f0;
    min-width: 120px;
}
.score-number { font-size: 36pt; font-weight: bold; line-height: 1; }
.score-label  { font-size: 11pt; font-weight: 600; }
.meta-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 18px;
}
.meta-item {
    background: #f8f9fc;
    padding: 8px 12px;
    border-radius: 4px;
    border-left: 3px solid #1A3A5C;
}
.meta-label { font-size: 7pt; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
.meta-value { font-size: 10pt; font-weight: 600; color: #1a1a2e; font-family: monospace; }
.executive-summary {
    background: #f0f4ff;
    border-left: 4px solid #1A3A5C;
    padding: 12px 16px;
    border-radius: 4px;
    margin-bottom: 18px;
    font-size: 10.5pt;
}
.finding {
    margin-bottom: 14px;
    border: 1px solid #e0e4f0;
    border-radius: 6px;
    overflow: hidden;
    page-break-inside: avoid;
}
.finding-header {
    display: flex;
    align-items: center;
    padding: 8px 14px;
    background: #f8f9fc;
}
.severity-badge {
    font-size: 7.5pt;
    font-weight: bold;
    padding: 2px 8px;
    border-radius: 10px;
    color: white;
    margin-right: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.finding-title { font-size: 10.5pt; font-weight: 600; color: #1A3A5C; }
.finding-body { padding: 10px 14px; }
.finding-plain { margin-bottom: 6px; }
.finding-rec {
    background: #fff8ee;
    border-left: 3px solid #E8A020;
    padding: 6px 10px;
    font-size: 9.5pt;
    border-radius: 2px;
}
.tech-detail {
    font-family: monospace;
    font-size: 8.5pt;
    color: #555;
    background: #f4f6fb;
    padding: 4px 8px;
    border-radius: 3px;
    margin-top: 6px;
}
.param-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 9pt; }
.param-table th {
    background: #1A3A5C;
    color: white;
    padding: 6px 10px;
    text-align: left;
    font-size: 8pt;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.param-table td { padding: 6px 10px; border-bottom: 1px solid #e8ecf5; }
.param-table tr:nth-child(even) td { background: #f8f9fc; }
.param-name { font-family: monospace; font-weight: bold; color: #1A3A5C; }
.param-val  { font-family: monospace; }
.signature-block {
    margin-top: 28px;
    page-break-inside: avoid;
    border: 1px solid #ccd0e0;
    border-radius: 6px;
    padding: 16px 20px;
}
.sig-title { font-size: 10pt; font-weight: bold; color: #1A3A5C; margin-bottom: 16px; }
.sig-line {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    margin-bottom: 24px;
}
.sig-field { border-bottom: 1px solid #555; padding-bottom: 4px; }
.sig-label { font-size: 7.5pt; color: #888; margin-top: 4px; }
.disclaimer {
    font-size: 7.5pt;
    color: #888;
    margin-top: 16px;
    border-top: 1px solid #e0e4f0;
    padding-top: 10px;
}"""


def severity_colour(severity) -> str:
    if hasattr(severity, "value"):
        severity = severity.value
    return SEVERITY_COLOURS.get(str(severity).lower(), "#888888")


def score_colour(score) -> str:
    if score is None:
        return "#888888"
    for threshold, colour in SCORE_COLOURS:
        if score >= threshold:
            return colour
    return "#FF3D3D"


def format_ms(ms) -> str:
    if ms is None:
        return "—"
    s = ms / 1000
    m, sec = divmod(int(s), 60)
    return f"{m:02d}:{sec:02d}.{int((s % 1) * 10)}"


@lru_cache(maxsize=1)
def template_env():
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["severity_colour"] = severity_colour
    env.filters["score_colour"] = score_colour
    env.filters["format_ms"] = format_ms
    return env


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _write_pdf(html: str) -> bytes:
    try:
        # heavy import with system deps, only load when a PDF is asked for
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as e:
        # OSError: the package is there but Pango/HarfBuzz aren't
        raise RuntimeError(INSTALL_HINT) from e
    with _render_lock:
        return HTML(string=html, base_url=TEMPLATE_DIR).write_pdf(stylesheets=[CSS(string=BASE_CSS)])


def render_report_html(report) -> str:
    return template_env().get_template("report.html").render(report=report, generated_at=_now())


def render_report_pdf(report) -> bytes:
    pdf = _write_pdf(render_report_html(report))
    logger.info(f"PDF for report {report.report_id}: {len(pdf)} bytes")
    return pdf


def render_airframe_record_html(
    airframe_label: str,
    flights: list,
    config,
    total_flight_hours: float,
    hours_since_maintenance: float,
    maintenance_due: bool,
) -> str:
    return template_env().get_template("airframe_record.html").render(
        airframe_label=airframe_label,
        flights=flights,
        config=config,
        total_flight_hours=total_flight_hours,
        hours_since_maintenance=hours_since_maintenance,
        maintenance_due=maintenance_due,
        generated_at=_now(),
    )


def render_airframe_record_pdf(**kwargs) -> bytes:
    """Same keyword arguments as render_airframe_record_html."""
    pdf = _write_pdf(render_airframe_record_html(**kwargs))
    logger.info(f"airframe record PDF: {len(pdf)} bytes, {len(kwargs.get('flights') or [])} flights")
    return pdf
