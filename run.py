from hthp.cli import main

RODAR_COMPARACAO = True
PONTOS = 10
TEMP_AR_ENTRADA = 30.0  # °C
TEMP_AGUA_SATURADA = 120.0  # °C; pressão de saturação calculada automaticamente

if __name__ == "__main__":
    main([
        "--analise", "comparacao" if RODAR_COMPARACAO else "ponto",
        "--pontos", str(PONTOS),
        "--fonte", str(TEMP_AR_ENTRADA),
        "--agua-saturada", str(TEMP_AGUA_SATURADA),
    ])