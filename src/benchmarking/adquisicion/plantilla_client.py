import time
import requests

_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}

def descargar_plantilla(numero_proceso, id_version, base_url, session=None, reintentos=3):
    ses = session or requests.Session()
    url = f"{base_url.rstrip('/')}/estudios/{numero_proceso}/version/{id_version}/plantilla-modificada"
    for intento in range(reintentos):
        resp = ses.get(url, headers=_HEADERS, timeout=60)
        if resp.status_code in (500, 502, 503, 504):
            if intento < reintentos - 1:
                time.sleep(2 * (intento + 1))
            continue
        resp.raise_for_status()
        return resp.content
    return None
