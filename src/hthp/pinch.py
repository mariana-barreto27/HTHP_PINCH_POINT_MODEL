"""Configuração comum dos pinch points do modelo integrado."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PinchPointConfig:
    """Diferenças mínimas de temperatura nos três níveis do sistema."""

    evaporator_K: float = 10.0
    condenser_K: float = 10.0
    cascade_K: float = 10.0

    def __post_init__(self) -> None:
        for name, value in (
            ("evaporator_K", self.evaporator_K),
            ("condenser_K", self.condenser_K),
            ("cascade_K", self.cascade_K),
        ):
            if value <= 0.0:
                raise ValueError(f"{name} deve ser positivo.")
