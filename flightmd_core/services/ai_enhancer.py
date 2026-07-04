"""
AIEnhancer — optional AI enhancement layer, provider-agnostic.

This is NOT the diagnostic engine. All findings, severities, and parameter
recommendations are produced by the deterministic ExplanationEngine and the
seven rule-based analysers, and are never touched here. This module only:

  1. Optionally rewrites the deterministic executive summary in a more
     natural voice (polish_summary).
  2. Optionally answers free-form questions about a completed report,
     grounded strictly in that report's own data (answer_question).

Two providers are supported:
  - "groq"      — free tier (Llama 3.3 70B), no cost to the operator running
                  this instance. Uses Groq's OpenAI-compatible chat
                  completions endpoint via the `openai` SDK pointed at a
                  different base_url — no Groq-specific SDK needed.
  - "anthropic" — Claude, for operators who want that quality and have a key.

If no API key is supplied for the selected provider, every method is a
no-op that returns the input unchanged (polish_summary) or a clear "not
configured" message (answer_question). Any exception during an API call is
caught and the method falls back to the same safe behaviour — this layer
must never break report generation.
"""

import logging
from typing import Optional, TYPE_CHECKING

from flightmd_core.models.findings import Finding

if TYPE_CHECKING:
    from flightmd_core.models.findings import FlightMDReport
    from flightmd_core.models.metadata import FlightMetadata

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

NOT_CONFIGURED_MESSAGE = (
    "AI assistant is not configured — showing keyword search results instead."
)


class AIEnhancer:
    def __init__(
        self,
        provider: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        model: Optional[str] = None,
        # Backward-compatible alias for the original Anthropic-only signature.
        api_key: Optional[str] = None,
    ):
        # Back-compat: earlier callers passed api_key= expecting Anthropic,
        # with no provider argument at all. If that's the call shape in use
        # (api_key given, provider not specified), resolve to "anthropic" so
        # old call sites keep working — only default to the new "groq"
        # default when the caller hasn't signalled the old convention.
        if api_key and not anthropic_api_key:
            anthropic_api_key = api_key
            if provider is None:
                provider = "anthropic"

        self.provider = (provider or "groq").lower().strip()
        self._client = None
        self._call_fn = None

        if self.provider == "groq":
            self.model = model or DEFAULT_GROQ_MODEL
            if groq_api_key:
                self._init_groq(groq_api_key)
        elif self.provider == "anthropic":
            self.model = model or DEFAULT_ANTHROPIC_MODEL
            if anthropic_api_key:
                self._init_anthropic(anthropic_api_key)
        else:
            logger.warning(f"Unknown AI provider '{provider}' — AI enhancer disabled.")
            self.model = model or ""

    def _init_groq(self, groq_api_key: str) -> None:
        try:
            import openai
            self._client = openai.AsyncOpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL)
            self._call_fn = self._call_openai_compatible
        except Exception as e:
            logger.warning(f"AI enhancer could not initialise Groq client (disabled): {e}")
            self._client = None

    def _init_anthropic(self, anthropic_api_key: str) -> None:
        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
            self._call_fn = self._call_anthropic
        except Exception as e:
            logger.warning(f"AI enhancer could not initialise Anthropic client (disabled): {e}")
            self._client = None

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    # ── provider call adapters ──────────────────────────────────────────────

    async def _call_anthropic(self, prompt: str, max_tokens: int) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if hasattr(block, "text")
        ).strip()

    async def _call_openai_compatible(self, prompt: str, max_tokens: int) -> str:
        response = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip()

    # ── public API ───────────────────────────────────────────────────────────

    async def polish_summary(
        self,
        base_summary: str,
        findings: list[Finding],
        metadata: "FlightMetadata",
    ) -> str:
        """
        Rewrite the deterministic executive summary in a more natural voice.
        Never invents new findings or changes the facts — only the prose.
        Falls back to base_summary unchanged on any error or when disabled.
        """
        if not self.is_configured:
            return base_summary

        finding_lines = "\n".join(
            f"- [{f.severity.value.upper()}] {f.title}" for f in findings[:15]
        ) or "- None"

        prompt = (
            "Rewrite the following flight-analysis executive summary in clear, "
            "natural prose for a drone pilot. Do not add, remove, or change any "
            "facts, findings, or numbers — only improve the phrasing and flow. "
            "Keep it to 2-3 sentences, no bullet points, no markdown.\n\n"
            f"Flight duration: {metadata.duration_seconds:.0f}s\n"
            f"Findings:\n{finding_lines}\n\n"
            f"Current summary:\n{base_summary}"
        )

        try:
            text = await self._call_fn(prompt, max_tokens=300)
            return text or base_summary
        except Exception as e:
            logger.warning(f"AI summary polish failed, using deterministic summary: {e}")
            return base_summary

    async def answer_question(self, question: str, report: "FlightMDReport") -> str:
        """
        Answer a free-form question about a completed report, grounded only
        in that report's own findings/metadata. Falls back to a clear
        "not configured" message when disabled, or a graceful error message
        if the API call fails.
        """
        if not self.is_configured:
            return NOT_CONFIGURED_MESSAGE

        finding_lines = "\n".join(
            f"- [{f.severity.value.upper()}] {f.category.value}: {f.title} — "
            f"{f.plain_english} Recommendation: {f.recommendation}"
            for f in report.findings
        ) or "- No findings were detected in this flight."

        context = (
            f"Overall health score: {report.overall_score}/100 ({report.score_label}, "
            f"grade {report.letter_grade})\n"
            f"Executive summary: {report.executive_summary}\n"
            f"Flight duration: {report.metadata.duration_seconds:.0f}s\n"
            f"Findings:\n{finding_lines}"
        )

        prompt = (
            "You are answering a question about a single drone flight log analysis "
            "report. Use ONLY the data below — do not invent findings, numbers, or "
            "parameter values that aren't present. If the answer isn't in this data, "
            "say so plainly rather than guessing.\n\n"
            f"Report data:\n{context}\n\n"
            f"Question: {question}"
        )

        try:
            text = await self._call_fn(prompt, max_tokens=400)
            return text or "I couldn't generate an answer from this report's data."
        except Exception as e:
            logger.warning(f"AI Q&A call failed: {e}")
            return "The AI assistant encountered an error answering that question. Try the keyword search instead."
