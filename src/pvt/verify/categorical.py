"""2x2 contingency scores (docs/01 section 5).

a = hit, b = false alarm, c = miss, d = correct negative. Undefined ratios are NaN.
"""

from __future__ import annotations

from dataclasses import dataclass


def _ratio(num: float, den: float) -> float:
    return num / den if den else float("nan")


@dataclass(frozen=True)
class Contingency:
    """Counts of a 2x2 contingency table."""

    a: int
    b: int
    c: int
    d: int

    @property
    def n(self) -> int:
        """Total count."""
        return self.a + self.b + self.c + self.d

    def pod(self) -> float:
        """Probability of detection a/(a+c)."""
        return _ratio(self.a, self.a + self.c)

    def far(self) -> float:
        """Return the false alarm ratio b/(a+b)."""
        return _ratio(self.b, self.a + self.b)

    def csi(self) -> float:
        """Critical success index a/(a+b+c)."""
        return _ratio(self.a, self.a + self.b + self.c)

    def freq_bias(self) -> float:
        """Frequency bias (a+b)/(a+c)."""
        return _ratio(self.a + self.b, self.a + self.c)

    def ets(self) -> float:
        """Equitable threat score."""
        if not self.n:
            return float("nan")
        a_r = (self.a + self.b) * (self.a + self.c) / self.n
        return _ratio(self.a - a_r, self.a + self.b + self.c - a_r)

    def pss(self) -> float:
        """Peirce / Hanssen-Kuipers skill score."""
        return self.pod() - _ratio(self.b, self.b + self.d)

    def hss(self) -> float:
        """Heidke skill score."""
        a, b, c, d = self.a, self.b, self.c, self.d
        return _ratio(2.0 * (a * d - b * c), (a + c) * (c + d) + (a + b) * (b + d))

    def scores(self) -> dict[str, float]:
        """All scores as a dict."""
        return {
            "pod": self.pod(),
            "far": self.far(),
            "csi": self.csi(),
            "ets": self.ets(),
            "pss": self.pss(),
            "hss": self.hss(),
            "freq_bias": self.freq_bias(),
        }
