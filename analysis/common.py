"""Utilidades compartilhadas pelas análises de pinch point."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence

from analysis.plot_style import apply_plot_standard


def configure_plot_style() -> None:
    """Aplica o padrão visual dos gráficos."""
    apply_plot_standard()


def save_csv(
    records: Sequence[dict[str, float | bool | str]],
    path: Path,
) -> None:
    """Salva registros em CSV, preservando a ordem das colunas."""
    if not records:
        raise ValueError("Não há registros para salvar.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for record in records:
        for key in record:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def report_completion(
    name: str,
    records: Sequence[dict[str, float | bool | str]],
    output: Path,
) -> None:
    """Resume os pontos válidos e inválidos da análise."""
    valid = sum(record.get("valid") is True for record in records)
    invalid = len(records) - valid
    print(
        f"{name}: {valid} pontos válidos, {invalid} inválidos. "
        f"Resultados em {output}"
    )
