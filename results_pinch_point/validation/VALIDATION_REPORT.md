# Integrated pinch-point validation

## Reference condition

- Product: water heated from 110 to 115 °C at 5 bar.
- Total useful duty: 170 kW.
- Makeup: 190 kg/h at 25 °C.
- Water path: subcooler, mixture with return, main condenser.
- Refrigerants: R410A in the low stage and R245fa in the high stage.
- High-stage evaporation temperature: 35 °C.
- Evaporator, cascade and condenser pinch points: 10 K.
- Superheat and refrigerant subcooling: 5 K.
- Subcooler effectiveness: 0.90.
- Current architectures: linear compressor-efficiency model.

## Four-architecture check

| Configuration | Q cond. [kW] | Q SC [kW] | W el. [kW] | COP el. |
|---|---:|---:|---:|---:|
| Conventional cascade + subcooler | 151.14 | 18.86 | 117.22 | 1.450 |
| Low-stage flash tank + subcooler | 151.14 | 18.86 | 114.50 | 1.485 |
| High-stage flash tank + subcooler | 151.14 | 18.86 | 91.89 | 1.850 |
| Flash tanks in both stages + subcooler | 151.14 | 18.86 | 88.05 | 1.931 |

PASS_WITH_WARNING means that all balances, pinch points, water mixing, UA values and compressor-speed checks passed, but the assumed efficiency correlation reached a clipping limit. This is a compressor-data warning, not an energy-balance failure.

## Regression against the supplied model

| Variable | Original | Modular | Difference [%] | Status |
|---|---:|---:|---:|---|
| High-stage evaporation temperature [°C] | 35 | 35 | +0.000e+00 | MATCH |
| Low-stage condensation temperature [°C] | 45 | 45 | +0.000e+00 | MATCH |
| Main condenser duty [kW] | 101.13702 | 101.13702 | +0.000e+00 | MATCH |
| Subcooler duty [kW] | 18.862977 | 18.862977 | +0.000e+00 | MATCH |
| Total useful heat [kW] | 120 | 120 | +0.000e+00 | MATCH |
| Total shaft power [kW] | 75.994139 | 75.994139 | -5.610e-14 | MATCH |
| Overall shaft COP [-] | 1.5790691 | 1.5790691 | +5.625e-14 | MATCH |
| Heat-source mass flow [kg/s] | 4.3744272 | 4.3744272 | -2.843e-13 | MATCH |

The regression uses the original quadratic compressor relations and shaft-based COP. The water-mixing model is an added downstream balance and does not change the refrigerant-cycle regression quantities.
