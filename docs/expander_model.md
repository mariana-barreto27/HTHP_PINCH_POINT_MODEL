# Expansion work recovery inside the cascade heat pump

## Scope and reference

Replace the valve of a conventional heat-pump circuit with an adiabatic,
efficiency-based expander. Keep the original conventional case and all previous
flash-tank, economizer and ejector cases. New placements are low only, high
only and both; they do not add an ORC, change the fluids or replace a compressor.

The fixed reference conditions remain 170 kW TOTAL useful heat, R32 in the low
circuit, R1233zd(E) in the high circuit, and the same flow/pinch/compressor
closure as `model.py`. When the existing high-stage WATER subcooler is on,
its heat is included in those 170 kW. Its water is colder than the main sink;
do not interpret the total as 170 kW delivered entirely at 120 degC.

Cycle path in each selected circuit:

`compressor -> condenser -> optional external water subcooler -> expander -> evaporator`

There is no injection branch, extra pressure level, ejector or IHX in these
new isolated-component cases. The expander outlet pressure is the evaporator
pressure. The same mass flow passes through the compressor and expander.

## Inputs, assumptions and optimization

| Quantity | Initial value | Interpretation |
| --- | --- | --- |
| Expander isentropic efficiency | 0.50 | Exploratory fixed assumption, not fitted manufacturer data |
| Useful fraction of shaft output | 1.00 | Ideal transmission to the compressor shaft; independent of isentropic efficiency |
| Expansion outlet pressure | Evaporator pressure | Set by the existing thermodynamic boundaries |
| Expander heat exchange | Zero | Adiabatic control volume |
| Expander inlet/outlet kinetic energy | Neglected | Specific work follows enthalpy decrease |
| Working-fluid properties | Existing CoolProp backend | Equilibrium single-/two-phase states |
| Temperature search | Existing bounded SciPy optimizer | Maximize cascade COP versus low-stage condensing temperature |

Efficiency and useful shaft fraction accept finite values from zero to one.
They are scenario inputs, NOT freely optimized performance multipliers.
An isentropic efficiency of zero is the valve limit. A useful shaft fraction
of zero means that expansion work is generated but discarded externally:
the expander's outlet state is still different from a valve's outlet state.

## Thermodynamic equations

At the inlet state, take pressure, enthalpy and entropy from the same condenser
and external-subcooler calculation as the baseline. At the prescribed outlet
pressure, calculate the ideal isentropic outlet using real-fluid properties:

\[
h_{\mathrm{out},s}=h(P_{\mathrm{evap}},s_{\mathrm{in}}),\qquad
h_{\mathrm{out}}=h_{\mathrm{in}}-
\eta_{\mathrm{exp,is}}(h_{\mathrm{in}}-h_{\mathrm{out},s}).
\]

The gross expander output and useful shaft recovery are:

\[
\dot W_{\mathrm{exp}}=\dot m(h_{\mathrm{in}}-h_{\mathrm{out}}),\qquad
\dot W_{\mathrm{rec}}=\eta_{\mathrm{use}}\dot W_{\mathrm{exp}},\qquad
\dot W_{\mathrm{loss}}=(1-\eta_{\mathrm{use}})\dot W_{\mathrm{exp}}.
\]

Recovered work assists the compressor shaft. It is not new useful heat:

\[
\dot W_{\mathrm{net}}=\dot W_{\mathrm{comp,gross}}-\dot W_{\mathrm{rec}},\qquad
COP_{\mathrm{cascade}}=
\frac{\dot Q_{\mathrm{useful}}}{\dot W_{\mathrm{net,low}}+\dot W_{\mathrm{net,high}}}.
\]

The integrated model keeps unit motor efficiency, as before, so this is a
shaft-based COP and excludes fans/pumps. The standalone expander-cycle class
can use the existing motor efficiency; shaft recovery occurs before the motor,
so its net electrical input is net shaft input divided by motor efficiency.

The evaporator duty MUST change with the new outlet enthalpy:

\[
\dot Q_{\mathrm{evap}}=\dot m(h_{\mathrm{evap,out}}-h_{\mathrm{exp,out}}).
\]

The high-stage evaporator duty sets the low-stage condenser duty. The existing
source-flow closure, mass flows and outlet temperatures are solved again at
every trial. Keeping old heat duties while only subtracting recovered work
would violate these balances.

## Two control-volume balances

For the refrigerant circuit (gross expander output leaves it):

\[
\dot Q_{\mathrm{cond}}+\dot Q_{\mathrm{sc}}
-\dot Q_{\mathrm{evap}}-\dot W_{\mathrm{comp,gross}}
+\dot W_{\mathrm{exp}}=0.
\]

For the system with useful shaft recovery and external recovery losses:

\[
\dot Q_{\mathrm{useful}}+\dot W_{\mathrm{loss}}
-\dot Q_{\mathrm{source}}-\dot W_{\mathrm{net,total}}=0.
\]

The unutilized shaft output is assumed dissipated outside the useful heat
and source circuits. A different generator/transmission arrangement would
need its own losses and system boundary; it is not silently credited here.

## Files and outputs

- `components/expander.py`: isentropic reference, real outlet state and specific shaft output.
- `cycles/expander_cycle.py`: conventional-circuit topology with the new expansion and shaft recovery.
- `configurations.py`: coupling into the same normalized stages and fixed-flow cascade.
- `analyses.py`: gross/recovered/net powers, corrected loss balance, combined P-h connections.
- `cli.py`: `--componente expansor` (alias `turbina`), location, efficiencies and comparison family.

CSV fields `W_shaft_kW` (legacy alias) and `W_net_shaft_kW` are NET input.
`W_compressor_shaft_kW` is gross compressor demand; `W_expander_shaft_kW`
is gross expander output; `W_recovered_kW` is the portion used at the shaft;
`W_recovery_loss_kW` is the remainder. They are not interchangeable.

The comparison plots retain the previous style and use line curves. A family
run saves COP, net input, gross compressor input, expander output, useful
recovery, compressor discharge/efficiency, same-temperature COP gains, optimum
tables and conditions under `results/cascata/comparacao/por_componente/expansor/`.
P-h runs plot BOTH circuits together at that configuration's own optimized point.

## Verification and limitations

Tests cover both actual fluids, efficiency-zero agreement with the valve,
isentropic-efficiency/entropy consistency, recalculated source heat, positive
net input, loss bookkeeping, all three placements, optional water subcooler,
the existing bounded optimizer, CLI propagation, and combined P-h diagrams.
Original conventional and component regression tests are retained.

This model does NOT specify blade/disc geometry, speed, nozzle choking,
non-equilibrium flashing, phase slip, erosion, leakage, mechanical sizing,
control, cost or a manufacturer operating map. Supporting equilibrium
two-phase states in CoolProp is not proof that a conventional dry-vapor
turbine can accept the liquid/wet expansion encountered here. No minimum
improvement is guaranteed, especially with nonideal shaft utilization and
reclosed finite-source/cascade boundaries.

## Literature and what is (not) imported from it

- Li, L.; An, D.; Xi, H. (2025), *Proposal and optimization of novel heat pump
  cycles with the Tesla turbine as an expansion device*, Energy 340,139276.
  https://doi.org/10.1016/j.energy.2025.139276
  Supports replacing the heat-pump valve with a two-phase expander and
  evaluating uses of recovered work, including R1233zd(E). Our generic
  efficiency model is not their detailed Tesla geometry, redesign or reported
  gain. The default 0.50 is OUR study assumption, not a value attributed to it.
- Kong et al. (2026), *Transcritical-Transcritical Cascade CO2 Heat Pump with
  Expansion Work Recovery: A Thermodynamic Analysis*, Energies19,3767.
  https://doi.org/10.3390/en19163767
  Supports evaluating recovery at whole-cascade level. Its CO2 transcritical
  topology, assumed efficiency and performance gains are not transferred to
  this R32/R1233zd(E) subcritical case.

Hassan et al. (2022), DOI10.1016/j.egyr.2022.08.201, retains a valve in its
heat pump and a separate ORC expander. It does NOT validate replacing the
heat-pump valve with this expander.
