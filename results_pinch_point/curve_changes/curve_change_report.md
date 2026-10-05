# COP, compressor discharge and efficiency-limit study

## Conditions

- Useful heating duty: 170 kW.
- Water: 110 to 115 °C at 5 bar.
- Source: 20 to 10 °C.
- High-stage evaporation search: 20–60 °C.
- Compressor efficiency: the current linear correlation, clipped to its configured limits.
- The discharge-temperature curves are model predictions; no manufacturer compressor map or allowable-temperature limit is applied.

## Continuous optima

| Configuration | T* high-stage evap. [°C] | COP* | Power [kW] | Max discharge low/high [°C] | Boundary? |
|---|---:|---:|---:|---:|:---:|
| Conventional cascade + subcooler | 51.63 | 1.558 | 109.13 | 115.2 / 136.1 | No |
| Low-stage flash tank + subcooler | 60.00 | 1.752 | 97.06 | 107.0 / 131.8 | Yes |
| High-stage flash tank + subcooler | 31.29 | 1.854 | 91.69 | 75.7 / 129.3 | No |
| Flash tanks in both stages + subcooler | 44.73 | 1.948 | 87.27 | 88.3 / 127.5 | No |

## Effect of the efficiency lower limit

| Configuration | Sweep points without active limit | Minimum raw efficiency low/high |
|---|---:|---:|
| Conventional cascade + subcooler | 44/81 | 0.552 / -0.016 |
| Low-stage flash tank + subcooler | 44/81 | 0.717 / -0.016 |
| High-stage flash tank + subcooler | 81/81 | 0.552 / 0.625 |
| Flash tanks in both stages + subcooler | 81/81 | 0.717 / 0.625 |

## Efficiency-limit transitions

| Configuration | Temperature interval [°C] | Low-stage status | High-stage status |
|---|---:|---|---|
| Conventional cascade + subcooler | 38.0–38.5 | none → none | minimum → none |
| Low-stage flash tank + subcooler | 38.0–38.5 | none|none → none|none | minimum → none |

The clipped-model COP curve includes every thermodynamic point and substitutes the configured efficiency limit when the raw correlation exceeds its range. The clipping-sensitivity figure overlays a second calculation that rejects such points, leaving gaps where the efficiency correlation is outside its configured range. A kink near a limit transition is therefore partly caused by the chosen efficiency correlation and clipping rule. This rejection check evaluates the assumed correlation only; it is not a manufacturer compressor map. Compare predicted discharge temperatures against the actual compressor manufacturer's allowable envelope before making an equipment-feasibility claim.
