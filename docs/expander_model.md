# Expansor no ciclo cascata

O expansor substitui a válvula no circuito escolhido:

`compressor → condensador → subcooler de água (se houver) → expansor → evaporador`

A saída fica na pressão de evaporação. Nesse circuito simples, a mesma vazão passa pelo compressor e pelo expansor; não há ORC, injeção nem um nível extra de pressão. O outro circuito pode manter a configuração convencional ou usar Flash tank, economizador ou ejetor + IHX. Os refrigerantes não se misturam: os dois circuitos estão ligados pelo balanço de calor da cascata. Para componentes combinados **no mesmo circuito**, veja [Combinações no mesmo circuito](intrastage_model.md).

O modelo usa R32 na baixa e R1233zd(E) na alta. Com o subcooler externo de água ligado, os 170 kW úteis são a soma do condensador e do subcooler. Como a água do subcooler está mais fria, isso não representa 170 kW inteiramente a 120 °C.

## Cálculo

O expansor é adiabático, sem variação relevante de energia cinética entre entrada e saída. O CoolProp dá a entalpia ideal de saída na pressão do evaporador e na entropia de entrada. Com entalpia em kJ/kg e vazão em kg/s, as potências ficam em kW:

```text
h_out,s = h(P_evap, s_in)
h_out = h_in - eta_is * (h_in - h_out,s)
W_exp = m * (h_in - h_out)
W_rec = eta_use * W_exp
W_loss = (1 - eta_use) * W_exp
W_net = W_comp,gross - W_rec
Q_evap = m * (h_evap,out - h_out)
```

`eta_is` é 0,50 e `eta_use` é 1,00 por padrão; são entradas do estudo, não dados de catálogo nem variáveis da otimização. Ambas aceitam valores finitos de 0 a 1. Com `eta_is=0`, o expansor reproduz a válvula. Já com `eta_use=0` e eficiência isentrópica positiva, a expansão ainda muda a entalpia: só o aproveitamento do trabalho é zero.

Balanços nas duas fronteiras:

```text
Circuito: Q_cond + Q_sc - Q_evap - W_comp,gross + W_exp = 0
Sistema:  Q_util + W_loss - Q_fonte - W_net,total = 0
COP = Q_util / (W_net,baixa + W_net,alta)
```

O trabalho recuperado ajuda o compressor do próprio circuito, antes do motor, e é descontado uma vez. A parcela não aproveitada é dissipada fora do sistema. A vazão, as cargas e as temperaturas de saída são recalculadas a cada tentativa; a carga do evaporador da alta determina a do condensador da baixa.

A busca limitada do SciPy maximiza o COP em função da temperatura de condensação da baixa. Nas combinações entre estágios, o outro circuito conserva seu cálculo: otimização da pressão de injeção no Flash tank e no economizador, ou fechamento do arraste e da pressão do separador no ejetor. O modelo integrado usa eficiência de motor 1 e não inclui bombas e ventiladores; no solver isolado, `W_el,net = W_net / eta_motor`.

## Rodar e ler os resultados

```bash
python run.py --baixa expansor --alta flash --analise ph
python run.py --baixa flash --alta expansor --analise curva --sem-subcooler
python run.py --baixa expansor --alta economizador --analise curva
python run.py --baixa economizador --alta expansor --analise ph
python run.py --baixa expansor --alta ejetor --analise curva
python run.py --baixa ejetor --alta expansor --analise ph --sem-subcooler
```

`turbina` é um alias de `expansor`. A comparação fica em `results/cascata/comparacao/por_componente/expansor/`; o P-h mostra os dois circuitos no ponto ótimo do caso. Nos CSVs, `W_shaft_kW` é o nome antigo de `W_net_shaft_kW`. Os demais campos são `W_compressor_shaft_kW` (entrada bruta), `W_expander_shaft_kW` (saída bruta), `W_recovered_kW` (aproveitada) e `W_recovery_loss_kW` (perda).

A expansão está em `src/hthp/components/expander.py`; o ciclo simples com expansor, em `src/hthp/cycles/expander_cycle.py`.

## Limites e referências

O modelo aceita estados bifásicos em equilíbrio, mas não dimensiona a máquina nem prevê geometria, rotação, estrangulamento, escorregamento, erosão, vazamentos, controle ou custo. Isso não demonstra que uma turbina de vapor seco possa operar nesse ponto, nem garante ganho de COP.

- [Li, An e Xi (2025)](https://doi.org/10.1016/j.energy.2025.139276): referência para recuperar trabalho da expansão bifásica na própria bomba de calor; não usamos a geometria Tesla, o ganho relatado nem seus parâmetros.
- [Kong et al. (2026)](https://doi.org/10.3390/en19163767): recuperação de trabalho analisada no nível da cascata; o ciclo transcrítico de CO₂ e seus resultados não são transferidos para este modelo.
- [Hassan et al. (2022)](https://doi.org/10.1016/j.egyr.2022.08.201): usa válvula na bomba de calor e expansor em um ORC separado; não valida a substituição da válvula aqui.
