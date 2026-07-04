"""
ScoreCalculator — weighted health score from analyser results.
"""

from flightmd_core.models.findings import AnalyserResult, Severity

# Weights must sum to 100
MODULE_WEIGHTS: dict[str, float] = {
    "oscillation": 20.0,
    "vibration":   20.0,
    "ekf":         20.0,
    "battery":     15.0,
    "gps":         15.0,
    "parameters":   5.0,
    "motors":       5.0,
}

SEVERITY_PENALTY: dict[str, float] = {
    Severity.CRITICAL: 30.0,
    Severity.WARNING:  15.0,
    Severity.INFO:      5.0,
    Severity.GOOD:      0.0,
}

SCORE_LABELS = [
    (90, "Excellent"),
    (75, "Good"),
    (60, "Caution"),
    (40, "Warning"),
    (0,  "Critical"),
]


class ScoreCalculator:
    def calculate(self, results: list[AnalyserResult]) -> tuple[float, str]:
        """
        Calculate overall health score and label.

        Returns:
            (score, label) where score ∈ [0, 100]
        """
        total_weight = 0.0
        weighted_sum = 0.0

        # Build a lookup by analyser name
        result_map = {r.analyser: r for r in results}

        for module_name, weight in MODULE_WEIGHTS.items():
            if module_name not in result_map:
                # Analyser wasn't applicable — skip (don't penalise)
                continue
            r = result_map[module_name]
            if r.skipped:
                # Skipped — don't penalise, don't count
                continue

            # Apply per-finding penalties to module score
            module_score = 100.0
            for finding in r.findings:
                penalty = SEVERITY_PENALTY.get(finding.severity, 0.0)
                module_score = max(0.0, module_score - penalty)

            # Update result's health_score field
            r.health_score = module_score

            weighted_sum  += module_score * weight
            total_weight  += weight

        if total_weight == 0:
            overall = 100.0
        else:
            overall = weighted_sum / total_weight

        overall = round(max(0.0, min(100.0, overall)), 1)
        label   = self._label(overall)
        return overall, label

    def _label(self, score: float) -> str:
        for threshold, label in SCORE_LABELS:
            if score >= threshold:
                return label
        return "Critical"
