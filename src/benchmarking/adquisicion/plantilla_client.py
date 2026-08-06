import time
import requests

_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
_5XX = (500, 502, 503, 504)


class DescargaFallida(Exception):
    """No se pudo obtener la plantilla tras agotar los reintentos.

    NO significa que el estudio carezca de plantilla (eso es un 404, que devuelve None):
    significa que existe la duda. Se distingue para que la pérdida de datos sea contable
    y no se confunda con una ausencia legítima.
    """


class PlantillaRechazada(Exception):
    """El servidor rechaza la petición de forma determinista (4xx distinto de 404).

    Reintentarlo no cambia nada, así que tampoco es "dato perdido": contarlo junto a los
    fallos de red inflaría el marcador de pérdidas con estudios que nunca fueron
    recuperables. Se cuenta aparte.
    """


def descargar_plantilla(numero_proceso, id_version, base_url, session=None,
                        reintentos=3, espera=time.sleep):
    """Descarga la plantilla-modificada de un estudio.

    Devuelve los bytes del XLSX, o `None` si el estudio no tiene plantilla (404).
    Lanza `DescargaFallida` si tras `reintentos` intentos no se pudo saber.

    Se reintenta tanto ante 5xx como ante **fallos de conexión** (SSLError, timeouts,
    reset). Esto último es lo que rompía con concurrencia alta: la excepción escapaba
    del bucle sin reintentar y el estudio se descartaba en silencio.
    """
    ses = session or requests.Session()
    url = f"{base_url.rstrip('/')}/estudios/{numero_proceso}/version/{id_version}/plantilla-modificada"
    ultimo = None
    for intento in range(reintentos):
        try:
            resp = ses.get(url, headers=_HEADERS, timeout=60)
        except requests.exceptions.RequestException as exc:   # SSL, conexión, timeout
            ultimo = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code == 404:
                return None                                   # hecho, no fallo: no se reintenta
            if resp.status_code not in _5XX:
                if 400 <= resp.status_code < 500:
                    raise PlantillaRechazada(f"{url}: HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.content
            ultimo = f"HTTP {resp.status_code}"
        if intento < reintentos - 1:
            espera(2 * (intento + 1))
    raise DescargaFallida(f"{url}: agotados {reintentos} intentos ({ultimo})")
