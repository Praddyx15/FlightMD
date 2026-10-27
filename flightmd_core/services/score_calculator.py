"""
Overall health score: weighted mean of the assessed modules' own scores.

Each analyser's health_score is used as it computed it (with its own caps
and extra penalties). Modules that were skipped or couldn't check anything
are left out of the mean, and when none could be assessed the report is
"Not assessed", never 100 / A.
"""

from flightmd_core.models.findings import AnalyserResult, Severity

# sum to 100; ascent_profile is deliberately unweighted (see its docstring)
MODULE_WEIGHTS: dict[str, float] = {
    "oscillation": 20.0,
    "vibration":   20.0,
    "ekf":         20.0,
    "battery":     15.0,
    "gps":         15.0,
    "parameters":   5.0,
    "motors":       5.0,
}

# the usual per-finding penalties; analysers apply their own variants
SEVERITY_PENALTY: dict[str, float] = {
    Severity.CRITICAL: 30.0,
    Severity.WARNING:  15.0,
    Severity.INFO:      5.0,
    Severity.GOOD:      0.0,
}

NOT_ASSESSED_LABEL = "Not assessed"
NOT_ASSESSED_GRADE = "-"

# one table for both, so a label and a grade can't disagree
# (score floor, label, grade)
BANDS = [
    (90, "Excellent", "A"),
    (80, "Good",      "B"),
    (70, "Caution",   "C"),
    (60, "Caution",   "D"),
    (50, "Warning",   "E"),
    (0,  "Critical",  "F"),
]
SCORE_LABELS = [(floor, label) for floor, label, _ in BANDS]


class ScoreCalculator:
    def calculate(self, results: list[AnalyserResult]) -> tuple[float, str, str]:
        """(score 0-100, label, letter grade). Marks unassessed results
        (assessed=False) as a side effect. Nothing assessed gives
        (0.0, "Not assessed", "-")."""
        total_weight = 0.0
        weighted_sum = 0.0

        for r in results:
            if r.skipped:
                r.assessed = False
            if r.analyser not in MODULE_WEIGHTS or not r.assessed:
                continue
            weight = MODULE_WEIGHTS[r.analyser]
            r.health_score = max(0.0, min(100.0, r.health_score))
            weighted_sum += r.health_score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0, NOT_ASSESSED_LABEL, NOT_ASSESSED_GRADE

        overall = round(max(0.0, min(100.0, weighted_sum / total_weight)), 1)
        return overall, self._label(overall), self.get_letter_grade(overall)

    def assessed_fraction(self, results: list[AnalyserResult]) -> float:
        """Share of the total weight that was actually assessed, 0-1."""
        done = sum(MODULE_WEIGHTS.get(r.analyser, 0.0) for r in results
                   if r.assessed and not r.skipped)
        return round(done / sum(MODULE_WEIGHTS.values()), 3)

    def get_letter_grade(self, score: float) -> str:
        for floor, _, grade in BANDS:
            if score >= floor:
                return grade
        return "F"

    def _label(self, score: float) -> str:
        for floor, label, _ in BANDS:
            if score >= floor:
                return label
        return "Critical"
