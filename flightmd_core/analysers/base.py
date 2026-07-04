"""
BaseAnalyser — all analysers must inherit from this.
"""

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
        """
        Run analysis on the provided topics and parameters.
        Must return a fully populated AnalyserResult — never raise.
        """
        pass

    def is_applicable(self, available_topics: set[str]) -> bool:
        """
        Returns True only if all required_topics are present in the log.
        ParameterAnalyser overrides this (it uses params, not topics).
        """
        return all(t in available_topics for t in self.required_topics)

    def safe_analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        """
        Wraps analyse() with timing and error handling.
        Any exception → skipped result, never propagates.
        """
        start = time.time()
        try:
            result = self.analyse(topics, params)
            result.processing_ms = int((time.time() - start) * 1000)
            return result
        except Exception as e:
            return AnalyserResult(
                analyser=self.name,
                display_name=self.display_name,
                findings=[],
                skipped=True,
                skip_reason=f"Analysis error: {type(e).__name__}: {str(e)}",
                processing_ms=int((time.time() - start) * 1000),
            )
