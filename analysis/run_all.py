"""Executa somente as análises do modelo integrado de pinch point."""

from analysis.compressor_model_comparison import main as compressor_models
from analysis.integrated_all_technology_comparison import main as technologies
from analysis.integrated_curve_change_analysis import main as curve_changes
from analysis.integrated_economizer_analysis import main as economizer
from analysis.integrated_flash_tank_subcooler_comparison import (
    main as flash_tank_subcooler,
)
from analysis.integrated_pinch_heat_source_map import main as source_map
from analysis.integrated_pinch_heat_source_sweep import main as source_sweep
from analysis.integrated_pinch_model import main as pinch_model
from analysis.integrated_pinch_validation import main as validation
from analysis.integrated_subcooler_comparison import main as subcooler


def main() -> None:
    steps = (
        ("Modelo integrado", pinch_model),
        ("Validação do ponto-base", validation),
        ("Mapa de fonte térmica e evaporação", source_map),
        ("Temperatura de entrada da fonte", source_sweep),
        ("Modelos de eficiência do compressor", compressor_models),
        ("Economizador", economizer),
        ("Flash tank e subcooler", flash_tank_subcooler),
        ("Comparação das tecnologias", technologies),
        ("Comparação com/sem subcooler", subcooler),
        ("Curvas COP, ótimos e descarga", curve_changes),
    )
    for index, (description, run) in enumerate(steps, start=1):
        print(f"{index}/{len(steps)} — {description}", flush=True)
        run()
    print("Todas as análises de pinch point foram concluídas.")


if __name__ == "__main__":
    main()
