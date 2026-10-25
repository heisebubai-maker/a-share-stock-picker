"""Local compatibility boundary. Only close prices are needed by these screeners.

This is not Quanti's trading/model runtime. No execution modules are loaded.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class BarData:
    close: float


class BaseScreener(ABC):
    @abstractmethod
    def init(self, config: dict) -> None: ...

    @abstractmethod
    def screen(self, code: str, bars: list[BarData]) -> float: ...
