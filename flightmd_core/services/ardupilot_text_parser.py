"""
ArduPilot text dataflash logs (.log): the "FMT, 128, 89, FMT, ..." comma-separated form
Mission Planner and mavlogdump write. pymavlink's DFReader_text reads it into the same
messages DFReader_binary gives, with values already scaled, so everything after opening
the reader is ArduPilotBinParser's mapping.
"""

from flightmd_core.services.ardupilot_parser import INDEX_SHARE, ArduPilotBinParser


class ArduPilotTextParser(ArduPilotBinParser):
    """Same interface as ULogParser: .parse(path) -> (topics, params, metadata)."""

    def _open_reader(self, path):
        from pymavlink import DFReader

        report = self._progress
        if report is None:
            return DFReader.DFReader_text(path)
        return DFReader.DFReader_text(path, progress_callback=lambda pct: report(INDEX_SHARE * pct / 100))
