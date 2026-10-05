"""Relatório textual compacto para conferir uma simulação."""

from hthp.cycles.simple_cycle import SimpleCycleResult
from hthp.cycles.flash_tank_cycle import FlashTankCycleResult


def format_cycle_report(result: SimpleCycleResult) -> str:
    lines = [
        "HTHP MODULAR — CICLO DE ESTÁGIO ÚNICO",
        "=" * 72,
        f"Refrigerante:                 {result.config.refrigerant}",
        f"Fonte de calor:               {result.heat_source.name}",
        f"Temperatura de evaporação:    {result.evaporation_temperature_C:8.2f} °C",
        f"Temperatura de condensação:   {result.config.condensation_temperature_C:8.2f} °C",
        f"Capacidade de aquecimento:    {result.condenser_heat_kW:8.2f} kW",
        f"Calor retirado da fonte:      {result.evaporator_heat_kW:8.2f} kW",
        f"Potência no eixo:             {result.compressor_shaft_power_kW:8.2f} kW",
        f"Potência elétrica:            {result.compressor_electrical_power_kW:8.2f} kW",
        f"Perda no motor:               {result.motor_loss_kW:8.2f} kW",
        f"COP de aquecimento:           {result.heating_COP:8.3f}",
        f"Vazão de refrigerante:        {result.refrigerant_mass_flow_kg_s:8.4f} kg/s",
        f"Razão de pressão:             {result.pressure_ratio:8.3f}",
        f"Erro relativo do balanço:     {result.relative_energy_balance_error:.3e}",
    ]

    if result.heat_source.outlet_temperature_C is not None:
        lines.append(
            "Temperatura de saída da fonte: "
            f"{result.heat_source.outlet_temperature_C:8.2f} °C"
        )

    lines.extend(
        [
            "",
            "ESTADOS DO REFRIGERANTE",
            "Ponto       P [bar]       T [°C]     h [kJ/kg]        título",
            "-" * 72,
        ]
    )
    for point, state in result.states.items():
        quality = "--" if state.quality is None else f"{state.quality:.4f}"
        lines.append(
            f"{point:>5d}  {state.pressure_bar:12.3f}  "
            f"{state.temperature_C:11.2f}  {state.enthalpy_kJ_kg:13.2f}  "
            f"{quality:>12s}"
        )
    return "\n".join(lines)


def format_flash_tank_report(result: FlashTankCycleResult) -> str:
    lines = [
        "HTHP MODULAR — CICLO COM FLASH TANK",
        "=" * 76,
        f"Refrigerante:                    {result.config.refrigerant}",
        f"Fonte de calor:                  {result.heat_source.name}",
        f"Temperatura de evaporação:       {result.evaporation_temperature_C:8.2f} °C",
        f"Temperatura de condensação:      {result.config.condensation_temperature_C:8.2f} °C",
        f"Pressão intermediária:           {result.intermediate_pressure_bar:8.3f} bar",
        f"Média geométrica das pressões:   {result.geometric_mean_pressure_bar:8.3f} bar",
        f"Fração de vapor no flash:        {result.flash_vapor_fraction:8.4f}",
        f"Capacidade de aquecimento:       {result.condenser_heat_kW:8.2f} kW",
        f"Calor retirado da fonte:         {result.evaporator_heat_kW:8.2f} kW",
        f"Potência elétrica — baixa:       {result.low_compressor_electrical_power_kW:8.2f} kW",
        f"Potência elétrica — alta:        {result.high_compressor_electrical_power_kW:8.2f} kW",
        f"Potência elétrica total:         {result.total_electrical_power_kW:8.2f} kW",
        f"COP de aquecimento:              {result.heating_COP:8.3f}",
        f"Vazão total:                     {result.total_refrigerant_mass_flow_kg_s:8.4f} kg/s",
        f"Vazão no evaporador:             {result.evaporator_mass_flow_kg_s:8.4f} kg/s",
        f"Vazão de vapor injetado:         {result.injected_vapor_mass_flow_kg_s:8.4f} kg/s",
        f"Razão de pressão — baixa:        {result.low_stage_pressure_ratio:8.3f}",
        f"Razão de pressão — alta:         {result.high_stage_pressure_ratio:8.3f}",
        f"Erro relativo do balanço:        {result.relative_energy_balance_error:.3e}",
        "",
        "ESTADOS DO REFRIGERANTE",
        "Ponto       P [bar]       T [°C]     h [kJ/kg]        título",
        "-" * 76,
    ]
    for point, state in result.states.items():
        quality = "--" if state.quality is None else f"{state.quality:.4f}"
        lines.append(
            f"{point:>5s}  {state.pressure_bar:12.3f}  "
            f"{state.temperature_C:11.2f}  {state.enthalpy_kJ_kg:13.2f}  "
            f"{quality:>12s}"
        )
    return "\n".join(lines)
