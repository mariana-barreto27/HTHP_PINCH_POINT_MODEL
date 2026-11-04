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
`comparacao` compares all nineteen supported configurations, writes an optimum
summary table, and generates shared COP, compressor-power, and discharge-
temperature curves across the low-stage condensation-temperature sweep. The
comparison plots use curves rather than architecture bar charts.

`python run.py all` performs the selected-model analyses for all nineteen
configurations and then the shared comparisons. It does not reproduce old
single-stage cases with different refrigerants and boundary conditions. IHXs
are present only as part of the explicitly selected ejector + IHX cycle. The
new-model comparisons consistently use the same load, source condition,
subcooler setting, refrigerants, and pinch assumptions so the architectures
can be compared fairly.

To find which of the nineteen configurations has the largest COP, run
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

## Mixed components and comparison views

The original four component types (conventional cycle, flash tank, economizer,
ejector + IHX) retain all sixteen 4 x 4 combinations and the same names/order.
Three additional cases replace the valve with a generic two-phase expander
in the low stage, high stage or both. Expander hybrids with flash tanks,
economizers or ejectors are not part of this initial isolated-component study.
Parallel compressors and double injection have not been added.

Select the low and high components explicitly:

```bash
python run.py --baixa flash --alta economizador --analise curva
python run.py --baixa economizador --alta ejetor --analise ph
```

Use `--baixa`/`--alta` OR the previous `--componente`/`--estagio` syntax, not both.
An omitted stage in the explicit syntax uses the conventional cycle. All five
individual analyses, including the combined optimum P-h diagram, work for the
mixed cases too. Ejector separator pressure still follows its balance closure;
only flash-tank/economizer intermediate pressures use the injection optimizer.

Generate all comparison views with one calculation campaign:

```bash
python run.py --analise comparacao
```

Or calculate just the cases in one family:

```bash
python run.py --analise comparacao --grupo economizador
python run.py --analise comparacao --grupo flash
python run.py --analise comparacao --grupo ejetor
python run.py --analise comparacao --grupo mistas
python run.py --analise comparacao --grupo expansor
```

Each component-family figure includes the seven configurations containing that
original component plus the conventional cascade as a clearly identified reference.
The expander family instead contains its three placements and that same reference.
Different views reuse the same calculated points; they never run new optimizations
just to change a plot grouping. Colors and line styles remain consistent across views.

Comparison output is organized under `results/cascata/comparacao/`:

- `temperature_curves/` and `optima.csv`: the original ten-case comparison is retained.
- `todas_combinacoes/`: all nineteen cases, optima, COP, net power, discharge and efficiency curves.
- `por_componente/economizador/`, `flash_tank/`, `ejetor_ihx/`: component-family COP curves.
- `por_componente/expansor/`: conventional reference and the three expander locations, with gross/recovered/net power curves.
- `combinacoes_mistas/`: the six mixed cases plus the conventional reference.
- `componente_baixa_fixo/`: five views holding the LOW-stage component fixed.
- `componente_alta_fixo/`: five views holding the HIGH-stage component fixed.

"Fixed component" means fixed component TYPE, not a fixed temperature: these
figures still sweep the low-stage condensation temperature. Each view includes
`optima.csv`, the temperature-sweep CSV, PNG/PDF figures and `conditions.json`.

Every new view also includes `cop_gain_vs_low_stage_condensation.png/.pdf` and
`cop_gains.csv`. The gain is `100 * (COP_case / COP_reference - 1)` at the SAME
intermediate temperature. It does not compare each case at its separate optimum.
Family/mixed figures use the conventional reference; fixed-component figures use
the matching case with a conventional cycle in the other circuit. A gap means
the case OR its reference is unavailable there; no gain is interpolated across it.

Views containing the conventional reference also write `optima_summary.csv`,
`optima_summary.md` and a copy-ready `optima_summary.tex` table. The complete
nineteen-case table is in `todas_combinacoes/`, sorted by maximum COP. The
`optima_summary.png/.pdf` versions of this table are ready for slides. It lists
the component in each stage, both optimal coupling temperatures, net shaft
input and the gain over the conventional **own optimum**, with the same
subcooler setting. This table gain is different from the same-temperature gain
in the curves. The detailed `optima.csv` remains available.

For a source-temperature comparison at a fixed low-stage condensation
temperature, also request `--comparar-fonte`. For example:

```bash
python run.py --analise comparacao --grupo expansor --pontos 41 --comparar-fonte --temperatura-baixa 45
```

This adds COP and gain curves for source inlet temperatures from 5 to 40 °C
under `comparacao/fonte/por_componente/expansor/`. It holds low-stage
condensation at 45 °C (high-stage evaporation at 40 °C for the default 5 K
cascade pinch); it does not optimize this temperature at each source point.
The conventional reference uses the same source and coupling temperatures.
Use `--subcooler` or `--sem-subcooler` for separate source campaigns.

After calculating, regenerate figures without solving the cycles again:

```bash
python run.py --analise comparacao --grupo economizador --replotar
python run.py --analise comparacao --replotar
```

`--replotar` only accepts complete saved data with matching parameters, grid,
thermodynamic-code signature and property-library versions. Changed conditions
or equations require a fresh calculation without that flag. A family-only run
does not overwrite the general or original ten-case comparison. `all` continues
to run ALL available analyses; it is not a fast preview mode.

## Output

### Adding components: always include the bare cascade

To distinguish the benefit of a component from the benefit of the water
subcooler, compare BOTH actual model versions in the SAME figure:

```bash
python run.py --analise comparacao --comparar-subcooler
python run.py --analise comparacao --comparar-subcooler --grupo economizador
```

The full figure has 38 cases (19 architectures x 2 subcooler settings).
Each family includes the conventional cascade without a subcooler, the
conventional cascade with a subcooler, and each family configuration with and
without a subcooler. For example: economizer alone; economizer + subcooler;
economizer in one stage + flash tank or ejector + IHX in the other, again with
and without a subcooler. These are actual recalculations, NOT renamed curves.

Same color means the same low/high components. Dashed lines have no water
subcooler; solid lines include the HIGH-stage water subcooler. No low-stage
water subcooler is introduced. The ejector's internal IHX remains installed;
the economizer's internal subcooling is also retained when removing the water
subcooler. "Bare cascade" means conventional cycles in both stages, no
injection/ejector/IHX and no additional water subcooler. The small specified
condenser outlet subcooling remains a boundary assumption, not an added device.

All cases retain the SAME total 170 kW duty (or the requested `--carga`),
refrigerants, water/source boundary conditions, compressor law and pinches.
With the water subcooler enabled, its heat is included in that duty, as in the
existing model; the heat split between that water branch and the main load can
therefore change. This comparison is not a claim of 170 kW supplied entirely
at 120 °C. Intermediate temperatures are swept on the same grid and flash/
economizer intermediate pressures are optimized in each version. Optimum
temperatures are separately optimized, not copied from the subcooler case.

New figures and tables go under `results/cascata/comparacao/adicao_componentes/`,
with `todas_combinacoes/`, `por_componente/` and `combinacoes_mistas/` views.
Every gain figure uses the conventional cascade WITHOUT a subcooler as reference,
at the same intermediate temperature. Existing comparison folders are untouched.
The full campaign also writes the complete **38-case optimum table** to
`results/cascata/comparacao/pontos_otimos/`, separately from the curve caches.
Its CSV, Markdown and LaTeX include both actual subcooler versions; the PNG/PDF
tables are split into `optima_summary_com_subcooler` and
`optima_summary_sem_subcooler` for readability. In the table, the gain compares
each own optimum against the conventional own optimum with the same subcooler
setting, rather than the bare reference used by the paired gain curves.
Compatible versioned data are reused automatically; missing/incompatible data
are recalculated. To only regenerate the figures (fail if recalculation is needed):

```bash
python run.py --analise comparacao --comparar-subcooler --grupo economizador --replotar
```

Use the same load, source, point count and tolerance as the saved campaign.
Do not combine `--comparar-subcooler` with `--sem-subcooler`: the former already
includes both versions. `python run.py all` also generates these addition views.

Only the selected analysis is generated. Files go under `results/`, in folders
named for the cycle, configuration, and analysis. Each run writes a
`conditions.json` so the plotted/result values can be tied to the inputs.
P–h runs also save the state table as CSV.

## Replacing the expansion valve with an expander

This is expansion work recovery INSIDE the heat pump, not a separate ORC.
The original conventional cycle and the sixteen previous configurations remain
unchanged. The existing 170 kW duty, R32/R1233zd(E), external source/sink flows,
compressor correlation and pinches are retained.

Compare the conventional cascade with expanders in the low stage, high stage
and both (four cases only, without recalculating the flash/economizer/ejector cases):

```bash
python run.py --analise comparacao --grupo expansor
```

Optimize and draw BOTH circuits together in the P-h diagram:

```bash
python run.py --componente expansor --estagio ambos --analise ph
```

Use `--estagio alta` or `--estagio baixa` for one circuit. `turbina` is an alias
for `expansor`; it does NOT select a detailed turbine geometry. To compare with
and without the existing HIGH-stage water subcooler:

```bash
python run.py --analise comparacao --grupo expansor --comparar-subcooler
```

Study assumptions are explicit and adjustable:

```bash
python run.py --componente expansor --estagio ambos --analise ponto --eficiencia-expansor 0.50 --recuperacao-expansor 0.90
```

- `--eficiencia-expansor`: isentropic expansion efficiency, default **0.50**,
  an exploratory assumption rather than manufacturer data. Zero reproduces
  the valve; one is ideal isentropic expansion, not a realistic default.
- `--recuperacao-expansor`: fraction of expander shaft output used to assist
  the compressor, default **1.0**, an IDEAL mechanical-transmission assumption.
  Reducing this value exposes unutilized power as an external loss. It is NOT
  the turbine's isentropic efficiency and does not add useful heating capacity.

The expander changes its outlet enthalpy, evaporator heat, source outlet and
cascade heat balance; it is NOT just a subtraction from a saved compressor
power. COP uses NET shaft input, consistent with the integrated reference's
unit motor efficiency. CSVs distinguish gross compressor input, gross
expander output, recovered shaft power, unrecovered power and net input.
The external water-subcooler heat remains included in the total 170 kW as in
the reference: this is not 170 kW delivered entirely at 120 degC.

`scipy.optimize.minimize_scalar` still searches the low-stage condensing
temperature for maximum cascade COP. Expansion outlet pressure is the same
evaporator pressure dictated by the boundaries; no extra arbitrary intermediate
pressure or vapor-injection fraction is optimized. Efficiencies are fixed
scenario inputs, not optimization variables.

New comparison results go to `results/cascata/comparacao/por_componente/expansor/`, and to
`results/cascata/low-stage_expander/`, `high-stage_expander/` or
`expanders_in_both_stages/` for individual analyses. A family-only run does
not overwrite the sixteen-case results previously saved in other folders.
`all` now also includes these three expander cases; it remains a full campaign.

See [the expander model notes](docs/expander_model.md) for equations,
control-volume balances, literature and limitations. It is a generic
equilibrium two-phase expander study, not a validated Tesla/bladed turbine
design or a commercial-machine performance map.

## Project layout

- `run.py`: terminal entry point.
- `src/hthp/model.py`: reference thermodynamic model and cascade optimization.
- `src/hthp/configurations.py`: flash-tank and economizer implementations.
- `src/hthp/analyses.py`: result records, plots, and P–h diagrams.
- `src/hthp/comparisons.py`: grouping, reference gains and saved-data validation.
- `src/hthp/component_comparison.py`: paired component comparisons with/without the water subcooler.
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
or both stages. Six mixed cases additionally combine different component types
across the circuits. The IHX is included ONLY in the stage selected for the ejector;
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
