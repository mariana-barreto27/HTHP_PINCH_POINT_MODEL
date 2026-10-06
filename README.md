# High-temperature heat-pump model

The project has one terminal entry point. Choose the cycle, component, stage,
and analysis; the default run evaluates one selected case.

## Start here

From the project folder, create/activate `.venv` and install the project once:

```bash
python -m pip install -e .
```

Then inspect the available choices:

```bash
python run.py --help
```

For example, optimize and draw the P–h diagrams for a cascade with an
economizer in both stages:

```bash
python run.py --ciclo cascata --componente economizador --estagio ambos --analise ph
```

Run an economizer only in the high stage and include the water subcooler:

```bash
python run.py --ciclo cascata --componente economizador --estagio alta --analise ponto
```

Run a low-stage flash tank without the subcooler:

```bash
python run.py --ciclo cascata --componente flash --estagio baixa --sem-subcooler --analise curva
```

Compare every cascade configuration (including COP, compressor power,
discharge temperatures, and line curves for all architectures) only when requested:

```bash
python run.py --analise comparacao
```

The available analyses are `ponto`, `curva`, `ph`, `mapa`, `fonte`, and
`comparacao`. A `ponto` search finds the best low-stage condensing temperature
for the selected cascade. `curva` sweeps the intermediate cascade condition
and plots against the corresponding high-stage evaporation temperature.
`ph` optimizes first and plots the selected cascade at that point. `mapa` shows
COP versus source inlet and low-stage condensation temperatures. `fonte` shows
COP versus source temperature at the requested fixed low-stage condensation.
`comparacao` compares all seven supported architectures, writes an optimum
summary table, and generates shared COP, compressor-power, and discharge-
temperature curves across the low-stage condensation-temperature sweep. The
comparison plots use curves rather than architecture bar charts.

`python run.py all` performs the selected-model analyses for all seven
architectures and then the shared comparisons. It does not reproduce analyses
that depend on components removed from this model (such as IHX), or old
single-stage cases with different refrigerants and boundary conditions. The
new-model comparisons consistently use the same load, source condition,
subcooler setting, refrigerants, and pinch assumptions so the architectures
can be compared fairly.

To find which of the seven configurations has the largest COP, run
`--analise comparacao`. That explicitly optimizes each configuration and
saves a short table and COP chart. Then select the configuration you want and
run `--analise ph` to draw its cycle at its own optimum. `--analise curva`
scans a temperature range for just the selected configuration.

For flash tanks, each trial searches intermediate pressure; vapor mass fraction
follows phase equilibrium. For economizers in optimized-mass mode, each trial searches both intermediate
pressure and injection mass fraction relative to total condenser flow. Injection
leaves as saturated vapor. The main-liquid outlet enthalpy follows the adiabatic
heat balance. The old 90% temperature rule no longer constrains the optimum; it
is used only for feasible starting candidates. Direct component calls without
a prescribed mass fraction retain the old thermal closure for compatibility.

The economizer counterflow pinch is checked on duty-aligned profiles including
the injection phase boundary. Actual pinch and required UA are exported. UA is
a result, not fixed hardware: this compares thermodynamic sizing alternatives,
not controls of one installed economizer with fixed area. Existing assumptions
for the other heat exchangers and compressors are unchanged.

Pressure/mass searches use feasible coarse seeds and bounded coordinate-wise
refinement. These numerical candidates are not proof of a global optimum.
The temperature search is adaptive with cached candidates rounded to **1 °C**
by default; it does not sweep the entire range. `--tolerancia 1` sets this
resolution. `--pontos` separately controls curve/map point count.
Operating conditions use `--carga`, `--fonte`, and `--temperatura-baixa`.

Settings are in `ComponentParams` (`src/hthp/configurations.py`):
`economizer_mass_fraction_min/max` and `economizer_mass_fraction_tolerance`.
The modes are now explicit:

- `optimize_economizer_mass_fraction=True`: optimize mass and pressure, keeping
  saturated vapor at injection. The 90% rule is only an initialization seed.
- `optimize_economizer_mass_fraction=False`, `fixed_economizer_mass_fraction=False`
  (default fixed-mode flag): return to the 90% thermal rule, saturated injection,
  and mass fraction calculated by the energy balance. Mass guesses are ignored.
- `optimize_economizer_mass_fraction=False`, `fixed_economizer_mass_fraction=True`:
  use `economizer_mass_fraction_low/high` as prescribed fractions and calculate
  the liquid outlet by energy balance, keeping saturated injection.

Pressure can still be optimized in all modes with `optimize_injection=True`.
To fix pressure too, set `optimize_injection=False`. Legacy
`injection_fraction_low/high` specify log-pressure coordinates, not mass fractions.

Fixed-flow closure now starts from an energy-consistent conservative estimate,
with alternative seeds if an intermediate trial fails. Constraints are not
relaxed. Curve rows distinguish `constraint_violation` (a verified constraint),
`not_converged` (the numerical solver/search failed), and `evaluation_error`
(an unclassified evaluation error). Not converging does not prove physical
impossibility. Comparison continues when one architecture's optimum search fails.
Rejected-point details are saved in `temperature_curves/rejected_points.csv`.
Graph markers indicate actual samples; three points do not resolve a peak curve.

Result tables include `low/high_injection_fraction`, pressure, economizer actual
pinch, required UA and `economizer_mass_fractions_optimized`. The point-analysis
console prints injection mass fractions and the curve run prints progress.

## Output

Only the selected analysis is generated. Files go under `results/`, in folders
named for the cycle, configuration, and analysis. Each run writes a
`conditions.json` so the plotted/result values can be tied to the inputs.
P–h runs also save the state table as CSV.

## Project layout

- `run.py`: terminal entry point.
- `src/hthp/model.py`: reference thermodynamic model and cascade optimization.
- `src/hthp/configurations.py`: flash-tank and economizer implementations.
- `src/hthp/analyses.py`: result records, plots, and P–h diagrams.
- `src/hthp/components/`, `cycles/`, `heat_sources/`, `thermo/`: reusable
  component and property calculations used by the selected model.

The standard case retains the reference-model inputs: 170 kW useful output,
R32 in the low stage, R1233zd(E) in the high stage, air at 30 °C, saturated
water at 120 °C, 5 K main heat-exchanger pinches, 5 K superheat, and a
high-stage water subcooler. These values can be changed in `Params` in
`src/hthp/model.py`; command-line overrides include load and source temperature.
