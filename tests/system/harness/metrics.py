"""Prometheus text scraping helpers for higher-band system tests."""

from __future__ import annotations

from dataclasses import dataclass
from urllib import error, request

from prometheus_client.parser import text_string_to_metric_families


class MetricsScrapeError(RuntimeError):
    """Raised when a metrics scrape or parse step fails."""


@dataclass(frozen=True, slots=True)
class MetricsSampleSnapshot:
    """One parsed Prometheus sample from a metrics endpoint."""

    family_name: str
    family_type: str
    sample_name: str
    labels: dict[str, str]
    value: float


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """One parsed `/metrics` payload plus convenience lookup helpers."""

    text: str
    samples: tuple[MetricsSampleSnapshot, ...]

    @property
    def family_names(self) -> frozenset[str]:
        return frozenset(sample.family_name for sample in self.samples)

    def samples_for_name(self, sample_name: str) -> tuple[MetricsSampleSnapshot, ...]:
        return tuple(sample for sample in self.samples if sample.sample_name == sample_name)

    def matching_samples(
        self,
        sample_name: str,
        **labels: str,
    ) -> tuple[MetricsSampleSnapshot, ...]:
        return tuple(
            sample
            for sample in self.samples_for_name(sample_name)
            if all(sample.labels.get(key) == value for key, value in labels.items())
        )

    def sample_values(
        self,
        sample_name: str,
        **labels: str,
    ) -> tuple[float, ...]:
        return tuple(sample.value for sample in self.matching_samples(sample_name, **labels))

    def single_value(
        self,
        sample_name: str,
        **labels: str,
    ) -> float:
        values = self.sample_values(sample_name, **labels)
        if len(values) != 1:
            raise MetricsScrapeError(
                f"Expected exactly one sample for {sample_name} with labels {labels!r}, "
                f"got {len(values)}"
            )
        return values[0]


def parse_metrics_text(text: str) -> MetricsSnapshot:
    """Parse Prometheus exposition text into a normalized snapshot."""
    try:
        families = tuple(text_string_to_metric_families(text))
    except ValueError as exc:
        raise MetricsScrapeError("Metrics payload was not valid Prometheus text") from exc

    samples: list[MetricsSampleSnapshot] = []
    for family in families:
        family_name = str(family.name)
        family_type = str(family.type)
        for sample in family.samples:
            if isinstance(sample.value, bool) or not isinstance(sample.value, int | float):
                raise MetricsScrapeError(
                    f"Metrics sample {sample.name!r} did not expose a numeric value"
                )
            samples.append(
                MetricsSampleSnapshot(
                    family_name=family_name,
                    family_type=family_type,
                    sample_name=str(sample.name),
                    labels={key: str(value) for key, value in sample.labels.items()},
                    value=float(sample.value),
                )
            )

    return MetricsSnapshot(text=text, samples=tuple(samples))


def fetch_metrics_snapshot(
    base_url: str,
    *,
    path: str = "/metrics",
    timeout: float = 5.0,
) -> MetricsSnapshot:
    """Fetch and parse one metrics payload over HTTP."""
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("Metrics base_url must use http:// or https://")

    normalized_path = path if path.startswith("/") else f"/{path}"
    url = f"{base_url.rstrip('/')}{normalized_path}"
    req = request.Request(url, method="GET")  # noqa: S310
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            text = response.read().decode()
    except error.HTTPError as exc:
        body = exc.read().decode()
        raise MetricsScrapeError(
            f"Metrics request failed with HTTP {exc.code}: {body or exc.reason}"
        ) from exc
    except error.URLError as exc:
        raise MetricsScrapeError(f"Metrics request failed: {exc.reason}") from exc

    return parse_metrics_text(text)
