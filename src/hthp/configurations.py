"""Flash tank, economizer and ejector/IHX options for the cascade model.

All external conditions, flow closure, water phase calculation, condenser and
subcooler pinches, compressor coefficients, COP definition and intermediate
temperature optimization belong to the reference model. No unrelated settings
or integrated-cycle solver is imported here. Existing component solvers are
used at prescribed thermodynamic conditions, normalized to 1 kW condenser duty.
"""

from dataclasses import dataclass, replace
from functools import lru_cache
import math

import numpy as np
from scipy.optimize import minimize_scalar

from hthp import model as ref
from hthp.components.compressor_performance import QuadraticPressureRatioEfficiency
from hthp.cycles.flash_tank_cycle import FlashTankCycle, FlashTankCycleConfig
from hthp.cycles.economizer_cycle import EconomizerCycle, EconomizerCycleConfig
from hthp.cycles.simple_cycle import SimpleVaporCompressionCycle, SimpleCycleConfig
from hthp.cycles.ejector_cycle import EjectorCycle, EjectorCycleConfig
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource


@dataclass
class ComponentParams(ref.Params):
    analysis_family: str = "all"
    low_technology: str = "simple"
    high_technology: str = "simple"
    use_subcooler: bool = True  # Same high-stage water subcooler as the reference.
    economizer_effectiveness: float = 0.90
    economizer_minimum_approach_K: float = 5.0
    ejector_nozzle_efficiency: float = 0.50
    ejector_mixing_efficiency: float = 0.50
    ejector_diffuser_efficiency: float = 0.50
    ejector_ihx_minimum_approach_K: float = 5.0
    optimize_injection: bool = True
    injection_fraction_low: float = 0.5
    injection_fraction_high: float = 0.5
    injection_fraction_min: float = 0.05
    injection_fraction_max: float = 0.95
    injection_tolerance: float = 0.005
    injection_grid_points: int = 7
    injection_coordinate_passes: int = 3
    _evaluating_injection: bool = False


BASE_ARCHITECTURES = (
    ("Conventional cascade", "simple", "simple"),
    ("Low-stage flash tank", "flash_tank", "simple"),
    ("High-stage flash tank", "simple", "flash_tank"),
    ("Flash tanks in both stages", "flash_tank", "flash_tank"),
    ("Low-stage economizer", "economizer", "simple"),
    ("High-stage economizer", "simple", "economizer"),
    ("Economizers in both stages", "economizer", "economizer"),
    ("High-stage ejector + IHX", "simple", "ejector"),
    ("Low-stage ejector + IHX", "ejector", "simple"),
    ("Ejectors + IHXs in both stages", "ejector", "ejector"),
)

MIXED_ARCHITECTURES = (
    ("Low-stage flash tank / high-stage economizer", "flash_tank", "economizer"),
    ("Low-stage economizer / high-stage flash tank", "economizer", "flash_tank"),
    ("Low-stage flash tank / high-stage ejector + IHX", "flash_tank", "ejector"),
    ("Low-stage ejector + IHX / high-stage flash tank", "ejector", "flash_tank"),
    ("Low-stage economizer / high-stage ejector + IHX", "economizer", "ejector"),
    ("Low-stage ejector + IHX / high-stage economizer", "ejector", "economizer"),
)

# Keep the ten original names and plotting indices unchanged.
ARCHITECTURES = BASE_ARCHITECTURES + MIXED_ARCHITECTURES


@lru_cache(maxsize=2048)
def _solve_simple(config):
    return SimpleVaporCompressionCycle(config).solve()


@lru_cache(maxsize=2048)
def _solve_flash(config):
    return FlashTankCycle(config).solve()


@lru_cache(maxsize=2048)
def _solve_economizer(config):
    return EconomizerCycle(config).solve()


@lru_cache(maxsize=2048)
def _solve_ejector(config):
    return EjectorCycle(config).solve()


def _normalized_stage(p, stage, Tev, Tcd, q_sc):
    fluid = p.F_h if stage == "h" else p.F_l
    technology = p.high_technology if stage == "h" else p.low_technology
    coefficients = (p.a_is_h, p.b_is_h, p.c_is_h) if stage == "h" else (p.a_is_l, p.b_is_l, p.c_is_l)
    efficiency = QuadraticPressureRatioEfficiency(*coefficients, p.eta_is_min, p.eta_is_max)
    kwargs = dict(refrigerant=fluid, heat_source=FixedTemperatureHeatSource(Tev),
                  condensation_temperature_C=Tcd, heating_capacity_kW=1.0,
                  superheat_K=p.SUP_h if stage == "h" else p.SUP_l,
                  subcooling_K=p.SUB_h if stage == "h" else p.SUB_l,
                  compressor_efficiency_model=efficiency, motor_efficiency=1.0,
                  external_subcooling_specific_heat_kJ_kg=q_sc/1000)
    if technology == "simple":
        result = _solve_simple(SimpleCycleConfig(**kwargs))
        s = result.states
        return dict(result=result, states=s, mass=result.refrigerant_mass_flow_kg_s,
                    main_fraction=1.0, suction=s[1], discharge=s[2], condenser=s[3],
                    sc=s["3E"], evap_in=s[4], work=result.compressor_shaft_power_kW,
                    Qev=result.evaporator_heat_kW, Pint=None,
                    compressors=[(s[1], s[2], 1.0)])
    if technology == "ejector":
        result = _solve_ejector(EjectorCycleConfig(
            **kwargs, nozzle_efficiency=p.ejector_nozzle_efficiency,
            mixing_efficiency=p.ejector_mixing_efficiency,
            diffuser_efficiency=p.ejector_diffuser_efficiency,
            ihx_minimum_approach_K=p.ejector_ihx_minimum_approach_K))
        s = result.states
        return dict(result=result, states=s, mass=result.refrigerant_mass_flow_kg_s,
                    main_fraction=result.entrainment_ratio, technology="ejector",
                    suction=s["suction"], discharge=s["discharge"],
                    condenser=s["condenser_out"], sc=s["subcooler_out"],
                    evap_in=s["evaporator_in"], evap_out=s["evaporator_out"],
                    work=result.compressor_shaft_power_kW,
                    Qev=result.evaporator_heat_kW, Pint=None,
                    compressors=[(s["suction"], s["discharge"], 1.0)])
    fraction = p.injection_fraction_high if stage == "h" else p.injection_fraction_low
    pev, pcd = ref.psat_bar(fluid, Tev, 1), ref.psat_bar(fluid, Tcd, 0)
    kwargs["intermediate_pressure_bar"] = pev * (pcd/pev)**fraction
    if technology == "flash_tank":
        result = _solve_flash(FlashTankCycleConfig(**kwargs))
        vapor_fraction = result.flash_vapor_fraction
    elif technology == "economizer":
        kwargs.update(economizer_effectiveness=p.economizer_effectiveness,
                      economizer_minimum_approach_K=p.economizer_minimum_approach_K)
        result = _solve_economizer(EconomizerCycleConfig(**kwargs))
        vapor_fraction = result.injection_mass_fraction
    else:
        raise ValueError(f"Unknown component: {technology}")
    s = result.states
    return dict(result=result, states=s, mass=result.total_refrigerant_mass_flow_kg_s,
                main_fraction=1-vapor_fraction, suction=s["1"], discharge=s["4"],
                condenser=s["5"], sc=s["5E"], evap_in=s["7"],
                work=result.total_shaft_power_kW, Qev=result.evaporator_heat_kW,
                Pint=result.intermediate_pressure_bar,
                compressors=[(s["1"], s["2"], 1-vapor_fraction), (s["3"], s["4"], 1.0)])


def _to_reference_dict(p, stage, Tev, Tcd, normalized, mass, qsc):
    fluid = p.F_h if stage == "h" else p.F_l
    scale = mass/normalized["mass"]
    suction, discharge = normalized["suction"], normalized["discharge"]
    cond, sc, evap = normalized["condenser"], normalized["sc"], normalized["evap_in"]
    evap_out = normalized.get("evap_out", suction)
    coeff = (p.a_is_h, p.b_is_h, p.c_is_h) if stage == "h" else (p.a_is_l, p.b_is_l, p.c_is_l)
    compressors = []
    for sin, sout, fraction in normalized["compressors"]:
        rp = sout.pressure_Pa/sin.pressure_Pa
        eta = ref.eta_isentropica(rp, *coeff, p.eta_is_min, p.eta_is_max)
        raw_eta = coeff[0] + coeff[1]*rp + coeff[2]*rp**2
        k = ref.cp_TP(fluid, sin.temperature_C, sin.pressure_bar)/ref.cv_TP(fluid, sin.temperature_C, sin.pressure_bar)
        etav = ref.eta_volumetrica(rp, k, p.C_h if stage == "h" else p.C_l)
        v = ref.v_TP(fluid, sin.temperature_C, sin.pressure_bar)
        m = fraction*mass
        # As in the previous component extension, each compression step has
        # its own cylinder/drive sizing; no manufacturer injection map is implied.
        speed = p.N_h if stage == "h" else m*v/(etav*p.V_sw_l)
        volume = m*v/(etav*speed)
        compressors.append(dict(RP=rp, eta_is=eta, eta_raw=raw_eta, eta_v=etav,
                                N=speed, V_sw=volume, T_discharge=sout.temperature_C,
                                m_dot=m, limited=not p.eta_is_min <= raw_eta <= p.eta_is_max))
    W = normalized["work"]*scale*1000
    Qcond, Qev, Qsc = scale*1000, normalized["Qev"]*scale*1000, mass*qsc
    result = dict(fluid=fluid, T_ev=Tev, T_cd=Tcd, T1=suction.temperature_C,
                  T2=discharge.temperature_C, T3=cond.temperature_C, T4=sc.temperature_C,
                  H1=suction.enthalpy_kJ_kg*1000, H2=discharge.enthalpy_kJ_kg*1000,
                  H3=cond.enthalpy_kJ_kg*1000,
                  H4=(sc if stage == "h" else evap).enthalpy_kJ_kg*1000,
                  H5=evap.enthalpy_kJ_kg*1000, P_ev=evap.pressure_bar,
                  H_evap_out=evap_out.enthalpy_kJ_kg*1000,
                  T_evap_out=evap_out.temperature_C,
                  P_suction=suction.pressure_bar,
                  P_cd=cond.pressure_bar, P_int=normalized["Pint"],
                  RP=cond.pressure_Pa/suction.pressure_Pa, eta_is=compressors[-1]["eta_is"],
                  eta_v=compressors[0]["eta_v"], m_dot=mass,
                  m_dot_evap=mass*normalized["main_fraction"],
                  V_sw=compressors[0]["V_sw"], N=compressors[0]["N"],
                  N_rpm=compressors[0]["N"]*60,
                  N_feasible=all(p.N_l_min <= c["N"] <= p.N_l_max for c in compressors),
                  W=W, Q_cond=Qcond, Q_sc=Qsc, Q_ev=Qev, Q_total=Qcond+Qsc,
                  COP=(Qcond+Qsc)/W, residual=Qcond+Qsc-W-Qev,
                  compressors=compressors, component_states=normalized["states"],
                  injection_fraction=(0.0 if normalized.get("technology") == "ejector"
                                      else 1-normalized["main_fraction"]))
    if normalized.get("technology") == "ejector":
        ejector = normalized["result"]
        result.update(
            P_separator=ejector.separator_pressure_bar,
            ejector_entrainment_ratio=ejector.entrainment_ratio,
            ejector_pressure_lift_ratio=ejector.ejector.pressure_lift_ratio,
            separator_vapor_quality=ejector.separator_vapor_quality,
            ejector_closure_residual=ejector.closure_residual,
            separator_mass_residual=ejector.separator_mass_balance_error_kg_s*scale,
            Q_ihx=ejector.ihx_heat_kW*scale*1000,
            ihx_balance_residual=ejector.ihx_balance_error_kW*scale*1000,
            ihx_minimum_approach_K=ejector.ihx_minimum_approach_K,
            compressor_superheat_K=suction.temperature_C
                - normalized["states"]["separator_vapour"].temperature_C,
            evaporator_superheat_K=p.SUP_h if stage == "h" else p.SUP_l,
        )
    return result


def calcular_alta_com_componentes(p, T_ev_h, T_cd_h):
    if ref.MODO_DIMENSIONAMENTO != "CAPACIDADE":
        raise ValueError("Component extensions currently require CAPACIDADE sizing.")
    Pcd = ref.psat_bar(p.F_h, T_cd_h, 0)
    T3 = T_cd_h-p.SUB_h
    H3 = ref.h_QT(p.F_h, T_cd_h, 0) if p.SUB_h == 0 else ref.h_TP(p.F_h, T3, Pcd)
    Qwater, dhref = ref.limites_subresfriador(p, p.F_h, Pcd, T3, H3) if p.use_subcooler else (0.0, 0.0)
    qsc = 0.0
    previous_error = math.inf
    # Coupled subcooler/injection closure. The target heat includes Qcond+Qsc;
    # Qsc=min(water-terminal limit, refrigerant-terminal limit), exactly as
    # in the reference (no effectiveness or assumed C_min here).
    for _ in range(100):
        normalized = _normalized_stage(p, "h", T_ev_h, T_cd_h, qsc)
        qcond = 1000/normalized["mass"]
        mass = p.Q_target/(qcond+qsc)
        expected = ref.calor_subresfriador(mass, Qwater, dhref)/mass
        if abs(expected-qsc)*mass < 1e-5:
            return _to_reference_dict(p, "h", T_ev_h, T_cd_h, normalized, mass, qsc)
        error = abs(expected-qsc)
        qsc = expected if error < previous_error else 0.5*(qsc+expected)
        previous_error = error
    raise ValueError("Subcooler/component energy closure did not converge.")


def calcular_baixa_com_componentes(p, T_ev_l, T_cd_l, Q_cond_required):
    normalized = _normalized_stage(p, "l", T_ev_l, T_cd_l, 0.0)
    mass = normalized["mass"]*Q_cond_required/1000
    return _to_reference_dict(p, "l", T_ev_l, T_cd_l, normalized, mass, 0.0)


def otimizar_injecao(p, T_cd_l):
    """Maximize the complete cascade COP, reclosing fixed flows at every trial.

Log-pressure fractions are bounded in (0,1). A grid seeds coordinate-wise
bounded SciPy searches. This is a numerical candidate, not a global guarantee.
The pressure search is distinct from the unchanged reference Tcond optimizer.
"""
    fields = [name for name, technology in (
        ("injection_fraction_low", p.low_technology),
        ("injection_fraction_high", p.high_technology))
        if technology in ("flash_tank", "economizer")]
    if not fields:
        return ref.ciclo_cascata(replace(p, _evaluating_injection=True), T_cd_l)
    cache = {}
    best = None

    def evaluate(values):
        nonlocal best
        key = tuple(round(float(v), 10) for v in values)
        if key not in cache:
            case = replace(p, _evaluating_injection=True, **dict(zip(fields, key)))
            try:
                result = ref.ciclo_cascata(case, T_cd_l)
                result["injection_search_fractions"] = dict(zip(fields, key))
                cache[key] = result
                if best is None or result["COP"] > best["COP"]:
                    best = result
            except ValueError:
                cache[key] = None
        return cache[key]

    values = np.array([getattr(p, f) for f in fields], dtype=float)
    grid = np.linspace(p.injection_fraction_min, p.injection_fraction_max, p.injection_grid_points)
    evaluate(values)
    # Joint coarse seeding avoids rejecting a two-component configuration just
    # because its initial geometric pressures were infeasible.
    if len(fields) == 2:
        for a in grid[::2]:
            for b in grid[::2]:
                evaluate([a, b])
        if best:
            values = np.array([best["injection_search_fractions"][f] for f in fields])
    for _ in range(p.injection_coordinate_passes):
        previous = values.copy()
        for dimension in range(len(fields)):
            candidates = []
            for value in grid:
                trial = values.copy(); trial[dimension] = value
                result = evaluate(trial)
                if result is not None:
                    candidates.append((result["COP"], value))
            if not candidates:
                continue
            _, seed = max(candidates)
            index = int(np.argmin(abs(grid-seed)))
            def objective(value):
                trial = values.copy(); trial[dimension] = value
                result = evaluate(trial)
                return 1e6 if result is None else -result["COP"]
            result = minimize_scalar(objective, method="bounded",
                                     bounds=(grid[max(0,index-1)], grid[min(len(grid)-1,index+1)]),
                                     options={"xatol": p.injection_tolerance, "maxiter": 40})
            if result.success:
                objective(result.x)
            if best:
                values = np.array([best["injection_search_fractions"][f] for f in fields])
        if np.max(abs(values-previous)) < p.injection_tolerance:
            break
    if best is None:
        raise ValueError("No feasible flash/economizer pressure found.")
    best["injection_search_evaluations"] = len(cache)
    return best
