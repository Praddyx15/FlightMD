"""
PDFGenerator — renders FlightMDReport to a printable flight analysis report.

Uses WeasyPrint (HTML→PDF) with a Jinja2 template. The PDF is an engineering
analysis document for internal review and maintenance tracking — it is not a
regulatory or compliance instrument.
"""

import logging
import os
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape

from flightmd_core.models.findings import FlightMDReport, Severity

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

SEVERITY_COLOURS = {
    Severity.CRITICAL: "#FF3D3D",
    Severity.WARNING:  "#FF7A2F",
    Severity.INFO:     "#3A9CF8",
    Severity.GOOD:     "#0DD97C",
}

SCORE_COLOURS = [
    (90, "#0DD97C"),   # Excellent — green
    (75, "#3A9CF8"),   # Good — blue
    (60, "#E8A020"),   # Caution — amber
    (40, "#FF7A2F"),   # Warning — orange
    (0,  "#FF3D3D"),   # Critical — red
]


class PDFGenerator:
    def __init__(self):
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self._env.filters["severity_colour"] = self._severity_colour
        self._env.filters["score_colour"]    = self._score_colour
        self._env.filters["format_ms"]       = self._format_ms

    def generate(self, report: FlightMDReport) -> bytes:
        """Render report to PDF bytes."""
        try:
            from weasyprint import HTML, CSS
        except ImportError as e:
            raise ImportError(
                "WeasyPrint is required for PDF generation. "
                "Install it with: pip install weasyprint"
            ) from e

        template = self._env.get_template("report.html")
        html_content = template.render(
            report=report,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            severity_colours=SEVERITY_COLOURS,
        )

        pdf_bytes = HTML(string=html_content, base_url=TEMPLATE_DIR).write_pdf(
            stylesheets=[
                CSS(string=self._base_css()),
            ]
        )
        logger.info(f"PDF generated for report {report.report_id}: {len(pdf_bytes)} bytes")
        return pdf_bytes

    # ── Jinja2 filters ───────────────────────────────────────────────────────

    @staticmethod
    def _severity_colour(severity) -> str:
        if hasattr(severity, "value"):
            severity = severity.value
        return {
            "critical": "#FF3D3D",
            "warning":  "#FF7A2F",
            "info":     "#3A9CF8",
            "good":     "#0DD97C",
        }.get(str(severity).lower(), "#888888")

    @staticmethod
    def _score_colour(score: float) -> str:
        for threshold, colour in SCORE_COLOURS:
            if score >= threshold:
                return colour
        return "#FF3D3D"

    @staticmethod
    def _format_ms(ms: int) -> str:
        if ms is None:
            return "—"
        s = ms / 1000
        m, sec = divmod(int(s), 60)
        return f"{m:02d}:{sec:02d}.{int((s % 1) * 10)}"

    # ── Base CSS ─────────────────────────────────────────────────────────────

    @staticmethod
    def _base_css() -> str:
        return """
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
        }
        """
