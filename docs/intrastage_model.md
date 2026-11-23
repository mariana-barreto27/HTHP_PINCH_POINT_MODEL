# Combinações de componentes no mesmo circuito

São nove variantes em cinco famílias, aplicáveis à baixa, à alta ou aos dois circuitos: 27 casos além das 25 combinações entre estágios. Não há variante Flash tank + economizador. Mantêm-se os fluidos, fonte, carga, pinches, fechamento de vazões externas e correlação do compressor. Desligar o subcooler de água não retira o IHX do ejetor nem o economizador. Veja [Expansor no ciclo cascata](expander_model.md) para o balanço de recuperação e o que compõe os 170 kW.

- Expansor: eficiência isentrópica 0,50 e aproveitamento de eixo 1,00.
- Ejetor: eficiências de bocal, mistura e difusor de 0,50, com mistura a pressão constante. IHX: superaquecimento na sucção e aproximação mínima de 5 K.
- Economizador: efetividade de 0,90 e aproximação mínima de 5 K.

Nas equações, `M` é a vazão no condensador (kg/s), `y = m_inj/M` é a fração injetada e `mu = m_evap/m_motriz` é a razão de arraste, não a fração injetada. As entalpias estão em kJ/kg e as potências em kW. `P_inj` é a pressão entre compressões; `P_sep` é a do separador após o ejetor.

## Flash tank + expansor

Expansor **antes** do tanque (`P_cond → P_inj`), **depois** do tanque na linha de líquido (`P_inj → P_evap`), ou nos dois trechos. Onde não tem expansor, fica a válvula.

```text
y = (h_tanque,in - h_liq,sat(P_inj)) / (h_vap,sat(P_inj) - h_liq,sat(P_inj))
m_inj = y*M; m_evap = (1-y)*M
W_exp = M*w_antes + (1-y)*M*w_depois
```

Cada `w` é a queda de entalpia no expansor daquele ramo, ou zero se não houver expansor. A expansão antes do tanque muda a entalpia de entrada e a fração `y`. Sem mistura bifásica admissível, o caso é inviável.

## Economizador + expansor

O expansor pode ficar na linha **principal** após o economizador (`P_cond → P_evap`), na linha de **injeção** antes do economizador (`P_cond → P_inj`), ou nas duas linhas. O vapor de injeção sai saturado em `P_inj`.

```text
T_main,out = T_hot,in - epsilon * [T_hot,in - (T_sat(P_inj) + DT_min)]
(1-y)*(h_hot,in - h_hot,out) = y*(h_inj,out - h_inj,in)
y = delta_h_hot / (delta_h_hot + delta_h_inj)
W_exp = (1-y)*M*w_main + y*M*w_inj
```

O expansor de injeção muda `h_inj,in` e, portanto, `y`. O trabalho do expansor principal não é calor trocado pelo economizador.

## Ejetor + expansor

Só a válvula da linha de líquido do separador é substituída (`P_sep → P_evap`); o bocal do ejetor fica como está. A vazão do evaporador é `mu*M`; `W_exp = mu*M*(h_sep,liq - h_evap,in)` e `Q_evap = mu*M*(h_evap,out - h_evap,in)`. A queda de pressão aproveitada pelo ejetor não é recuperada outra vez como potência de eixo. O fechamento de `mu/P_sep` não usa o estado após a válvula líquida; o acoplamento e o ótimo da cascata são recalculados.

## Flash tank + ejetor / economizador + ejetor

Nas duas variantes, o vapor `y*M` vai à injeção intermediária e o líquido `(1-y)*M` passa pelo IHX até a entrada motriz do ejetor. Com **Flash tank**, o líquido sai do tanque em `P_inj` e `y` vem do balanço do tanque. Há dois separadores: o tanque de injeção e o separador após o ejetor. Com **economizador**, a corrente principal fica em `P_cond`, `y` vem do balanço do trocador e não há tanque de injeção.

A entrada secundária vem do evaporador. Após o ejetor, o separador envia vapor ao IHX e ao primeiro compressor; o líquido passa pela válvula e volta ao evaporador. O vapor de injeção se mistura à descarga do primeiro compressor antes do segundo.

```text
P_evap < P_sep < P_inj < P_cond
m_motriz = m_comp1 = (1-y)*M
m_evap = mu*(1-y)*M; m_comp2 = M
h_mix = (1-y)*h_comp1,out + y*h_inj
W_comp = (1-y)*M*(h_comp1,out - h_suc) + M*(h_desc - h_mix)
IHX: m_motriz*(h_hot,in - h_hot,out) = m_comp1*(h_suc - h_sep,vap)
```

### Fechamento do ejetor

```text
v_bocal = sqrt(2000*eta_bocal*(h_motriz - h_bocal,s))
v_mistura = v_bocal*sqrt(eta_mistura)/(1+mu)
h_ejetor,out = (h_motriz + mu*h_secundaria)/(1+mu)
h_mistura = h_ejetor,out - v_mistura^2/2000
h_difusor,s = h_mistura + eta_difusor*(h_ejetor,out - h_mistura)
P_ejetor,out = P(h_difusor,s, s_mistura)
x_sep = (h_ejetor,out - h_sep,liq)/(h_sep,vap - h_sep,liq)
```

O fator 2000 converte a energia cinética entre m/s e kJ/kg. O ejetor não gera potência de eixo. `scipy.optimize.least_squares` resolve `x_sep = 1/(1+mu)` e `P_ejetor,out = P_sep` para encontrar `mu` e `P_sep`. Isso fecha balanços, não maximiza COP. Os pinches do IHX e do economizador são conferidos no perfil nas variantes com injeção + ejetor; a compressão deve permanecer em vapor. O calor do IHX e do economizador é interno.

## Busca do ótimo e limites

`P_inj = P_evap*(P_cond/P_evap)^alpha`, com `0,05 ≤ alpha ≤ 0,95`. Cada tentativa recalcula os balanços e vazões. `scipy.optimize.minimize_scalar` busca a temperatura de acoplamento e as pressões de injeção, com apoio de uma malha curta. O P-h usa o ponto otimizado, não a malha das curvas; a busca não garante ótimo global. A definição de COP é a mesma da [nota do expansor](expander_model.md). Não foram adicionados bombas, ventiladores ou perdas de pressão.

As combinações de injeção com ejetor são propostas de simulação, não validação experimental. Referências da modelagem: [Mateu-Royo et al. (2020)](https://doi.org/10.1016/j.ijrefrig.2020.07.016), para o ejetor; [Barta et al. (2018), projeto Viper](https://docs.lib.purdue.edu/iracc/1894/), para recuperação na expansão e separação de fases. Nenhuma das duas valida diretamente as combinações deste modelo.
