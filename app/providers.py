"""Explicit data-source boundary. Demo data never represents real quotations."""
from datetime import date, timedelta
from random import Random
from typing import Protocol


class Provider(Protocol):
    name: str

    def bars(self) -> list[dict]: ...


class DemoProvider:
    name = "demo"

    def bars(self):
        rng = Random(20261017)
        end = date(2026, 10, 16)
        days = []
        while len(days) < 70:
            if end.weekday() < 5:
                days.append(end.isoformat())
            end -= timedelta(days=1)
        rows = []
        for i in range(12):
            price = 10 + i * 3
            for day in reversed(days):
                price *= 1 + rng.uniform(-0.035, 0.037)
                rows.append(dict(code=f"DEMO{i+1:02}", name=f"模拟样本{i+1:02}",
                                 day=day, close=round(price, 2),
                                 amount=round(rng.uniform(0.5, 6) * 1e8),
                                 is_st=int(i == 10), suspended=int(i == 11)))
        return rows


class BaoStockProvider:
    name = "baostock"

    def bars(self):
        # Never download at startup: cached research stays available offline.
        return []


def get_provider(name: str) -> Provider:
    if name == 'baostock':
        return BaoStockProvider()
    if name == 'demo':
        return DemoProvider()
    raise ValueError('未知数据源；仅支持baostock或demo，禁止静默回退')
