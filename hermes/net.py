"""Red: preferir IPv4.

En algunas redes de casa la computadora tiene dirección IPv6 pero esa ruta no llega a internet. Cada
conexión intenta primero IPv6, espera ~20 s a que venza y recién entonces usa IPv4. Con Telegram eso
retrasaba las respuestas a los botones hasta que Telegram las daba por vencidas.

Aquí solo se reordenan las direcciones: las IPv4 van primero y las IPv6 siguen como respaldo, así que
un servicio que solo tenga IPv6 sigue funcionando.
"""
from __future__ import annotations

import socket
from typing import Any

_original = socket.getaddrinfo


def _ipv4_first(*args: Any, **kwargs: Any) -> list[Any]:
    results = _original(*args, **kwargs)
    return sorted(results, key=lambda item: item[0] != socket.AF_INET)  # sorted es estable: respeta el orden dentro de cada grupo.


def prefer_ipv4() -> None:
    socket.getaddrinfo = _ipv4_first  # type: ignore[assignment]
