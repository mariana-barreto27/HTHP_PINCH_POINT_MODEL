from dataclasses import dataclass, replace
from functools import lru_cache
from time import perf_counter
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize_scalar
from CoolProp.CoolProp import AbstractState, HmassP_INPUTS, PSmass_INPUTS, PT_INPUTS, QT_INPUTS, PropsSI
from hthp.plots.figures import create_figure
from hthp.plots.heatmap import heatmap
from hthp.plots.cycles import make_cycle, plot_ph, plot_ts
from hthp.plots.cycles.diagrams import plot_cycles
from hthp.plots.style import COLORS, DASHES, MARKERS, MM, add_minor_grid

# ============================================================
# MODELO SIMPLIFICADO PARA DIMENSIONAMENTO DA HEAT PUMP
# ============================================================
# Objetivo principal:
# 1) calcular o ciclo termodinâmico;
# 2) impor os pinch points desejados;
# 3) calcular o UA necessário de cada trocador;
# 4) comparar COP entre pares de refrigerantes.
#
# Hipótese dos trocadores:
# - todos em contracorrente;
# - refrigerante tratado como isotérmico na temperatura de saturação para o cálculo do LMTD/UA;
# - superaquecimento e subresfriamento continuam sendo considerados no ciclo termodinâmico e podem ser alterados pelo usuário.

# Potência de ventiladores e bombas desconsideradas

# ============================================================
# CONFIGURAÇÃO
# ============================================================

MODO_ENTRADA_EXTERNA = "VAZAO"          # "DELTA_T" ou "VAZAO" (m³/h na entrada)
MODO_CICLO = "CASCATA"                  # "CASCATA" ou "ALTA"
MODO_DIMENSIONAMENTO = "CAPACIDADE"     # "CAPACIDADE" ou "DESLOCAMENTO"
MODO_OTIMIZACAO = "SIM"                 # "SIM" ou "NAO" - Otimiza a temperatura de condensação do ciclo de baixa 
T_CD_L_FIXA = 45.0                      # [°C], usada se MODO_OTIMIZACAO = "NAO" Temperatura de condensação do ciclo de baixa é fixa (controle de rotação)

PLOTAR_PH = False
PLOTAR_TS = False
PLOTAR_PERFIS_TROCADORES = True
CALCULAR_HEATMAP_COP = True
CALCULAR_HEATMAP_COMPARACAO = False
PLOTAR_UA_PINCH = False
PLOTAR_COP_PINCH = False
HEATMAP_MOSTRAR_PROGRESSO = False
CALCULAR_HEATMAP_RPM_BAIXA = False
N_PONTOS_PERFIL = 10


# Pares usados no heatmap de comparação
PAR_BASE_H = "R245fa"
PAR_BASE_L = "R410A"
PAR_NOVO_H = "R1233zd(E)"
PAR_NOVO_L = "R32"
COMPARACAO_RELATIVA = True               # True: Delta COP [%] | False: Delta COP [-]

# ============================================================
# CONFIGURAÇÃO DOS HEATMAPS
# ============================================================

T_W_MAP_MIN = 90.0
T_W_MAP_MAX = 130.0
T_W_MAP_STEP = 5

T_SOURCE_ALTA_MIN = 40.0
T_SOURCE_ALTA_MAX = 80.0
T_SOURCE_ALTA_STEP = 5
CONTOUR_STEP_ALTA = 0.5

T_SOURCE_CASCATA_MIN = 5.0
T_SOURCE_CASCATA_MAX = 40.0
T_SOURCE_CASCATA_STEP = 5
CONTOUR_STEP_CASCATA = 0.2

# ============================================================
# PARÂMETROS
# ============================================================

@dataclass
class Params:
    # Condições externas
    F_source: str = "Air"                # "Air" = ar ou "Water" = água
    T_source_in: float = 30.0            # temperatura de entrada da fonte [°C]
    P_source: float    = 1.0             # pressão da fonte [bar]
    
    # Estado de entrada da água no condensador.
    MODO_AGUA_COND: str = "SATURADO"    # "SUBRESFRIADO" ou "SATURADO"
    T_w_cond_in: float = 120            # [°C], usada somente em SUBRESFRIADO
    P_w_cond_liq: float = 5.0           # [bar absolutos], usada somente em SUBRESFRIADO
    
    T_sat_w_cond: float = 120           # [°C], usada somente em SATURADO; Entrada líquido bifásico
    
    T_w_sc_in: float = 25.0             # água de entrada do subresfriador externo [°C]
    m_dot_w_sc: float = 270/3600.0      # vazão de água no subresfriador [kg/s]

    # Refrigerantes
    F_h: str = "R1233zd(E)"             # ciclo de alta
    F_l: str = "R32"                    # ciclo de baixa
    

    # (Usado caso MODO_ENTRADA_EXTERNA = VAZAO)
    modo_entrada_externa: str = MODO_ENTRADA_EXTERNA
    # Evaporador: somente a vazão do fluido selecionado em F_source é usada.
    V_dot_air_evap: float = 60000.0      # vazão de ar da fonte [m³/h], usada com F_source="Air"
    V_dot_w_evap: float = 16.0           # vazão de água da fonte [m³/h], usada com F_source="Water"
    V_dot_w_cond: float = 30.0           # vazão de água do sumidouro [m³/h]

    # Variações de temperatura externas  (Usado caso MODO_ENTRADA_EXTERNA = DELTA T)
    DT_w_cond: float = 5.0               # água no condensador: T_out - T_in [K]
    DT_source: float = 5.0               # fonte: T_in - T_out [K]

    # Pinch points desejados
    DT_pinch_cond: float = 10.0         # T_cd,h - T_água,out [K]
    DT_pinch_cascade: float = 10.0      # T_cd,l - T_ev,h [K]
    DT_pinch_evap: float = 10.0         # T_fonte,out - T_ev [K]
    DT_pinch_sc: float = 20.0           # Pinch do subresfriador [K]

    # Superaquecimento e subresfriamento
    SUP_h: float = 5.0                   # [K]
    SUP_l: float = 5.0                   # [K]
    SUB_h: float = 0.01                  # [K]
    SUB_l: float = 0.01                  # [K]

    # Subresfriador externo do ciclo de alta
    # Q_sc é calculado para que o menor DT terminal seja DT_pinch_sc.

    # Capacidade térmica útil
    Q_target: float = 170000.0           # [W]

    # Compressor de alta
    V_sw_h: float = 0.0014               # [m³/rev]
    N_h: float = 60.0                    # [rev/s]
    C_h: float = 0.02
    
    # Eficiência isentrópica = a + b*RP + c*RP^2
    # a_is_h: float = -0.29
    # b_is_h: float = 0.33
    # c_is_h: float = -0.027
    
    a_is_h: float = 0.8
    b_is_h: float = -0.015
    c_is_h: float = 0

    # Compressor de baixa
    V_sw_l: float = 0.0005               # [m³/rev]
    N_l_min: float = 10.0                # [rev/s]
    N_l_max: float = 100.0               # [rev/s]
    C_l: float = 0.02
    
    # Eficiência isentrópica = a + b*RP + c*RP^2
    # a_is_l: float = 0.45
    # b_is_l: float = 0.16
    # c_is_l: float = -0.027
    
    a_is_l: float = 0.8
    b_is_l: float = -0.015
    c_is_l: float = 0

    eta_is_min: float = 0.40
    eta_is_max: float = 0.90
    
    # Busca da temperatura intermediária
    T_cd_l_min: float = 25.0
    T_cd_l_crit_margin: float = 7.0
    T_cd_l_step: float = 5.0
    T_cd_l_step_map: float = 5.0

    @property
    def P_w_cond(self):
        """Pressão efetiva [bar absolutos] segundo o modo de entrada da água."""
        if self.MODO_AGUA_COND == "SATURADO":
            return pressao_saturacao_agua(self.T_sat_w_cond)
        if self.MODO_AGUA_COND == "SUBRESFRIADO":
            return self.P_w_cond_liq
        raise ValueError('MODO_AGUA_COND deve ser "SUBRESFRIADO" ou "SATURADO".')

# ============================================================
# CONVERSÕES E PROPRIEDADES
# ============================================================

def C2K(T_C): return T_C + 273.15
def K2C(T_K): return T_K - 273.15
def bar2pa(P_bar): return P_bar * 1e5
def pa2bar(P_Pa): return P_Pa / 1e5

AS = {}

def get_state(fluid):
    if fluid not in AS: AS[fluid] = AbstractState("HEOS", fluid)
    return AS[fluid]

CACHE_PROPRIEDADES_MAX = 32768

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def psat_bar(fluid, T_C, Q):
    st = get_state(fluid); st.update(QT_INPUTS, Q, C2K(T_C)); return pa2bar(st.p())

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def h_QT(fluid, T_C, Q):
    st = get_state(fluid); st.update(QT_INPUTS, Q, C2K(T_C)); return st.hmass()

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def h_TP(fluid, T_C, P_bar):
    st = get_state(fluid); st.update(PT_INPUTS, bar2pa(P_bar), C2K(T_C)); return st.hmass()

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def s_TP(fluid, T_C, P_bar):
    st = get_state(fluid); st.update(PT_INPUTS, bar2pa(P_bar), C2K(T_C)); return st.smass()

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def rho_TP(fluid, T_C, P_bar):
    st = get_state(fluid); st.update(PT_INPUTS, bar2pa(P_bar), C2K(T_C)); return st.rhomass()

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def cp_TP(fluid, T_C, P_bar):
    st = get_state(fluid); st.update(PT_INPUTS, bar2pa(P_bar), C2K(T_C)); return st.cpmass()

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def cv_TP(fluid, T_C, P_bar):
    st = get_state(fluid); st.update(PT_INPUTS, bar2pa(P_bar), C2K(T_C)); return st.cvmass()

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def h_PS(fluid, P_bar, s):
    st = get_state(fluid); st.update(PSmass_INPUTS, bar2pa(P_bar), s); return st.hmass()

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def T_PH(fluid, P_bar, h):
    st = get_state(fluid); st.update(HmassP_INPUTS, h, bar2pa(P_bar)); return K2C(st.T())

def v_TP(fluid, T_C, P_bar): return 1.0 / rho_TP(fluid, T_C, P_bar)

def limpar_cache_propriedades():
    for func in (psat_bar, h_QT, h_TP, s_TP, rho_TP, cp_TP, cv_TP, h_PS, T_PH): func.cache_clear()

# ============================================================
# COMPRESSORES
# ============================================================

def eta_isentropica(RP, a, b, c, eta_min, eta_max):
    return float(np.clip(a + b * RP + c * RP**2, eta_min, eta_max))

def eta_volumetrica(RP, k, clearance):
    eta_v = 1.0 - clearance * (RP**(1.0 / k) - 1.0)
    if not 0.0 < eta_v <= 1.0: raise ValueError(f"Eficiência volumétrica não física: {eta_v:.4f}")
    return eta_v

# ============================================================
# TEMPERATURAS DEFINIDAS PELOS PINCH POINTS
# ============================================================

@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def pressao_saturacao_agua(T_C):
    if not np.isfinite(T_C) or not PropsSI("Ttriple", "Water") < C2K(T_C) < PropsSI("Tcrit", "Water"):
        raise ValueError("T_sat_w_cond deve ser finita e estar entre as temperaturas tripla e crítica da água [°C].")
    return pa2bar(PropsSI("P", "T", C2K(T_C), "Q", 0, "Water"))


@lru_cache(maxsize=CACHE_PROPRIEDADES_MAX)
def saturacao_agua(P_bar):
    pressure = bar2pa(P_bar)
    if not np.isfinite(pressure) or not PropsSI("ptriple", "Water") < pressure < PropsSI("pcrit", "Water"):
        raise ValueError("P_w_cond deve estar entre as pressões tripla e crítica da água.")
    return (K2C(PropsSI("T", "P", pressure, "Q", 0, "Water")),
            PropsSI("H", "P", pressure, "Q", 0, "Water"),
            PropsSI("H", "P", pressure, "Q", 1, "Water"),
            PropsSI("D", "P", pressure, "Q", 0, "Water"))


def entrada_agua_condensador(p):
    """SUBRESFRIADO: T e P independentes; SATURADO: T_sat e título zero."""
    Tsat, hf, hg, rho_f = saturacao_agua(p.P_w_cond)
    if p.MODO_AGUA_COND == "SATURADO":
        return Tsat, hf, rho_f
    if p.T_w_cond_in is None or not np.isfinite(p.T_w_cond_in):
        raise ValueError("Em SUBRESFRIADO, informe T_w_cond_in finita em °C.")
    if p.T_w_cond_in >= Tsat - 1e-4:
        raise ValueError(f"Em SUBRESFRIADO, T_w_cond_in deve ser menor que T_sat={Tsat:.5f} °C "
                         f"na pressão de {p.P_w_cond:.5f} bar. Para líquido saturado, use MODO_AGUA_COND=SATURADO.")
    return p.T_w_cond_in, h_TP("Water", p.T_w_cond_in, p.P_w_cond), rho_TP("Water", p.T_w_cond_in, p.P_w_cond)


def estado_agua_condensador(p, high, T_out):
    T_in, h_in, rho_in = entrada_agua_condensador(p)
    Tsat, hf, hg, _ = saturacao_agua(p.P_w_cond)
    if p.modo_entrada_externa == "VAZAO":
        m = p.V_dot_w_cond * rho_in / 3600.0
        h_out = h_in + high["Q_cond"] / m
        T_out = T_PH("Water", p.P_w_cond, h_out)
    else:
        if abs(T_out - Tsat) <= 1e-4:
            raise ValueError("Saída na saturação não é definida apenas por delta T. Use modo VAZAO para calcular o título.")
        h_out = h_TP("Water", T_out, p.P_w_cond)
        if h_out <= h_in:
            raise ValueError("O condensador deve aumentar a entalpia da água; para vaporização isotérmica use VAZAO.")
        m = high["Q_cond"] / (h_out - h_in)
    titulo = (h_out - hf) / (hg - hf)
    if titulo < 0:
        fase, titulo = "líquido subresfriado", None
    elif titulo > 1:
        fase, titulo = "vapor superaquecido", None
    else:
        fase = "bifásico" if 0 < titulo < 1 else ("líquido saturado" if titulo == 0 else "vapor saturado")
    return dict(T_w_cond_in=T_in, T_w_cond_out=T_out, H_w_cond_in=h_in,
                H_w_cond_out=h_out, m_dot_w_cond=m, rho_w_cond_in=rho_in,
                T_sat_w_cond=Tsat, fase_w_cond_out=fase, titulo_w_cond_out=titulo)


def temperaturas_condensador(p):
    T_w_out = entrada_agua_condensador(p)[0] + p.DT_w_cond
    T_cd_h = T_w_out + p.DT_pinch_cond
    return T_w_out, T_cd_h

def temperaturas_evaporador(p):
    T_source_out = p.T_source_in - p.DT_source
    T_ev = T_source_out - p.DT_pinch_evap
    return T_source_out, T_ev

def T_cd_l_max(p): return PropsSI("Tcrit", p.F_l) - 273.15 - p.T_cd_l_crit_margin

# ============================================================
# SUBRESFRIADOR EXTERNO — PINCH EM CONTRACORRENTE
# ============================================================

def limites_subresfriador(p, fluid, P_ref, T_ref_in, H_ref_in):
    if p.DT_pinch_sc <= 0.0: raise ValueError("DT_pinch_sc deve ser positivo.")
    if p.m_dot_w_sc <= 0.0: raise ValueError("m_dot_w_sc deve ser positiva.")
    if T_ref_in - p.T_w_sc_in <= p.DT_pinch_sc: raise ValueError("Diferença de temperatura insuficiente para o pinch do subresfriador.")

    # Terminal quente: T_ref,in - T_agua,out = DT_pinch_sc
    H_w_in = h_TP("Water", p.T_w_sc_in, p.P_w_cond)
    H_w_lim = h_TP("Water", T_ref_in - p.DT_pinch_sc, p.P_w_cond)
    Q_lim_agua = p.m_dot_w_sc * (H_w_lim - H_w_in)

    # Terminal frio: T_ref,out - T_agua,in = DT_pinch_sc
    H_ref_lim = h_TP(fluid, p.T_w_sc_in + p.DT_pinch_sc, P_ref)
    dh_lim_ref = H_ref_in - H_ref_lim

    if Q_lim_agua <= 0.0 or dh_lim_ref <= 0.0: raise ValueError("Pinch do subresfriador sem solução física.")
    return Q_lim_agua, dh_lim_ref

def calor_subresfriador(m_dot_ref, Q_lim_agua, dh_lim_ref):
    return min(Q_lim_agua, m_dot_ref * dh_lim_ref)

def vazao_para_capacidade(Q_target, dh_cond, Q_lim_agua, dh_lim_ref):
    m = Q_target / (dh_cond + dh_lim_ref)
    if m * dh_lim_ref <= Q_lim_agua: return m
    return (Q_target - Q_lim_agua) / dh_cond

# ============================================================
# LMTD E UA — TODOS OS TROCADORES EM CONTRACORRENTE
# ============================================================

def deltaT_lm(DT1, DT2):
    if DT1 <= 0.0 or DT2 <= 0.0: raise ValueError(f"Diferença terminal não física: DT1={DT1:.3f} K, DT2={DT2:.3f} K")
    if abs(DT1 - DT2) < 1e-9: return DT1
    return (DT2 - DT1) / np.log(DT2 / DT1)

def calcular_UA(Q, DT1, DT2):
    if Q <= 0.0: raise ValueError("Q deve ser positivo para calcular UA.")
    DTlm = deltaT_lm(DT1, DT2)
    return Q / DTlm, DTlm

def dimensionar_trocadores(p, ciclo):
    high = ciclo["high"]
    UA = {}

    # Condensador principal: LMTD simplificado com refrigerante isotérmico em T_cd,h.
    DT1 = high["T_cd"] - ciclo["T_w_cond_out"]
    DT2 = high["T_cd"] - ciclo["T_w_cond_in"]
    ua, dtlm = calcular_UA(high["Q_cond"], DT1, DT2)
    # Se houver mudança de fase da água, integra UA por trechos em entalpia,
    # mantendo a hipótese de refrigerante isotérmico adotada pelo modelo.
    _, hf, hg, _ = saturacao_agua(p.P_w_cond)
    h_in, h_out = ciclo["H_w_cond_in"], ciclo["H_w_cond_out"]
    if h_out > hf and h_in < hg:
        limites = sorted(set([h_in, h_out] + [h for h in (hf, hg) if h_in < h < h_out]))
        ua = 0.0
        for a, b in zip(limites[:-1], limites[1:]):
            hs = np.linspace(a, b, 33)
            Ts = [T_PH("Water", p.P_w_cond, float(h)) for h in hs]
            for j in range(len(hs) - 1):
                ua += ciclo["m_dot_w_cond"] * (hs[j+1] - hs[j]) / deltaT_lm(high["T_cd"] - Ts[j], high["T_cd"] - Ts[j+1])
        dtlm = high["Q_cond"] / ua
    UA["cond_h"] = dict(Q=high["Q_cond"], DT1=DT1, DT2=DT2, DTlm=dtlm, UA=ua, pinch=min(DT1, DT2))

    # Subresfriador externo: ambos os lados monofásicos, contracorrente.
    if high["Q_sc"] > 0.0:
        h_w_in = h_TP("Water", p.T_w_sc_in, p.P_w_cond)
        T_w_sc_out = T_PH("Water", p.P_w_cond, h_w_in + high["Q_sc"]/p.m_dot_w_sc)
        DT1 = high["T3"] - T_w_sc_out
        DT2 = high["T4"] - p.T_w_sc_in
        ua, dtlm = calcular_UA(high["Q_sc"], DT1, DT2)
        UA["subcooler"] = dict(Q=high["Q_sc"], DT1=DT1, DT2=DT2, DTlm=dtlm, UA=ua, pinch=min(DT1, DT2), T_w_out=T_w_sc_out)
    else:
        UA["subcooler"] = dict(Q=0.0, DT1=np.nan, DT2=np.nan, DTlm=np.nan, UA=0.0, pinch=np.nan, T_w_out=p.T_w_sc_in)

    if ciclo["mode"] == "CASCATA":
        low = ciclo["low"]
        DT = low["T_cd"] - high["T_ev"]
        ua, dtlm = calcular_UA(high["Q_ev"], DT, DT)
        UA["cascade"] = dict(Q=high["Q_ev"], DT1=DT, DT2=DT, DTlm=dtlm, UA=ua, pinch=DT)

        DT1 = p.T_source_in - low["T_ev"]
        DT2 = ciclo["T_source_out"] - low["T_ev"]
        ua, dtlm = calcular_UA(low["Q_ev"], DT1, DT2)
        UA["evap_l"] = dict(Q=low["Q_ev"], DT1=DT1, DT2=DT2, DTlm=dtlm, UA=ua, pinch=min(DT1, DT2))
    else:
        DT1 = p.T_source_in - high["T_ev"]
        DT2 = ciclo["T_source_out"] - high["T_ev"]
        ua, dtlm = calcular_UA(high["Q_ev"], DT1, DT2)
        UA["evap_h"] = dict(Q=high["Q_ev"], DT1=DT1, DT2=DT2, DTlm=dtlm, UA=ua, pinch=min(DT1, DT2))
    return UA

# ============================================================
# ESTÁGIO DE ALTA
# ============================================================

def calcular_estagio_alta(p, T_ev_h, T_cd_h):
    # Extensão opcional: Params() continua executando o código original abaixo.
    if getattr(p, "high_technology", "simple") != "simple" or not getattr(p, "use_subcooler", True):
        from hthp.configurations import calcular_alta_com_componentes
        return calcular_alta_com_componentes(p, T_ev_h, T_cd_h)
    if p.SUP_h < 0 or p.SUB_h < 0: raise ValueError("SUP_h e SUB_h devem ser >= 0.")
    if T_cd_h >= K2C(get_state(p.F_h).T_critical()): raise ValueError(f"{p.F_h}: T_cd,h >= Tcrit.")
    if T_ev_h + p.SUP_h >= T_cd_h: raise ValueError("Níveis térmicos incompatíveis no estágio de alta.")

    P_ev = psat_bar(p.F_h, T_ev_h, 1)
    P_cd = psat_bar(p.F_h, T_cd_h, 0)
    T1 = T_ev_h + p.SUP_h
    H1 = h_TP(p.F_h, T1, P_ev)
    S1 = s_TP(p.F_h, T1, P_ev)
    v1 = v_TP(p.F_h, T1, P_ev)

    RP = P_cd / P_ev
    eta_is = eta_isentropica(RP, p.a_is_h, p.b_is_h, p.c_is_h, p.eta_is_min, p.eta_is_max)
    H2s = h_PS(p.F_h, P_cd, S1)
    H2 = H1 + (H2s - H1) / eta_is
    T2 = T_PH(p.F_h, P_cd, H2)
    eta_v = eta_volumetrica(RP, cp_TP(p.F_h, T1, P_ev)/cv_TP(p.F_h, T1, P_ev), p.C_h)

    T3 = T_cd_h - p.SUB_h
    H3 = h_QT(p.F_h, T_cd_h, 0) if p.SUB_h == 0 else h_TP(p.F_h, T3, P_cd)
    dh_cond = H2 - H3
    if dh_cond <= 0.0: raise ValueError("Delta h do condensador de alta não físico.")

    Q_lim_agua, dh_lim_ref = limites_subresfriador(p, p.F_h, P_cd, T3, H3)

    if MODO_DIMENSIONAMENTO == "CAPACIDADE":
        m_dot = vazao_para_capacidade(p.Q_target, dh_cond, Q_lim_agua, dh_lim_ref)
        V_sw = m_dot * v1 / (eta_v * p.N_h)
    elif MODO_DIMENSIONAMENTO == "DESLOCAMENTO":
        V_sw = p.V_sw_h
        m_dot = eta_v * V_sw * p.N_h / v1
    else:
        raise ValueError("MODO_DIMENSIONAMENTO deve ser 'CAPACIDADE' ou 'DESLOCAMENTO'.")

    Q_sc = calor_subresfriador(m_dot, Q_lim_agua, dh_lim_ref)
    H4 = H3 - Q_sc/m_dot
    T4 = T_PH(p.F_h, P_cd, H4)
    H5 = H4

    W = m_dot * (H2-H1)
    Q_cond = m_dot * dh_cond
    Q_ev = m_dot * (H1-H5)
    Q_total = Q_cond + Q_sc
    return dict(fluid=p.F_h, T_ev=T_ev_h, T_cd=T_cd_h, T1=T1, T2=T2, T3=T3, T4=T4, H1=H1, H2=H2, H3=H3, H4=H4, H5=H5,
                P_ev=P_ev, P_cd=P_cd, RP=RP, eta_is=eta_is, eta_v=eta_v, m_dot=m_dot, V_sw=V_sw, N_rpm=p.N_h*60.0,
                W=W, Q_cond=Q_cond, Q_sc=Q_sc, Q_ev=Q_ev, Q_total=Q_total, COP=Q_total/W, residual=Q_total-W-Q_ev)

# ============================================================
# ESTÁGIO DE BAIXA
# ============================================================

def calcular_estagio_baixa(p, T_ev_l, T_cd_l, Q_cond_required):
    if getattr(p, "low_technology", "simple") != "simple":
        from hthp.configurations import calcular_baixa_com_componentes
        return calcular_baixa_com_componentes(p, T_ev_l, T_cd_l, Q_cond_required)
    if p.SUP_l < 0 or p.SUB_l < 0: raise ValueError("SUP_l e SUB_l devem ser >= 0.")
    if T_cd_l >= K2C(get_state(p.F_l).T_critical()): raise ValueError(f"{p.F_l}: T_cd,l >= Tcrit.")
    if T_ev_l + p.SUP_l >= T_cd_l: raise ValueError("Níveis térmicos incompatíveis no estágio de baixa.")

    P_ev = psat_bar(p.F_l, T_ev_l, 1)
    P_cd = psat_bar(p.F_l, T_cd_l, 0)

    T1 = T_ev_l + p.SUP_l
    H1 = h_TP(p.F_l, T1, P_ev)
    S1 = s_TP(p.F_l, T1, P_ev)
    v1 = v_TP(p.F_l, T1, P_ev)

    RP = P_cd / P_ev
    eta_is = eta_isentropica(RP, p.a_is_l, p.b_is_l, p.c_is_l, p.eta_is_min, p.eta_is_max)
    H2s = h_PS(p.F_l, P_cd, S1)
    H2 = H1 + (H2s - H1) / eta_is
    T2 = T_PH(p.F_l, P_cd, H2)
    eta_v = eta_volumetrica(RP, cp_TP(p.F_l, T1, P_ev) / cv_TP(p.F_l, T1, P_ev), p.C_l)

    T3 = T_cd_l - p.SUB_l
    H3 = h_QT(p.F_l, T_cd_l, 0) if p.SUB_l == 0 else h_TP(p.F_l, T3, P_cd)
    H4 = H3
    dh_cond = H2 - H3
    dh_ev = H1 - H4
    if dh_cond <= 0 or dh_ev <= 0: raise ValueError("Delta h não físico no estágio de baixa.")

    m_dot = Q_cond_required / dh_cond
    N = m_dot * v1 / (eta_v * p.V_sw_l)
    W = m_dot * (H2 - H1)
    Q_cond = m_dot * dh_cond
    Q_ev = m_dot * dh_ev
    return dict(fluid=p.F_l, T_ev=T_ev_l, T_cd=T_cd_l, T1=T1, T2=T2, T3=T3, H1=H1, H2=H2, H3=H3, H4=H4,
                P_ev=P_ev, P_cd=P_cd, RP=RP, eta_is=eta_is, eta_v=eta_v, m_dot=m_dot, V_sw=p.V_sw_l, N=N,
                N_rpm=N*60.0, N_feasible=p.N_l_min <= N <= p.N_l_max, W=W, Q_cond=Q_cond, Q_ev=Q_ev)

# ============================================================
# CICLO SOMENTE DE ALTA
# ============================================================

def resolver_entradas_externas(p, T_cd_l=None):
    """Fecha simultaneamente cargas, temperaturas e pinch para vazões fixas."""
    if p.F_source not in ("Air", "Water"):
        raise ValueError('F_source deve ser "Air" (ar) ou "Water" (água).')
    if p.modo_entrada_externa not in ("DELTA_T", "VAZAO"):
        raise ValueError("modo_entrada_externa deve ser 'DELTA_T' ou 'VAZAO'.")
    T_w_in, h_w_in, rho_w_in = entrada_agua_condensador(p)
    p = replace(p, T_w_cond_in=T_w_in)
    if p.modo_entrada_externa == "DELTA_T":
        return p
    nome_vazao_fonte = "V_dot_air_evap" if p.F_source == "Air" else "V_dot_w_evap"
    for nome in (nome_vazao_fonte, "V_dot_w_cond"):
        valor = getattr(p, nome)
        if not np.isfinite(valor) or valor <= 0:
            raise ValueError(f"{nome} deve ser finita e positiva [m³/h].")

    # Vazões volumétricas reais na entrada (não normalizadas).
    m_dot_source = getattr(p, nome_vazao_fonte) * rho_TP(p.F_source, p.T_source_in, p.P_source) / 3600.0
    m_dot_w_cond = p.V_dot_w_cond * rho_w_in / 3600.0
    h_s_in = h_TP(p.F_source, p.T_source_in, p.P_source)
    # Chute independente dos deltas informados no modo DELTA_T.
    deltas = np.array([1.0, 1.0])
    for _ in range(100):
        caso = replace(p,
                       DT_w_cond=float(deltas[0]), DT_source=float(deltas[1]))
        _, T_cd = temperaturas_condensador(caso)
        _, T_ev = temperaturas_evaporador(caso)
        high = calcular_estagio_alta(caso, T_ev if T_cd_l is None else
                                    T_cd_l - p.DT_pinch_cascade, T_cd)
        Q_source = high["Q_ev"]
        if T_cd_l is not None:
            low = calcular_estagio_baixa(caso, T_ev, T_cd_l, high["Q_ev"])
            Q_source = low["Q_ev"]
        if Q_source <= 0 or high["Q_cond"] <= 0:
            raise ValueError("Cargas térmicas não positivas no modo VAZAO.")
        T_w = T_PH("Water", p.P_w_cond, h_w_in + high["Q_cond"] / m_dot_w_cond)
        T_s = T_PH(p.F_source, p.P_source, h_s_in - Q_source / m_dot_source)
        novos = np.array([T_w - p.T_w_cond_in, p.T_source_in - T_s])
        if not np.all(np.isfinite(novos)) or (novos[0] < -1e-7 or novos[1] <= 0):
            raise ValueError("Temperaturas de saída não físicas no modo VAZAO.")
        # A entalpia de saída vem de Q/m, inclusive na região bifásica.
        # Não reconstruir h por T,P: na saturação isso perderia o calor latente.
        erro_fonte = m_dot_source * (h_s_in - h_TP(p.F_source, p.T_source_in - deltas[1], p.P_source)) / Q_source - 1
        if np.max(np.abs(novos - deltas)) < 1e-4 and abs(erro_fonte) < 1e-4:
            return caso
        deltas = 0.5 * deltas + 0.5 * novos
    raise ValueError("Modo VAZAO não convergiu para as vazões e condições informadas.")


def ciclo_alta(p):
    p = resolver_entradas_externas(p)
    T_source_out, T_ev_h = temperaturas_evaporador(p)
    T_w_cond_out, T_cd_h = temperaturas_condensador(p)
    high = calcular_estagio_alta(p, T_ev_h, T_cd_h)

    agua = estado_agua_condensador(p, high, T_w_cond_out)
    T_w_cond_out = agua["T_w_cond_out"]
    m_dot_w = agua["m_dot_w_cond"]

    h_source_in = h_TP(p.F_source, p.T_source_in, p.P_source)
    h_source_out = h_TP(p.F_source, T_source_out, p.P_source)
    m_dot_source = high["Q_ev"] / (h_source_in - h_source_out)

    ciclo = dict(mode="ALTA", high=high, T_source_out=T_source_out, T_w_cond_out=T_w_cond_out, m_dot_source=m_dot_source,
                 m_dot_w_cond=m_dot_w, W_total=high["W"], Q_total=high["Q_total"], COP=high["Q_total"]/high["W"])
    ciclo.update(agua)
    ciclo["UA"] = dimensionar_trocadores(p, ciclo)
    return ciclo

# ============================================================
# CICLO CASCATA
# ============================================================

def ciclo_cascata(p, T_cd_l):
    if getattr(p, "optimize_injection", False) and not getattr(p, "_evaluating_injection", False):
        from hthp.configurations import has_injection, otimizar_injecao
        if any(has_injection(t) for t in (p.low_technology, p.high_technology)):
            return otimizar_injecao(p, T_cd_l)
    p = resolver_entradas_externas(p, T_cd_l)
    T_source_out, T_ev_l = temperaturas_evaporador(p)
    T_w_cond_out, T_cd_h = temperaturas_condensador(p)
    T_ev_h = T_cd_l - p.DT_pinch_cascade

    high = calcular_estagio_alta(p, T_ev_h, T_cd_h)

    low = calcular_estagio_baixa(p, T_ev_l, T_cd_l, high["Q_ev"])
    if not low["N_feasible"]: raise ValueError(f"Rotação do compressor de baixa fora da faixa: {low['N_rpm']:.0f} rpm")

    agua = estado_agua_condensador(p, high, T_w_cond_out)
    T_w_cond_out = agua["T_w_cond_out"]
    m_dot_w = agua["m_dot_w_cond"]

    h_source_in = h_TP(p.F_source, p.T_source_in, p.P_source)
    h_source_out = h_TP(p.F_source, T_source_out, p.P_source)
    m_dot_source = low["Q_ev"] / (h_source_in - h_source_out)

    W_total = high["W"] + low["W"]
    ciclo = dict(mode="CASCATA", high=high, low=low, T_cd_l=T_cd_l, T_ev_h=T_ev_h, T_ev_l=T_ev_l, T_cd_h=T_cd_h,
                 T_source_out=T_source_out, T_w_cond_out=T_w_cond_out, m_dot_source=m_dot_source, m_dot_w_cond=m_dot_w,
                 W_total=W_total, Q_total=high["Q_total"], COP=high["Q_total"]/W_total,
                 residual_cascade=high["Q_ev"]-low["Q_cond"])
    ciclo.update(agua)
    ciclo["UA"] = dimensionar_trocadores(p, ciclo)
    return ciclo

# ============================================================
# OTIMIZAÇÃO DA TEMPERATURA INTERMEDIÁRIA
# ============================================================

def otimizar_cascata(p, step=None):
    Tmax = T_cd_l_max(p)
    if p.T_cd_l_min >= Tmax: raise ValueError("Faixa de T_cd,l inválida para o refrigerante de baixa.")

    xatol = p.T_cd_l_step if step is None else step
    avaliados = []

    def objetivo(T_cd_l):
        try:
            ciclo = ciclo_cascata(p, float(T_cd_l))
            avaliados.append(ciclo)
            return -ciclo["COP"]
        except ValueError:
            return 1e6

    res = minimize_scalar(objetivo, bounds=(p.T_cd_l_min, Tmax), method="bounded",
                          options={"xatol": xatol})

    if not avaliados:
        raise ValueError("Nenhum ponto viável encontrado para a cascata.")

    melhor = max(avaliados, key=lambda x: x["COP"])
    return melhor, avaliados

# ============================================================
# GRÁFICOS — CICLO TERMODINÂMICO
# ============================================================

def montar_ciclo_grafico(c, stage):
    if stage == "high":
        P = [c["P_ev"], c["P_cd"], c["P_cd"], c["P_cd"], c["P_ev"]]
        H = [c["H1"], c["H2"], c["H3"], c["H4"], c["H5"]]
    else:
        P = [c["P_ev"], c["P_cd"], c["P_cd"], c["P_ev"]]
        H = [c["H1"], c["H2"], c["H3"], c["H4"]]
    return make_cycle(c["fluid"], P, H, stage=stage)

def plot_diagramas_termodinamicos(ciclo):
    ciclos = [montar_ciclo_grafico(ciclo["high"], "high")]
    if ciclo["mode"] == "CASCATA": ciclos.append(montar_ciclo_grafico(ciclo["low"], "low"))
    if PLOTAR_PH and PLOTAR_TS:
        fig, axes = plt.subplots(1, 2, figsize=(190 * MM, 88 * MM))
        fig.canvas.manager.set_window_title("Diagramas P–h e T–s")
        plot_cycles(ciclos, "Ph", ax=axes[0])
        plot_cycles(ciclos, "Ts", ax=axes[1])
        return fig, axes
    if PLOTAR_PH: return plot_ph(ciclos)
    if PLOTAR_TS: return plot_ts(ciclos)

# ============================================================
# PERFIS DE TEMPERATURA DOS TROCADORES
# ============================================================

def perfil_temperatura_entalpia(fluid, P_bar, H_ini, H_fim, n=N_PONTOS_PERFIL):
    H = np.linspace(H_ini, H_fim, n)
    return np.array([T_PH(fluid, P_bar, float(h)) for h in H])

def formatar_perfil_trocador(ax, x, T_hot, T_cold, label_hot, label_cold, titulo, pinch_definido):
    hot_line, = ax.plot(x, T_hot, marker="none", label=label_hot)
    cold_line, = ax.plot(x, T_cold, marker="none", label=label_cold)

    DT = T_hot - T_cold
    i_pinch = int(np.nanargmin(DT))

    ax.plot(x[i_pinch], T_hot[i_pinch], marker="o", linestyle="none",
            color=hot_line.get_color(), markersize=5.5, zorder=4, label="_nolegend_")
    ax.plot(x[i_pinch], T_cold[i_pinch], marker="s", linestyle="none",
            color=cold_line.get_color(), markersize=5.5, zorder=4, label="_nolegend_")
    ax.vlines(x[i_pinch], T_cold[i_pinch], T_hot[i_pinch], linewidth=1.2,
              linestyles="--", color="black")
    ax.text(0.03, 0.05, f"Pinch = {pinch_definido:.1f} K", transform=ax.transAxes, fontsize=9,
        bbox=dict(boxstyle="square,pad=0.25", facecolor="white", edgecolor="0.6", alpha=0.95))
    ax.set_title(titulo)
    ax.set_xlabel(r"Normalized heat transfer $q/Q$ [-]")
    ax.set_ylabel(r"Temperature [$^\circ$C]")
    ax.set_xlim(0.0, 1.0)
    ax.grid(True, which="major", linestyle="--", linewidth=0.6, color="black")
    add_minor_grid(ax)
    ax.legend(loc="best", ncols=2, fontsize=9)

def plot_perfis_trocadores(p, ciclo):
    if ciclo["mode"] not in ("ALTA", "CASCATA"):
        raise ValueError("Modo de ciclo inválido para os perfis.")
    cascata = ciclo["mode"] == "CASCATA"

    high = ciclo["high"]
    evap = ciclo["low"] if cascata else high
    x = np.linspace(0.0, 1.0, N_PONTOS_PERFIL)

    fig, axes = plt.subplots(2, 2, figsize=(190 * MM, 120 * MM))
    ax_cond, ax_casc = axes[0]
    ax_evap, ax_sc = axes[1]
    if not cascata:
        ax_casc.set_axis_off()

    # Condensador de alta: refrigerante 2 -> 3; água em contracorrente.
    T_ref_cond = perfil_temperatura_entalpia(high["fluid"], high["P_cd"], high["H2"], high["H3"])
    H_w_cond_in = ciclo["H_w_cond_in"]
    H_w_cond_out = ciclo["H_w_cond_out"]
    T_w_cond = perfil_temperatura_entalpia("Water", p.P_w_cond, H_w_cond_out, H_w_cond_in)
    formatar_perfil_trocador(ax_cond, x, T_ref_cond, T_w_cond, high["fluid"], "Water", "Condenser", p.DT_pinch_cond)

    if cascata:
        low = ciclo["low"]
        # Cascata: ciclo de baixa condensa; ciclo de alta evapora.
        T_low_casc = perfil_temperatura_entalpia(low["fluid"], low["P_cd"], low["H2"], low["H3"])
        T_high_casc = perfil_temperatura_entalpia(high["fluid"], high["P_ev"], high.get("H_evap_out", high["H1"]), high["H5"])
        formatar_perfil_trocador(ax_casc, x, T_low_casc, T_high_casc, low["fluid"], high["fluid"], "Cascade", p.DT_pinch_cascade)

    # Evaporador ligado à fonte: baixa na cascata, alta no ciclo simples.
    H_source_in = h_TP(p.F_source, p.T_source_in, p.P_source)
    H_source_out = h_TP(p.F_source, ciclo["T_source_out"], p.P_source)
    T_source = perfil_temperatura_entalpia(p.F_source, p.P_source, H_source_in, H_source_out)
    H_evap_in = evap["H4"] if cascata else evap["H5"]
    T_ref_evap = perfil_temperatura_entalpia(evap["fluid"], evap["P_ev"], evap.get("H_evap_out", evap["H1"]), H_evap_in)
    formatar_perfil_trocador(ax_evap, x, T_source, T_ref_evap, p.F_source, evap["fluid"], "Evaporator", p.DT_pinch_evap)

    # Subresfriador externo: refrigerante de alta 3 -> 4; água em contracorrente.
    T_ref_sc = perfil_temperatura_entalpia(high["fluid"], high["P_cd"], high["H3"], high["H4"])
    H_w_sc_in = h_TP("Water", p.T_w_sc_in, p.P_w_cond)
    H_w_sc_out = H_w_sc_in + high["Q_sc"]/p.m_dot_w_sc
    T_w_sc = perfil_temperatura_entalpia("Water", p.P_w_cond, H_w_sc_out, H_w_sc_in)
    formatar_perfil_trocador(ax_sc, x, T_ref_sc, T_w_sc, high["fluid"], "Water", "Subcooler", p.DT_pinch_sc)

    return fig, axes

# ============================================================
# HEATMAPS
# ============================================================

def progresso_heatmap(linha, total, inicio, ultimo_aviso):
    agora = perf_counter()
    if HEATMAP_MOSTRAR_PROGRESSO and (linha == total or agora - ultimo_aviso >= 5.0):
        decorrido = agora - inicio
        restante = decorrido * (total - linha) / linha
        print(f"Heatmap: {linha}/{total} linhas ({100*linha/total:.0f}%) | {decorrido:.1f} s | restante: {restante:.1f} s", flush=True)
        return agora
    return ultimo_aviso

def plot_heatmap_cop(T_source, T_w_in, COP, contour_step):
    X, Y = np.meshgrid(T_source, T_w_in)
    fig, ax = create_figure()
    finite = COP[np.isfinite(COP)]
    if finite.size == 0: raise ValueError("Nenhum ponto válido no heatmap de COP.")

    vmin = np.nanmin(finite)
    vmax = np.nanmax(finite)
    levels = np.linspace(vmin, vmax, 150)

    cf, cbar = heatmap(ax, X, Y, COP, cbar_label="COP [-]", levels=levels)

    ticks = np.linspace(vmin, vmax, 7)
    cbar.set_ticks(ticks)
    cbar.set_ticklabels([f"{x:.1f}" for x in ticks])

    cmin = np.ceil(vmin / contour_step) * contour_step
    cmax = np.floor(vmax / contour_step) * contour_step
    contour_levels = np.arange(cmin, cmax + 0.5 * contour_step, contour_step)

    if contour_levels.size:
        cs = ax.contour(X, Y, COP, levels=contour_levels, colors="black", linewidths=0.7)
        ax.clabel(cs, inline=True, fontsize=9, fmt="%.1f")

    ax.set_xlabel(r"Heat source inlet temperature [$^\circ$C]")
    ax.set_ylabel(r"Water inlet temperature [$^\circ$C]")
    ax.set_xlim(T_source.min(), T_source.max())
    ax.set_ylim(T_w_in.min(), T_w_in.max())
    ax.set_xticks(np.arange(T_source.min(), T_source.max() + 1, 5))
    ax.set_yticks(np.arange(T_w_in.min(), T_w_in.max() + 1, 5))

    return fig, ax

def calcular_mapa_cop(p, modo):
    if modo == "ALTA":
        T_source = np.arange(T_SOURCE_ALTA_MIN, T_SOURCE_ALTA_MAX + 0.5*T_SOURCE_ALTA_STEP, T_SOURCE_ALTA_STEP)
    else:
        T_source = np.arange(T_SOURCE_CASCATA_MIN, T_SOURCE_CASCATA_MAX + 0.5*T_SOURCE_CASCATA_STEP, T_SOURCE_CASCATA_STEP)
    T_w = np.arange(T_W_MAP_MIN, T_W_MAP_MAX + 0.5*T_W_MAP_STEP, T_W_MAP_STEP)
    COP = np.full((len(T_w), len(T_source)), np.nan)
    inicio = ultimo = perf_counter()

    for i, Tw in enumerate(T_w):
        for j, Ts in enumerate(T_source):
            campo_agua = "T_sat_w_cond" if p.MODO_AGUA_COND == "SATURADO" else "T_w_cond_in"
            p_case = replace(p, T_source_in=float(Ts), **{campo_agua: float(Tw)})
            try:
                if modo == "ALTA": ciclo = ciclo_alta(p_case)
                elif MODO_OTIMIZACAO == "SIM": ciclo, _ = otimizar_cascata(p_case, p.T_cd_l_step_map)
                else: ciclo = ciclo_cascata(p_case, T_CD_L_FIXA)
                COP[i, j] = ciclo["COP"]
            except ValueError: pass
        ultimo = progresso_heatmap(i+1, len(T_w), inicio, ultimo)
    return T_source, T_w, COP

def heatmap_cop(p):
    T_source, T_w, COP = calcular_mapa_cop(p, MODO_CICLO)
    step = CONTOUR_STEP_ALTA if MODO_CICLO == "ALTA" else CONTOUR_STEP_CASCATA
    fig, ax = plot_heatmap_cop(T_source, T_w, COP, step)
    print(f"COP no mapa: mínimo = {np.nanmin(COP):.3f} | máximo = {np.nanmax(COP):.3f}")
    return fig, ax, COP

def criar_params_par(p, F_h, F_l): return replace(p, F_h=F_h, F_l=F_l)

def heatmap_comparacao_refrigerantes(p):
    if MODO_CICLO != "CASCATA": raise ValueError("O heatmap de comparação foi definido para o ciclo CASCATA.")

    p_base = criar_params_par(p, PAR_BASE_H, PAR_BASE_L)
    p_novo = criar_params_par(p, PAR_NOVO_H, PAR_NOVO_L)

    T_source, T_w, COP_base = calcular_mapa_cop(p_base, "CASCATA")
    _, _, COP_novo = calcular_mapa_cop(p_novo, "CASCATA")

    delta = 100.0*(COP_novo-COP_base)/COP_base if COMPARACAO_RELATIVA else COP_novo-COP_base
    finite = delta[np.isfinite(delta)]
    if finite.size == 0: raise ValueError("Nenhum ponto comum válido entre os dois pares de refrigerantes.")

    dmin = np.nanmin(finite)
    dmax = np.nanmax(finite)

    X, Y = np.meshgrid(T_source, T_w)
    fig, ax = create_figure()

    levels = np.linspace(dmin, dmax, 300)
    label = r"$\Delta COP$ [%]" if COMPARACAO_RELATIVA else r"$\Delta COP$ [-]"

    cf, cbar = heatmap(ax, X, Y, delta, cbar_label=label, levels=levels)

    ticks = np.linspace(dmin, dmax, 7)
    cbar.set_ticks(ticks)
    cbar.set_ticklabels([f"{x:.0f}" for x in ticks])

    step = 1.0 if COMPARACAO_RELATIVA else 0.05
    cmin = np.ceil(dmin/step)*step
    cmax = np.floor(dmax/step)*step
    contour_levels = np.arange(cmin, cmax + 0.5*step, step)

    if contour_levels.size:
        cs = ax.contour(X, Y, delta, levels=contour_levels, colors="black", linewidths=0.7)
        ax.clabel(cs, inline=True, fontsize=9, fmt="%.0f")

    if dmin < 0 < dmax:
        ax.contour(X, Y, delta, levels=[0], colors="black", linewidths=1.5, linestyles="--")

    ax.set_xlabel(r"Heat source inlet temperature [$^\circ$C]")
    ax.set_ylabel(r"Water inlet temperature [$^\circ$C]")
    ax.set_xlim(T_source.min(), T_source.max())
    ax.set_ylim(T_w.min(), T_w.max())
    ax.set_xticks(np.arange(T_source.min(), T_source.max()+1, 5))
    ax.set_yticks(np.arange(T_w.min(), T_w.max()+1, 5))

    print("\nCOMPARAÇÃO DE REFRIGERANTES")
    print("-"*70)
    print(f"Base........................: {PAR_BASE_H} / {PAR_BASE_L}")
    print(f"Novo........................: {PAR_NOVO_H} / {PAR_NOVO_L}")
    print(f"Delta COP mínimo............: {dmin:.3f}{' %' if COMPARACAO_RELATIVA else ''}")
    print(f"Delta COP máximo............: {dmax:.3f}{' %' if COMPARACAO_RELATIVA else ''}")
    return fig, ax, delta, COP_base, COP_novo


def heatmap_rpm_baixa(p):
    T_source = np.arange(T_SOURCE_CASCATA_MIN, T_SOURCE_CASCATA_MAX + 0.5*T_SOURCE_CASCATA_STEP, T_SOURCE_CASCATA_STEP)
    T_w = np.arange(T_W_MAP_MIN, T_W_MAP_MAX + 0.5*T_W_MAP_STEP, T_W_MAP_STEP)
    RPM = np.full((len(T_w), len(T_source)), np.nan)

    for i, Tw in enumerate(T_w):
        for j, Ts in enumerate(T_source):
            campo_agua = "T_sat_w_cond" if p.MODO_AGUA_COND == "SATURADO" else "T_w_cond_in"
            p_case = replace(p, T_source_in=float(Ts), **{campo_agua: float(Tw)})
            try:
                ciclo = otimizar_cascata(p_case, p.T_cd_l_step_map)[0] if MODO_OTIMIZACAO == "SIM" else ciclo_cascata(p_case, T_CD_L_FIXA)
                RPM[i, j] = ciclo["low"]["N_rpm"]
            except ValueError:
                pass

    X, Y = np.meshgrid(T_source, T_w)
    fig, ax = create_figure()
    finite = RPM[np.isfinite(RPM)]
    levels = np.linspace(np.nanmin(finite), np.nanmax(finite), 150)
    _, cbar = heatmap(ax, X, Y, RPM, cbar_label="Low-stage compressor speed [rpm]", levels=levels)

    cs = ax.contour(X, Y, RPM, levels=np.arange(np.ceil(np.nanmin(finite)/500)*500, np.floor(np.nanmax(finite)/500)*500 + 500, 500), colors="black", linewidths=0.7)
    ax.clabel(cs, inline=True, fontsize=9, fmt="%.0f")
    ax.set_xlabel(r"Heat source inlet temperature [$^\circ$C]")
    ax.set_ylabel(r"Water inlet temperature [$^\circ$C]")

    return fig, ax, RPM

def plot_UA_vs_pinch(p):
    if p.modo_entrada_externa == "VAZAO":
        raise ValueError("Este gráfico compara deltas fixos; use modo_entrada_externa=DELTA_T.")
    ciclo_base, _ = otimizar_cascata(p)
    T_cd_l_ref = ciclo_base["T_cd_l"]
    pinch_range = np.linspace(10.0, 3.0, 10)

    trocadores = {
        "Condenser": ("DT_pinch_cond", "cond_h", "DT_w_cond", DASHES[0], MARKERS[0], COLORS[0]),
        "Cascade": ("DT_pinch_cascade", "cascade", None, DASHES[2], MARKERS[2], COLORS[2]),
        "Evaporator": ("DT_pinch_evap", "evap_l", "DT_source", DASHES[3], MARKERS[3], COLORS[3]),
        "Subcooler": ("DT_pinch_sc", "subcooler", None, DASHES[5], MARKERS[5], COLORS[5]),
    }

    fig, ax = create_figure()

    for label, (parametro_pinch, chave, parametro_delta, ls, mk, cor) in trocadores.items():
        deltas = (2.0, 5.0, 10.0) if parametro_delta is not None else (5.0,)
        curvas = {}

        for delta in deltas:
            UA = []
            for pinch in pinch_range:
                kwargs = {parametro_pinch: float(pinch)}
                if parametro_delta is not None: kwargs[parametro_delta] = float(delta)
                p_case = replace(p, **kwargs)

                try:
                    ciclo = ciclo_cascata(p_case, T_cd_l_ref)
                    UA.append(ciclo["UA"][chave]["UA"]/1000.0)
                except ValueError:
                    UA.append(np.nan)

            curvas[delta] = np.array(UA)

        if parametro_delta is not None:
            y_central = curvas[5.0]
            y_low = np.minimum(curvas[2.0], curvas[10.0])
            y_high = np.maximum(curvas[2.0], curvas[10.0])
            yerr = np.vstack((y_central-y_low, y_high-y_central))

            ax.fill_between(pinch_range, y_low, y_high, color=cor, alpha=0.14, zorder=1)
            ax.errorbar(pinch_range, y_central, yerr=yerr, fmt="none", ecolor=cor, elinewidth=1.3, capsize=4, capthick=1.2, zorder=2)
            ax.plot(pinch_range, y_central, linestyle=ls, marker=mk, linewidth=2.2, markersize=8, color=cor, markerfacecolor=cor, markeredgecolor="black", markeredgewidth=1.0, label=label, zorder=3)

        else:
            ax.plot(pinch_range, curvas[5.0], linestyle=ls, marker=mk, linewidth=2.2, markersize=8, color=cor, markerfacecolor=cor, markeredgecolor="black", markeredgewidth=1.0, label=label, zorder=3)

    ax.set_xlabel("Pinch point [K]")
    ax.set_ylabel("Required UA [kW/K]")
    ax.set_xlim(10.0, 3.0)
    ax.grid(True, which="major", linestyle="--", linewidth=0.6, color="black")
    add_minor_grid(ax)

    ax.legend(loc="upper left", frameon=True, fancybox=False)
    ax.text(0.265, 0.965, r"Upper: $\Delta T=2$ K | Lower: $\Delta T=10$ K", transform=ax.transAxes, fontsize=9, va="top")
    ax.text(0.265, 0.9, r"Central line: $\Delta T=5$ K", transform=ax.transAxes, fontsize=9)

    return fig, ax

def plot_COP_vs_pinch(p):
    if p.modo_entrada_externa == "VAZAO":
        raise ValueError("Este gráfico compara deltas fixos; use modo_entrada_externa=DELTA_T.")
    pinch_range = np.linspace(10.0, 3.0, 10)
    deltas = (10.0, 5.0, 2.0)
    estilos = {delta: (DASHES[index], MARKERS[index], COLORS[index])
               for index, delta in enumerate(deltas)}
    fig, ax = create_figure()

    for delta in deltas:
        COPs = []
        for pinch in pinch_range:
            p_case = replace(p, DT_w_cond=float(delta), DT_source=float(delta), DT_pinch_cond=float(pinch), DT_pinch_cascade=float(pinch), DT_pinch_evap=float(pinch), DT_pinch_sc=float(pinch))
    
            try:
                ciclo, _ = otimizar_cascata(p_case)
                COPs.append(ciclo["COP"])
            except ValueError:
                COPs.append(np.nan)

        ls, mk, color = estilos[delta]
        ax.plot(pinch_range, COPs, linestyle=ls, marker=mk, linewidth=2.2, markersize=7,
                color=color, markerfacecolor=color, markeredgecolor="black",
                label=rf"$\Delta T_{{cond}}=\Delta T_{{evap}}={delta:.0f}$ K")

    ax.set_xlabel("Pinch point [K]")
    ax.set_ylabel("COP [-]")
    ax.set_xlim(10.0, 3.0)
    ax.grid(True, which="major", linestyle="--", linewidth=0.6, color="black")
    add_minor_grid(ax)
    ax.legend(loc="best", frameon=True, fancybox=False)
    return fig, ax






# ============================================================
# IMPRESSÃO DOS RESULTADOS
# ============================================================

def print_estagio(nome, c, p):
    SUP = p.SUP_h if nome == "ALTA" else p.SUP_l
    SUB = p.SUB_h if nome == "ALTA" else p.SUB_l
    print(f"\nESTÁGIO DE {nome}")
    print("-"*70)
    print(f"Fluido......................: {c['fluid']}")
    print(f"T_ev / T_cd.................: {c['T_ev']:.2f} / {c['T_cd']:.2f} °C")
    print(f"SUP / SUB...................: {SUP:.2f} / {SUB:.2f} K")
    print(f"P_ev / P_cd.................: {c['P_ev']:.3f} / {c['P_cd']:.3f} bar")
    print(f"RP..........................: {c['RP']:.3f}")
    print(f"eta_is / eta_v..............: {c['eta_is']:.3f} / {c['eta_v']:.3f}")
    print(f"m_dot.......................: {c['m_dot']:.4f} kg/s")
    print(f"Rotação.....................: {c['N_rpm']:.0f} rpm")
    print(f"V_sw........................: {c['V_sw']*1e6:.1f} cm³/rev")
    print(f"W_comp......................: {c['W']/1000:.2f} kW")
    print(f"Q_cond......................: {c['Q_cond']/1000:.2f} kW")
    if nome == "ALTA": print(f"Q_subresfriador.............: {c['Q_sc']/1000:.2f} kW")
    print(f"Q_ev........................: {c['Q_ev']/1000:.2f} kW")

def print_trocadores(ciclo):
    print("\nDIMENSIONAMENTO DOS TROCADORES")
    print("-"*70)
    nomes = {"cond_h": "Condensador alta", "subcooler": "Subresfriador", "cascade": "Trocador cascata", "evap_l": "Evaporador baixa", "evap_h": "Evaporador alta"}
    for chave, item in ciclo["UA"].items():
        print(f"{nomes[chave]}")
        print(f"  Q..........................: {item['Q']/1000:.2f} kW")
        print(f"  Pinch......................: {item['pinch']:.2f} K")
        print(f"  DT1 / DT2..................: {item['DT1']:.2f} / {item['DT2']:.2f} K")
        print(f"  LMTD.......................: {item['DTlm']:.2f} K")
        print(f"  UA requerido...............: {item['UA']/1000:.3f} kW/K")

def print_resultados(p, ciclo):
    print("\n" + "="*70)
    print("HEAT PUMP — DIMENSIONAMENTO TERMODINÂMICO")
    print("="*70)
    print(f"Modo ciclo...................: {MODO_CICLO}")
    print(f"Dimensionamento..............: {MODO_DIMENSIONAMENTO}")
    print(f"Otimização...................: {MODO_OTIMIZACAO}")
    print(f"Entrada externa..............: {p.modo_entrada_externa}")
    print(f"Delta fonte / sumidouro......: {p.T_source_in - ciclo['T_source_out']:.3f} / {ciclo['T_w_cond_out'] - ciclo['T_w_cond_in']:.3f} K")
    print(f"Fluido da fonte..............: {p.F_source}")
    print(f"Fonte........................: {p.T_source_in:.2f} -> {ciclo['T_source_out']:.2f} °C")
    print(f"Entrada água condensador.....: {p.MODO_AGUA_COND}")
    print(f"T_sat água / pressão efetiva.: {ciclo['T_sat_w_cond']:.1f} °C / {p.P_w_cond:.1f} bar abs")
    print(f"Água condensador.............: {ciclo['T_w_cond_in']:.2f} -> {ciclo['T_w_cond_out']:.2f} °C")
    print(f"Água subresfriador entrada...: {p.T_w_sc_in:.2f} °C")
    print(f"Pinch cond / casc / evap / SC: {p.DT_pinch_cond:.2f} / {p.DT_pinch_cascade:.2f} / {p.DT_pinch_evap:.2f} / {p.DT_pinch_sc:.2f} K")

    print_estagio("ALTA", ciclo["high"], p)
    if ciclo["mode"] == "CASCATA": print_estagio("BAIXA", ciclo["low"], p)

    print("\nSISTEMA")
    print("-"*70)
    if ciclo["mode"] == "CASCATA": print(f"T_cd,l.......................: {ciclo['T_cd_l']:.2f} °C")
    print(f"Q útil.......................: {ciclo['Q_total']/1000:.2f} kW")
    print(f"W total......................: {ciclo['W_total']/1000:.2f} kW")
    print(f"COP..........................: {ciclo['COP']:.3f}")

    rho_w = ciclo["rho_w_cond_in"]
    rho_source = rho_TP(p.F_source, p.T_source_in, p.P_source)
    print(f"Água condensador.............: {ciclo['m_dot_w_cond']:.3f} kg/s | {ciclo['m_dot_w_cond']/rho_w*3600:.1f} m³/h")
    print(f"Fonte térmica................: {ciclo['m_dot_source']:.3f} kg/s | {ciclo['m_dot_source']/rho_source*3600:.0f} m³/h")

    print(f"Saturação água (P_cond)......: {ciclo['T_sat_w_cond']:.3f} °C")
    print(f"Estado na saída condensador..: {ciclo['fase_w_cond_out']}")
    if ciclo["titulo_w_cond_out"] is not None:
        print(f"Título de vapor na saída.....: {ciclo['titulo_w_cond_out']*100:.2f} % kg vapor/kg mistura")
    print_trocadores(ciclo)
    print("\nHipótese UA: trocadores em contracorrente e refrigerante isotérmico em T_sat no cálculo do LMTD.")

# ============================================================
# MAIN
# ============================================================

def main():
    p = Params()

    if MODO_CICLO == "ALTA": ciclo = ciclo_alta(p)
    elif MODO_CICLO == "CASCATA" and MODO_OTIMIZACAO == "SIM": ciclo, resultados = otimizar_cascata(p)
    elif MODO_CICLO == "CASCATA" and MODO_OTIMIZACAO == "NAO": ciclo = ciclo_cascata(p, T_CD_L_FIXA)
    else: raise ValueError("Verifique MODO_CICLO e MODO_OTIMIZACAO.")

    print_resultados(p, ciclo)

    if PLOTAR_PH or PLOTAR_TS: plot_diagramas_termodinamicos(ciclo)
    if PLOTAR_PERFIS_TROCADORES: plot_perfis_trocadores(p, ciclo)
    if CALCULAR_HEATMAP_COP: heatmap_cop(p)
    if CALCULAR_HEATMAP_COMPARACAO: heatmap_comparacao_refrigerantes(p)
    if PLOTAR_UA_PINCH: plot_UA_vs_pinch(p)
    if PLOTAR_COP_PINCH: plot_COP_vs_pinch(p)
    if CALCULAR_HEATMAP_RPM_BAIXA: heatmap_rpm_baixa(p)

    if PLOTAR_PH or PLOTAR_TS or PLOTAR_PERFIS_TROCADORES or CALCULAR_HEATMAP_COP or CALCULAR_HEATMAP_COMPARACAO or PLOTAR_UA_PINCH or PLOTAR_COP_PINCH or CALCULAR_HEATMAP_RPM_BAIXA:
        plt.show()


if __name__ == "__main__":
    import cProfile
    import pstats

    profiler = cProfile.Profile()
    profiler.enable()
    main()
    profiler.disable()

    pstats.Stats(profiler).sort_stats("cumtime").print_stats(30)
