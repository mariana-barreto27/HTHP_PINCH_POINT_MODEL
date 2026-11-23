# Modelo HTHP com pinch point

Bomba de calor em cascata com R32 na baixa e R1233zd(E) na alta. O caso padrão usa ar a 30 °C, água saturada a 120 °C e 170 kW de calor útil total. Com o subcooler externo da alta ligado, o calor dele entra nesses 170 kW; nem toda a carga é entregue a 120 °C.

## Como rodar

Na pasta do projeto, com o ambiente virtual ativado:

```bash
python -m pip install -e .
python run.py --help
```

Sem argumentos, o programa calcula o ponto ótimo da cascata convencional. Para escolher outro caso:

```bash
python run.py --componente economizador --estagio alta --analise curva
python run.py --baixa flash --alta expansor --analise ph
```

Use `--componente` com `--estagio baixa|alta|ambos`, ou escolha cada circuito com `--baixa` e `--alta`. Se informar só um circuito nesse segundo formato, o outro fica convencional. `--sem-subcooler` retira apenas o subcooler externo da alta, não o IHX do ejetor nem o trocador do economizador.

- `ponto`: busca a temperatura de condensação da baixa que maximiza o COP.
- `curva`: varia a temperatura de acoplamento e gera curvas de COP e descarga da alta.
- `ph`: desenha os dois circuitos juntos no ponto ótimo e salva a tabela de estados.
- `mapa`: mostra o COP em função da temperatura da fonte e da evaporação da alta.
- `fonte`: varia a temperatura da fonte, com a condensação da baixa fixa em `--temperatura-baixa`.

Use `--carga` (kW), `--fonte` (°C), `--pontos` e `--tolerancia` para ajustar a execução. Os demais parâmetros do caso-base ficam em `Params` no [modelo](src/hthp/model.py).

## Comparações

```bash
python run.py --analise comparacao
python run.py --analise comparacao --grupo expansor --comparar-subcooler
python run.py --analise comparacao --grupo mesmo-ciclo
python run.py --analise comparacao --grupo expansor --comparar-fonte --temperatura-baixa 45
```

São 52 arquiteturas: 25 combinações entre circuitos e 27 casos com componentes no mesmo circuito. Use `--grupo` para rodar só a família que interessa. Nos gráficos com as duas versões de subcooler, a linha contínua é com subcooler e a tracejada é sem; a referência é a cascata convencional sem subcooler. Nas tabelas de ótimos, o ganho compara o máximo de cada caso com o máximo da referência **com o mesmo ajuste de subcooler**. Nas curvas de ganho, a comparação é feita na mesma temperatura.

`python run.py all` roda as análises individuais, as comparações e as versões com e sem subcooler. Pode demorar. Se interromper com Ctrl+C, repita o comando sem `--recalcular` para aproveitar os pontos já salvos. `--replotar` só redesenha comparações com CSVs compatíveis.

## Onde ficam as coisas

- `results/cascata/`: pasta por caso e análise, com dados, figuras e `conditions.json`.
- `results/cascata/comparacao/todas_combinacoes/`: curvas gerais e tabela de ótimos das 52 arquiteturas.
- `results/cascata/comparacao/pontos_otimos/`: tabela das 104 versões, gerada na comparação completa com e sem subcooler.
- [model.py](src/hthp/model.py): condições, balanço da cascata e busca do ponto ótimo.
- [configurations.py](src/hthp/configurations.py) e [cycles/](src/hthp/cycles/): seleção das arquiteturas e cálculos de cada circuito.
- [cli.py](src/hthp/cli.py) e [analyses.py](src/hthp/analyses.py): comandos, análises e saídas.

## Notas do modelo

No caso-base, os pinches do condensador, da cascata e do evaporador são de 10 K. O superaquecimento na saída dos evaporadores continua em 5 K e o pinch do subcooler externo é de 20 K. A busca por COP usa `scipy.optimize.minimize_scalar` dentro dos limites do modelo. Para Flash tank e economizador, a pressão de injeção também é otimizada. Já a pressão do separador pós-ejetor é fechada por balanço.

O ejetor inclui um IHX interno. As eficiências do bocal, da mistura e do difusor são 0,50 cada. O IHX mantém 5 K de superaquecimento na sucção e uma aproximação mínima de 5 K; seu calor não conta como calor útil. A formulação segue o modelo de mistura a pressão constante de [Mateu-Royo et al. (2020)](https://doi.org/10.1016/j.ijrefrig.2020.07.016), sem usar os resultados do artigo como multiplicadores de COP.

O expansor recupera trabalho dentro do próprio circuito. Os padrões são `--eficiencia-expansor 0.50` e `--recuperacao-expansor 1.0`, ambos hipóteses de estudo. As equações e os limites estão nas notas de [expansão](docs/expander_model.md) e de [combinações no mesmo circuito](docs/intrastage_model.md).

As propriedades dos componentes usam a [interface de baixo nível do CoolProp](https://coolprop.org/coolprop/LowLevelAPI.html). Para rodar os testes:

```bash
python -m unittest discover -s tests -q
```
