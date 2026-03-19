from __future__ import annotations

__all__ = [
    "generate_metric_event_charts",
    "ingest_uc_rainfall",
    "ingest_uc_rainfall_many",
    "list_candidate_cells",
]


def __getattr__(name: str):
    if name == "list_candidate_cells":
        from .services.candidate_service import list_candidate_cells

        return list_candidate_cells
    if name == "generate_metric_event_charts":
        from .services.graph_service import generate_metric_event_charts

        return generate_metric_event_charts
    if name in {"ingest_uc_rainfall", "ingest_uc_rainfall_many"}:
        from .services.ingest_service import ingest_uc_rainfall, ingest_uc_rainfall_many

        return ingest_uc_rainfall if name == "ingest_uc_rainfall" else ingest_uc_rainfall_many
    raise AttributeError(name)
