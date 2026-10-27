from abc import ABC, abstractmethod
import time

import pandas as pd

from flightmd_core.models.findings import AnalyserResult


class BaseAnalyser(ABC):
    name: str               # snake_case identifier
    display_name: str       # human-readable
    required_topics: list[str] = []   # must all exist in log to run
    optional_topics: list[str] = []   # used if present, ignored if absent

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
        return all(t in available_topics for t in self.required_topics)

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
        try:
            result = self.analyse(topics, params)
        except Exception as e:
            result = self._skip(f"Analysis error: {type(e).__name__}: {e}")
        result.processing_ms = int((time.time() - start) * 1000)
        return result
