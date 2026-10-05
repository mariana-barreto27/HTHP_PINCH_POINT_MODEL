"""Condições-base e faixas usadas em todos os gráficos."""

# Ciclo-base
REFRIGERANT = "R245fa"
# A cascata usa fluidos diferentes nos dois níveis. Ambos os nomes são
# reconhecidos diretamente pelo CoolProp.
CASCADE_LOW_STAGE_REFRIGERANT = "R410A"
CASCADE_HIGH_STAGE_REFRIGERANT = "R245fa"
AMBIENT_BASE_C = 25.0
EVAPORATOR_APPROACH_K = 5.0
HEATING_CAPACITY_KW = 170.0
SUPERHEAT_K = 5.0
SUBCOOLING_K = 5.0
COMPRESSOR_ISENTROPIC_EFFICIENCY = 0.70
MOTOR_EFFICIENCY = 0.95

# Serviço térmico desejado. Nesta versão, o vapor é representado pela
# temperatura-alvo e pela carga entregue; o lado água/vapor ainda não possui
# balanço de massa próprio. A condensação do refrigerante fica acima da
# temperatura do vapor pela aproximação térmica especificada.
STEAM_TEMPERATURE_MIN_C = 90.0
STEAM_TEMPERATURE_MAX_C = 120.0
STEAM_TEMPERATURE_BASE_C = 120.0
STEAM_GENERATOR_APPROACH_K = 5.0
STEAM_FEEDWATER_TEMPERATURE_C = 25.0
STEAM_OUTLET_QUALITY = 1.0
CONDENSATION_BASE_C = STEAM_TEMPERATURE_BASE_C + STEAM_GENERATOR_APPROACH_K

# Varredura da temperatura ambiente
AMBIENT_MIN_C = 0.0
AMBIENT_MAX_C = 40.0
AMBIENT_POINTS = 41
# A cascata com mistura zeotrópica é mais cara de calcular. Vinte e um pontos
# mantêm as curvas suaves sem tornar o comando run_all excessivamente lento.
CASCADE_AMBIENT_POINTS = 21
# As comparações completas são mais custosas porque avaliam todas as
# arquiteturas da cascata em cada ponto.
CYCLE_COMPARISON_AMBIENT_POINTS = 21
CYCLE_COMPARISON_CONDENSATION_POINTS = 16

# Varredura equivalente ao fornecimento de vapor entre 90 e 120 °C.
CONDENSATION_MIN_C = STEAM_TEMPERATURE_MIN_C + STEAM_GENERATOR_APPROACH_K
CONDENSATION_MAX_C = STEAM_TEMPERATURE_MAX_C + STEAM_GENERATOR_APPROACH_K
CONDENSATION_POINTS = 31

# Resolução do mapa 2D. Use valores maiores para mapas mais suaves.
MAP_AMBIENT_POINTS = 21
MAP_CONDENSATION_POINTS = 23

# Resolução do mapa da cascata com temperatura ambiente no eixo x e
# temperatura-alvo do vapor no eixo y. A mesma malha é usada para todas as
# arquiteturas, permitindo comparação direta entre as cores.
CASCADE_MAP_AMBIENT_POINTS = 21
CASCADE_MAP_STEAM_TEMPERATURE_POINTS = 16

# Pressão intermediária do flash tank. As frações são aplicadas em escala
# logarítmica entre as pressões de evaporação e condensação.
FLASH_PRESSURE_POINTS = 61
FLASH_PRESSURE_MIN_LOG_FRACTION = 0.05
FLASH_PRESSURE_MAX_LOG_FRACTION = 0.95
FLASH_OPTIMIZATION_POINTS = 31

# Na cascata, cada estágio que possui flash tank tem sua pressão intermediária
# otimizada. A busca começa com uma malha em escala logarítmica e refina o
# intervalo ao redor do melhor ponto. Isso evita a combinação cartesiana de
# centenas de pressões nos dois circuitos.
CASCADE_FLASH_OPTIMIZATION_INITIAL_POINTS = 11
CASCADE_FLASH_OPTIMIZATION_REFINEMENT_POINTS = 7
CASCADE_FLASH_OPTIMIZATION_REFINEMENTS = 1

# Nos resultados principais, toda a vazão passa pelo IHX (fração = 1,0),
# portanto não existe ramo de bypass. A faixa abaixo é mantida apenas para
# estudos opcionais de sensibilidade do modelo genérico.
IHX_FRACTION_MIN = 0.0
IHX_FRACTION_MAX = 1.0
IHX_FRACTION_POINTS = 41
IHX_FRACTION_BASE = 1.00
IHX_EFFECTIVENESS_BASE = 0.70
IHX_EFFECTIVENESS_MIN = 0.0
IHX_EFFECTIVENESS_MAX = 1.0
IHX_EFFECTIVENESS_POINTS = 31
IHX_MINIMUM_APPROACH_K = 5.0

# Temperatura intermediária da cascata. O valor representa a evaporação do
# estágio alto; o estágio baixo condensa CASCADE_APPROACH_K acima.
CASCADE_HIGH_EVAPORATION_BASE_C = 35.0
CASCADE_HIGH_EVAPORATION_MIN_C = 20.0
CASCADE_HIGH_EVAPORATION_MAX_C = 60.0
CASCADE_TEMPERATURE_POINTS = 31
CASCADE_APPROACH_K = 5.0

# Otimização da temperatura de evaporação do estágio alto. A primeira malha
# cobre todo o intervalo de 20 a 60 °C; as passagens seguintes refinam a busca
# ao redor do melhor ponto válido de cada arquitetura.
CASCADE_TEMPERATURE_OPTIMIZATION_INITIAL_POINTS = 21
CASCADE_TEMPERATURE_OPTIMIZATION_REFINEMENT_POINTS = 11
CASCADE_TEMPERATURE_OPTIMIZATION_REFINEMENTS = 2

# As comparações usam a efetividade-base de 0,70. A faixa completa de 0 a 1 é
# usada somente na análise de sensibilidade, sem ser chamada de otimização.
CASCADE_IHX_EFFECTIVENESS_SWEEP_POINTS = 21

# Qualidade das figuras no padrão HpDAC. Cada gráfico também é salvo em PDF.
FIGURE_DPI = 600

# Modo integrado baseado no modelo de pinch point. A água quente foi definida
# como produto principal; o modelo de vapor permanece disponível no código,
# mas não é executado pelas análises padrão.
INTEGRATED_PINCH_SINK_MODES = ("hot_water",)
COMPRESSOR_MODEL_COMPARISON_SINK_MODE = "hot_water"
INTEGRATED_PINCH_EVAPORATOR_K = 10.0
INTEGRATED_PINCH_CONDENSER_K = 10.0
INTEGRATED_PINCH_CASCADE_K = 10.0
INTEGRATED_SOURCE_INLET_C = 20.0
INTEGRATED_SOURCE_OUTLET_C = 10.0
INTEGRATED_SOURCE_TEMPERATURE_DROP_K = (
    INTEGRATED_SOURCE_INLET_C - INTEGRATED_SOURCE_OUTLET_C
)
INTEGRATED_SOURCE_PRESSURE_BAR = 1.0
INTEGRATED_SOURCE_FLUID = "Air"
INTEGRATED_EXTERNAL_SUBCOOLER_EFFECTIVENESS = 0.90
# Economizador refrigerante-refrigerante: a corrente principal é subresfriada
# enquanto a corrente secundária evapora na pressão de injeção. Esta
# efetividade não é a do subcooler externo que aquece a água.
INTEGRATED_ECONOMIZER_EFFECTIVENESS = 0.90
INTEGRATED_ECONOMIZER_MINIMUM_APPROACH_K = 5.0
INTEGRATED_HIGH_EVAPORATION_MIN_C = 20.0
INTEGRATED_HIGH_EVAPORATION_MAX_C = 60.0
INTEGRATED_HIGH_EVAPORATION_STEP_K = 0.5
# A malha acima continua sendo usada para desenhar as curvas e localizar
# intervalos viáveis. O ótimo final é refinado por uma função contínua de
# maximização do COP dentro desses intervalos.
INTEGRATED_TEMPERATURE_OPTIMIZATION_TOLERANCE_K = 0.01
INTEGRATED_TEMPERATURE_OPTIMIZATION_MAX_ITERATIONS = 80
# Malha 2D do modelo integrado. A fonte conserva a queda de 10 K enquanto sua
# temperatura de entrada é variada. A faixa vertical é a evaporação do estágio
# alto, e não a evaporação do R410A no estágio baixo.
INTEGRATED_MAP_SOURCE_INLET_MIN_C = 0.0
INTEGRATED_MAP_SOURCE_INLET_MAX_C = 40.0
INTEGRATED_MAP_SOURCE_INLET_POINTS = 17
INTEGRATED_MAP_HIGH_EVAPORATION_POINTS = 17
INTEGRATED_HEAT_SOURCE_SWEEP_FIXED_HIGH_EVAPORATION_C = 35.0
# Ponto fixo usado para validar as quatro arquiteturas sem confundir validação
# termodinâmica com a otimização da temperatura intermediária.
INTEGRATED_VALIDATION_HIGH_STAGE_EVAPORATION_C = 35.0
INTEGRATED_FLASH_OPTIMIZATION_POINTS = 11
INTEGRATED_FLASH_REFINEMENT_ITERATIONS = 24
# Curva de eficiência isentrópica usada somente no modo integrado. Os
# resultados antigos mantêm eta_is=0,70.
INTEGRATED_USE_LINEAR_COMPRESSOR_EFFICIENCY = True
# Modelo linear: eta_is = eta_RP1 + slope*(RP - 1).
INTEGRATED_COMPRESSOR_EFFICIENCY_AT_UNIT_PRESSURE_RATIO = 0.80
INTEGRATED_COMPRESSOR_EFFICIENCY_SLOPE_PER_PRESSURE_RATIO = -0.05
# Coeficientes quadráticos preservados apenas para reproduzir versões antigas.
INTEGRATED_HIGH_COMPRESSOR_EFFICIENCY_COEFFICIENTS = (-0.29, 0.33, -0.027)
INTEGRATED_LOW_COMPRESSOR_EFFICIENCY_COEFFICIENTS = (0.45, 0.16, -0.027)
INTEGRATED_COMPRESSOR_EFFICIENCY_MIN = 0.40
INTEGRATED_COMPRESSOR_EFFICIENCY_MAX = 0.90
# A equação solicitada inclui o corte entre 0,40 e 0,90. O CSV registra quando
# esse corte é acionado para deixar a hipótese visível.
INTEGRATED_REJECT_COMPRESSOR_EFFICIENCY_LIMITS = False
INTEGRATED_HIGH_COMPRESSOR_FIXED_SPEED_HZ = 60.0
INTEGRATED_HIGH_COMPRESSOR_CLEARANCE = 0.02
INTEGRATED_LOW_COMPRESSOR_DISPLACEMENT_M3_REV = 0.0005
INTEGRATED_LOW_COMPRESSOR_MINIMUM_SPEED_HZ = 10.0
INTEGRATED_LOW_COMPRESSOR_MAXIMUM_SPEED_HZ = 100.0
INTEGRATED_LOW_COMPRESSOR_CLEARANCE = 0.02
INTEGRATED_ENFORCE_COMPRESSOR_SPEED_LIMITS = True

# Consumidor de vapor: a mesma água é pré-aquecida no subresfriador externo
# antes de receber o restante da carga no condensador principal.
INTEGRATED_STEAM_TARGET_C = 120.0
INTEGRATED_STEAM_FEEDWATER_C = 25.0
INTEGRATED_STEAM_QUALITY = 1.0

# Consumidor de água quente do arquivo de referência: a água de reposição é
# aquecida no subresfriador, misturada ao retorno de 110 °C antes do condensador
# e a corrente combinada deixa o condensador a 115 °C.
INTEGRATED_WATER_MAIN_INLET_C = 110.0
INTEGRATED_WATER_MAIN_OUTLET_C = 115.0
INTEGRATED_WATER_PRESSURE_BAR = 5.0
INTEGRATED_WATER_MAKEUP_INLET_C = 25.0
INTEGRATED_WATER_MAKEUP_MASS_FLOW_KG_H = 190.0