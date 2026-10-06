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
