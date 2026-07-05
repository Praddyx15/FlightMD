"""
Tests for the airframe_record.html Jinja2 template — rendered directly
(bypassing WeasyPrint's HTML->PDF conversion, which needs system Pango/
Cairo libraries not installed in every dev environment) to verify the
template itself is valid and produces the expected content with no
leftover unescaped {{ }} / {% %} syntax.
"""

from datetime import datetime, timezone

from api.airframe_store import AirframeConfig, AlertRule, MaintenanceEntry
from api.services.pdf_generator import PDFGenerator


def render_airframe_record(config, flights, total_hours=10.0, hours_since=5.0, due=False):
    gen = PDFGenerator()
    template = gen._env.get_template("airframe_record.html")
    return template.render(
        airframe_label=config.airframe_label,
        flights=flights,
        config=config,
        total_flight_hours=total_hours,
        hours_since_maintenance=hours_since,
        maintenance_due=due,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


class TestAirframeRecordTemplate:
    def test_renders_without_leftover_template_syntax(self):
        config = AirframeConfig(
            airframe_label="Quad-1",
            checklist_items=["Check props", "Check GPS lock"],
            maintenance_log=[MaintenanceEntry(date="2026-06-01", maintenance_type="Prop swap", notes="All 4")],
            maintenance_interval_hours=20.0,
        )
        flights = [
            {"date": "2026-07-01", "file_name": "flight1.ulg", "duration_minutes": 12.0,
             "overall_score": 92, "letter_grade": "A"},
        ]
        html = render_airframe_record(config, flights)

        assert "{{" not in html
        assert "{%" not in html
        assert "Quad-1" in html
        assert "flight1.ulg" in html
        assert "Prop swap" in html
        assert "Check props" in html

    def test_empty_airframe_shows_placeholder_text(self):
        config = AirframeConfig(airframe_label="Empty-Drone")
        html = render_airframe_record(config, flights=[])

        assert "No flights logged" in html
        assert "No maintenance entries logged" in html

    def test_maintenance_due_flag_reflected_in_output(self):
        config = AirframeConfig(airframe_label="Quad-1", maintenance_interval_hours=10.0)
        html = render_airframe_record(config, flights=[], hours_since=15.0, due=True)
        assert "Maintenance Due" in html

    def test_disclaimer_present_not_a_certification(self):
        """This must never be framed as a compliance certification —
        it's the operator's own recordkeeping export."""
        config = AirframeConfig(airframe_label="Quad-1")
        html = render_airframe_record(config, flights=[])
        assert "not a regulatory certification" in html
