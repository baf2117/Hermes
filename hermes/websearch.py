"""Búsqueda en internet con Tavily. Solo devuelve texto para redactar una respuesta."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any

TAVILY_URL = "https://api.tavily.com/search"
MAX_RESULTS = 3
MAX_CONTENT_CHARS = 600


UPCOMING_LINES = 12
_MONTHS = {
    name: number
    for number, name in enumerate(
        "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1
    )
}
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b")
_WRITTEN_DATE = re.compile(r"\b(\d{1,2}) de ([a-záéíóú]{3,10})\.?(?: de (20\d{2}))?")


class SearchError(Exception):
    pass


def dates_in_line(line: str, today: date) -> list[date]:
    found: list[date] = []

    def add(year: int, month: int, day: int) -> None:
        try:
            found.append(date(year, month, day))
        except ValueError:
            pass

    for day, month, year in _NUMERIC_DATE.findall(line):
        add(int(year), int(month), int(day))
    for day, month_name, year in _WRITTEN_DATE.findall(line.lower()):
        month = _MONTHS.get(month_name) or next(
            (number for name, number in _MONTHS.items() if name[:3] == month_name[:3]), None
        )
        if month is None:
            continue
        add(int(year) if year else today.year, month, int(day))
        if not year and found and (today - found[-1]).days > 180:
            found[-1] = found[-1].replace(year=today.year + 1)  # "3 de enero" dicho en diciembre.
    return found


def upcoming_lines(raw: str, today: date) -> str:
    """Deja solo las líneas con fechas de hoy en adelante; las páginas suelen empezar por lo ya pasado."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    kept = [line for line in lines if (dates := dates_in_line(line, today)) and max(dates) >= today]
    return "\n".join(kept[:UPCOMING_LINES])[:MAX_CONTENT_CHARS]


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str


class TavilySearch:
    def __init__(self, api_key: str, timeout: float = 20.0):
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, upcoming_from: date | None = None) -> list[SearchResult]:
        """Si `upcoming_from` tiene fecha, prefiere las líneas de páginas con fechas desde ese día."""
        request = urllib.request.Request(
            TAVILY_URL,
            data=json.dumps(
                {
                    "query": query,
                    "max_results": MAX_RESULTS,
                    "search_depth": "basic",
                    "include_raw_content": "text" if upcoming_from else False,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body: Any = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SearchError(f"Tavily respondió HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise SearchError(f"No se pudo consultar Tavily ({type(exc).__name__})") from None
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise SearchError("Tavily devolvió una respuesta inesperada")
        usable = [r for r in results[:MAX_RESULTS] if isinstance(r, dict)]
        if upcoming_from:
            upcoming = [
                SearchResult(str(r.get("title", ""))[:200], str(r.get("url", "")), lines)
                for r in usable
                if (lines := upcoming_lines(str(r.get("raw_content") or ""), upcoming_from))
            ]
            if upcoming:
                return upcoming
        return [
            SearchResult(str(r.get("title", ""))[:200], str(r.get("url", "")), str(r.get("content", ""))[:MAX_CONTENT_CHARS])
            for r in usable
        ]
