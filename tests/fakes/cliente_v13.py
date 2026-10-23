"""ADAPTADOR DE PRUEBA: habla el contrato NUEVO con la API y devuelve al test las
respuestas en la forma de la v1.3 (claves snake_case, 202 + consulta, `detail`).

Existe para que los ~70 tests de COMPORTAMIENTO de la v1.3 (validaciones, conteos,
avisos, la cascada del CIIU) sigan probando exactamente lo mismo contra la API
refactorizada, sin reescribir cada asercion. El contrato nuevo en si (sobre, camelCase,
codigos) se prueba aparte, directo, en `test_contrato.py`.

DEUDA REGISTRADA: migrar esos tests al contrato nuevo y retirar este adaptador
(`.claude/rules/technical-debt.md`).
"""

import base64
import re

from src.shared.utils.conversion import a_camel

_CLAVES_DATO = frozenset({"repartoEstado", "repartoConfianza"})


def a_snake(k: str) -> str:
    if not re.fullmatch(r"[a-z][A-Za-z0-9]*", k):
        return k  # columnas del cliente y claves raras: tal cual
    return re.sub(r"([A-Z])", r"_\1", k).lower()


def claves_a_snake(obj):
    if isinstance(obj, dict):
        return {a_snake(k): (v if k in _CLAVES_DATO else claves_a_snake(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [claves_a_snake(x) for x in obj]
    return obj


class RespuestaV13:
    def __init__(self, status_code: int, cuerpo=None, contenido: bytes | None = None):
        self.status_code = status_code
        self._cuerpo = cuerpo
        self.content = contenido if contenido is not None else b""
        self.text = repr(cuerpo)

    def json(self):
        return self._cuerpo


def _error(r):
    d = r.json()
    detalle = claves_a_snake(d["content"]) if d.get("content") else d.get("message")
    return RespuestaV13(r.status_code, {"detail": detalle})


class ClienteV13:
    def __init__(self, cliente):
        self.c = cliente
        self._informes: dict[str, dict] = {}
        self._excel: dict[str, bytes] = {}

    def post(self, url, files=None, data=None, **kw):
        assert url == "/informes", url
        form = {a_camel(k): v for k, v in (data or {}).items()}
        form["incluirExcel"] = "true"
        r = self.c.post(url, files=files, data=form, **kw)
        if r.status_code != 200:
            return _error(r)
        d = claves_a_snake(r.json()["content"])
        tid = d["id_carga"]
        self._excel[tid] = base64.b64decode(d.pop("excel_base64"))
        self._informes[tid] = {"id": tid, "estado": "listo", **d}
        return RespuestaV13(
            202,
            {
                "id": tid,
                "estado": "listo",
                "filas": d["filas"],
                "columna_cargo": d["columna_cargo"],
                "anio": d["meta"]["anio"],
                "empresa": d["empresa"],
                "mapeo_aplicado": d["meta"]["mapeo_aplicado"],
            },
        )

    def get(self, url, params=None, **kw):
        m = re.fullmatch(r"/informes/([^/]+)(/excel)?", url)
        if m:
            tid, excel = m.group(1), m.group(2)
            if tid not in self._informes:
                return RespuestaV13(404, {"detail": "no existe o ya caduco"})
            return RespuestaV13(200, None, self._excel[tid]) if excel else RespuestaV13(200, self._informes[tid])
        params = {a_camel(k): v for k, v in (params or {}).items()}
        r = self.c.get(url, params=params, **kw)
        if r.status_code != 200:
            return _error(r)
        return RespuestaV13(200, claves_a_snake(r.json()["content"]))
