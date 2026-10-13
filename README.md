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
`comparacao` compares all ten supported architectures, writes an optimum
summary table, and generates shared COP, compressor-power, and discharge-
temperature curves across the low-stage condensation-temperature sweep. The
comparison plots use curves rather than architecture bar charts.

`python run.py all` performs the selected-model analyses for all ten
architectures and then the shared comparisons. It does not reproduce analyses
that depend on components removed from this model (such as IHX), or old
single-stage cases with different refrigerants and boundary conditions. The
new-model comparisons consistently use the same load, source condition,
subcooler setting, refrigerants, and pinch assumptions so the architectures
can be compared fairly.

To find which of the ten configurations has the largest COP, run
`--analise comparacao`. That explicitly optimizes each configuration and
saves a short table and COP chart. Then select the configuration you want and
run `--analise ph` to draw its cycle at its own optimum. `--analise curva`
scans a temperature range for just the selected configuration.

For flash tanks and economizers, each trial also searches its intermediate
pressure. The temperature and pressure searches use `scipy.optimize.minimize_scalar`;
the pressure search is bounded and seeded by a coarse grid. These are numerical
optima within the model bounds, not proof of a global optimum. Adjust search
resolution and operating conditions with `--tolerancia`, `--pontos`, `--carga`,
`--fonte`, and `--temperatura-baixa`.

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

## Ejector with IHX

The original seven configurations are retained. Three additional configurations
place an ejector with its own liquid/suction IHX in the high stage, low stage,
or both stages. The IHX is included ONLY in the stage selected for the ejector;
it is not restored in the conventional, flash-tank or economizer cases.

Start with the high-stage ejector and the existing high-stage water subcooler:

```bash
python run.py --componente ejetor --estagio alta --analise ponto
python run.py --componente ejetor --estagio alta --analise curva
python run.py --componente ejetor --estagio alta --analise ph
```

Use `--estagio baixa` or `--estagio ambos` for the other placements, and
`--sem-subcooler` to remove the WATER subcooler, not the IHX required by this
new architecture. `--analise comparacao` and `python run.py all` also include
the three new cases. Results go to, for example,
`results/cascata/high-stage_ejector_+_ihx/`. P-h diagrams show both cascade
circuits together at the selected configuration's optimized point.

### Arrangement and balance closure

- Compressor -> condenser -> optional water subcooler -> IHX hot side ->
  ejector motive inlet -> liquid/vapour separator.
- Separator vapour -> IHX cold side -> compressor suction.
- Separator liquid -> expansion valve -> evaporator -> ejector secondary inlet.
- The two cascade refrigerants NEVER mix. The cascade heat exchanger remains
  the thermal coupling between the two independent circuits.

The constant-pressure mixing model follows Fig. 3 and Eqs. (13)-(20) of
Mateu-Royo et al., *International Journal of Refrigeration* 119 (2020),
356-365, [doi:10.1016/j.ijrefrig.2020.07.016](https://doi.org/10.1016/j.ijrefrig.2020.07.016).
Mixing pressure equals the evaporator pressure in this simplified model.
The nozzle, mixing and diffuser efficiencies are EACH 0.50, as in the paper;
this is not a single overall ejector efficiency. The ejector is adiabatic,
with no shaft power, and internal kinetic energy is explicitly retained.

With `mu = evaporator_mass_flow / compressor_mass_flow`, the separator quality
must be `x = 1/(1+mu)`. `scipy.optimize.least_squares` closes this relation
and the ejector outlet/separator pressure simultaneously. Outlet pressure is
calculated from nozzle expansion, momentum mixing and diffuser recovery; it
is not independently chosen by the flash/economizer injection optimizer.
The existing `scipy.optimize.minimize_scalar` still optimizes the low-stage
condensation temperature for maximum WHOLE-CASCADE COP.

The existing evaporator-outlet superheat stays at 5 K. The IHX supplies the
heat required for 5 K superheat relative to saturation at the NEW compressor
suction pressure. Its duty is determined from that requirement; effectiveness
is not freely optimized. A minimum 5 K IHX approach is checked at nine positions
along its counterflow enthalpy profile. Infeasible conditions are rejected,
rather than adding external heat or changing the prescribed boundary conditions.

Only the original external useful heat, `Q_cond,high + Q_water_subcooler`,
counts toward 170 kW. IHX heat is internal and is NEVER added to useful heat.
The reference refrigerants, source/water inputs, main pinches, condenser outlet
subcooling settings, compressor efficiency coefficients and power definition
are unchanged. In particular, the paper's fixed evaporator load, motor efficiency
and boundary temperatures are not substituted for the project's inputs.
No COP gain reported in the paper is applied as a numerical multiplier.
Comparisons with the original no-IHX cases measure the combined ejector + IHX
architecture, not an isolated ejector-only gain. The fixed efficiencies and
equilibrium mixing model do not constitute ejector geometry/choking design or
experimental validation of a real ejector.

### Results and implementation

The result tables distinguish evaporator pressure, compressor suction pressure,
separator pressure, entrainment ratio, separator quality, IHX heat (W), IHX
minimum approach (K), suction superheat (K), and balance residuals. Ejector
flows are not labelled as injected vapour. State CSVs identify both IHX sides,
the nozzle/mixing/diffuser states and both separator outlets.

- `src/hthp/components/ejector.py`: ejector nozzle, mixing and diffuser model.
- `src/hthp/cycles/ejector_cycle.py`: IHX, separator and cycle balances.
- `src/hthp/configurations.py`: integration with the unchanged cascade boundary
  conditions and optional water subcooler.
- `src/hthp/analyses.py`: diagnostic records and branched P-h connections.

Run the independent balance and integration checks with:

```bash
python -m unittest discover -s tests -v
```
