# HTHP — modelo integrado de pinch point

Projeto independente do modelo integrado de pinch point. O projeto original `HTHP_NEW_TEC` permanece intacto; alterações feitas aqui não são sincronizadas com ele.

## Conteúdo

- `analysis/`: somente as análises do modelo integrado de pinch point.
- `src/hthp/`: ciclo integrado, componentes compartilhados e propriedades termodinâmicas.
- `results_pinch_point/`: resultados e gráficos existentes do modelo.
- `tests/`: teste do ciclo integrado.

Alguns ciclos auxiliares permanecem em `src/hthp/` porque a implementação integrada reutiliza partes da biblioteca modular. As análises antigas não foram copiadas.

## Instalação e execução

No terminal do VS Code, aberto nesta pasta, execute:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m analysis.run_all
```

No Windows, ative o ambiente com `.venv\\Scripts\\activate` em vez de `source .venv/bin/activate`.

Para gerar apenas as curvas de COP, ótimos, temperaturas de descarga e análise do limite de eficiência:

```bash
python -m analysis.integrated_curve_change_analysis
```

Os resultados são salvos em `results_pinch_point/`. As condições e faixas configuráveis estão em `analysis/settings.py`.

Para rodar os testes do ciclo integrado:

```bash
python -m unittest discover -s tests -v
```
