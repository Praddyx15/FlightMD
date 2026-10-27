from abc import ABC, abstractmethod
import time
from typing import Any, Optional

import pandas as pd

from flightmd_core.models.findings import AnalyserResult


class BaseAnalyser(ABC):
    name: str               # snake_case identifier
    display_name: str       # human-readable
    required_topics: list[str] = []   # must all exist in log to run
    optional_topics: list[str] = []   # used if present, ignored if absent
    required_any: list[str] = []      # at least one of these must exist
    # topic -> columns it must carry; only checked for topics that are present
    required_columns: dict[str, list[str]] = {}
    # format_detector ids this module understands; empty = any format
    formats: list[str] = []
    # share of the overall score (the built-ins sum to 100); 0 = findings
    # are shown but the module never moves the score
    weight: float = 0.0
    # FlightMetadata of the log being analysed, set by registry.load_analysers()
    metadata: Any = None

    @abstractmethod
    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        """Return a fully populated AnalyserResult. When there's nothing the
        module can actually check, return self._skip(reason) rather than a
        clean result, so the report says "not assessed" instead of 100."""

    def is_applicable(self, available_topics: set[str]) -> bool:
        if not all(t in available_topics for t in self.required_topics):
            return False
        return not self.required_any or any(t in available_topics for t in self.required_any)

    def missing_inputs(self, topics) -> Optional[str]:
        """Why this module can't run on these topics (a dict of DataFrames or
        just the names), or None when it can."""
        missing = [t for t in self.required_topics if t not in topics]
        if missing:
            return f"Required topics not available: {', '.join(missing)}"
        if self.required_any and not any(t in topics for t in self.required_any):
            return f"Needs one of these topics: {', '.join(self.required_any)}"
        fmt = getattr(self.metadata, "source_format", None)
        if self.formats and fmt and fmt not in self.formats:
            return f"Not available for {fmt} logs."
        if isinstance(topics, dict):
            for t, cols in self.required_columns.items():
                df = topics.get(t)
                if df is None:
                    continue
                lacking = [c for c in cols if c not in df.columns]
                if lacking:
                    return f"{t} has no {', '.join(lacking)} column"
        return None

    def skip_result(self, topics) -> AnalyserResult:
        return self._skip(self.missing_inputs(topics) or "Not applicable to this log.")

    def _skip(self, reason: str) -> AnalyserResult:
        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=[],
            skipped=True,
            skip_reason=reason,
        )

    def safe_analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        """analyse() with timing; any exception becomes a skipped result so
        one broken module never takes the report down."""
        start = time.time()
        reason = self.missing_inputs(topics)
        if reason:
            result = self._skip(reason)
        else:
            try:
                result = self.analyse(topics, params)
            except Exception as e:
                result = self._skip(f"Analysis error: {type(e).__name__}: {e}")
        result.processing_ms = int((time.time() - start) * 1000)
        return result
