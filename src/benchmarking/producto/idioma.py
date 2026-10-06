"""Capa de idioma (D-050): un titulo en ingles se resuelve por su traduccion al espanol.

`es_ingles` decide por las palabras: al menos la mitad son palabras de cargo en ingles (lista
`PALABRAS_EN`) y ninguna es un conector en espanol. `Traductor` usa opus-mt-en-es en local (CPU
basta) con el titulo dentro de una frase, que es como traduce bien:
`He works as a payroll analyst.` -> `Trabaja como analista de nominas.`

Sin `transformers` o sin los pesos, el traductor no se carga y el producto sigue sin la capa.
"""
import pathlib
import re
import unicodedata

PALABRAS_EN = frozenset("""
ACCOUNT ACCOUNTANT ACCOUNTING ACCOUNTS ADMIN ADMINISTRATIVE ADVISOR AGENT ANALYST ANALYTICS
ARCHITECT ASSISTANT ASSOCIATE ASSURANCE ATTENDANT AUDITOR BAKER BANKING BRAND BUSINESS BUYER
CARE CASHIER CHAIN CHANNEL CHIEF CLAIMS CLEANER CLERK CLIENT COACH COMMERCIAL COMPLIANCE
CONSULTANT CONTENT CONTROLLER COOK COORDINATOR COUNSEL COUNTRY CREDIT CUSTOMER DATA DELIVERY
DESIGNER DESK DEVELOPER DEVELOPMENT DIGITAL DIRECTOR DISTRICT DRIVER ENGINEER ENGINEERING
EXECUTIVE EXPERIENCE FIELD FINANCE FINANCIAL FLEET FRONT GENERAL GROWTH GUARD HEAD HELPER
HUMAN INSIGHTS INTERN INVENTORY KEY LEAD LEADER LEARNING LEGAL LOGISTICS MAINTENANCE MANAGEMENT
MANAGER MARKET MARKETING MECHANIC MERCHANDISER NURSE OFFICE OFFICER OPERATIONS OPERATOR
OWNER PARTNER PAYROLL PEOPLE PLANNER PLANNING PLANT PRESIDENT PROCUREMENT PRODUCT PROGRAM
PROJECT PURCHASING QUALITY RECEPTIONIST RECRUITER RECRUITMENT REGIONAL RELATIONS REPRESENTATIVE
RESEARCH RESOURCES RETAIL RISK SAFETY SALES SCIENTIST SECURITY SENIOR SERVICE SERVICES
SHIFT SOFTWARE SOLUTIONS SPECIALIST STAFF STORE STRATEGY SUCCESS SUPPLY SUPPORT SYSTEMS TALENT
TEAM TECHNICAL TECHNICIAN TEACHER TERRITORY TRADE TRAINEE TRAINER TRAINING TREASURY VICE
WAREHOUSE WORKER OF AND THE FOR TO WITH
""".split())
# conectores que solo aparecen en un titulo en espanol
CONECTORES_ES = frozenset("DE DEL LA LAS LOS EL Y EN PARA CON AL POR".split())
# palabras que en ingles NO hacen falta para decidir: comunes a los dos idiomas
COMUNES = frozenset("SENIOR JUNIOR SR JR GENERAL REGIONAL DIRECTOR SUPERVISOR STAFF DATA MARKETING".split())


def _palabras(t):
    return re.findall(r"[A-Z]+", str(t).upper())


def es_ingles(t):
    ws = [w for w in _palabras(t) if len(w) >= 2]
    if not ws or any(w in CONECTORES_ES for w in ws):
        return False
    en = [w for w in ws if w in PALABRAS_EN]
    propias = [w for w in en if w not in COMUNES]
    return bool(propias) and len(en) >= len(ws) / 2


def normalizar(t):
    """Como la base: mayusculas, sin tildes, sin el punto final."""
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.upper().strip().rstrip(".")).strip()


class Traductor:
    PLANTILLA = "He works as a {}."

    def __init__(self, ruta, lote=64):
        import torch
        from transformers import MarianMTModel, MarianTokenizer
        self.torch = torch
        self.tok = MarianTokenizer.from_pretrained(ruta)
        self.m = MarianMTModel.from_pretrained(ruta).eval()
        self.lote = lote
        self.cache = {}

    def _limpiar(self, s):
        s = re.sub(r"^\s*(trabaja|trabajo|el trabaja|ella trabaja)\s+(como|de)\s+(un |una )?", "", s, flags=re.I)
        return normalizar(s)

    def traducir(self, titulos):
        """dict titulo -> traduccion normalizada (MAYUSCULAS, sin tildes)."""
        falta = [t for t in dict.fromkeys(titulos) if t not in self.cache]
        for i in range(0, len(falta), self.lote):
            parte = falta[i:i + self.lote]
            frases = [self.PLANTILLA.format(str(t).lower().strip()) for t in parte]
            with self.torch.no_grad():
                x = self.tok(frases, return_tensors="pt", padding=True, truncation=True, max_length=64)
                o = self.m.generate(**x, num_beams=4, max_new_tokens=48)
            for t, s in zip(parte, self.tok.batch_decode(o, skip_special_tokens=True)):
                self.cache[t] = self._limpiar(s)
        return {t: self.cache[t] for t in titulos}


def cargar(ruta):
    """El traductor de `ruta`, o None si no se puede: el producto sigue sin la capa de idioma."""
    try:
        if not (pathlib.Path(ruta) / "config.json").exists():
            return None
        return Traductor(ruta)
    except Exception as e:                                   # noqa: BLE001 - se informa y se sigue
        print("[idioma] no se pudo cargar {}: {!r}".format(ruta, e), flush=True)
        return None
