"""Entrena el cross-encoder B de D-036, lo elige y lo calibra con `calibra`. Nunca ve `prueba`.

Parte de `mDeBERTa-v3-base-xnli` (el NLI congelado de `13c` y `19`) y lo ajusta con la
plata de Gemini. Todo lo que decide este guion esta registrado ANTES de correr en D-036,
enmiendas 1 a 3. Corre en el servidor con GPU; aqui se prueba con `--rapido`.

QUE LEE, Y QUE SE NIEGA A LEER
==============================================================================
Solo `salidas/21_paquete/` (`plata.csv`, `calibra.csv`, `manifiesto.json`). Se detiene si
el manifiesto no dice `prueba_en_el_paquete: 0`. No tiene ninguna opcion para abrir
`13e_*` ni `20_*`: la prueba final (H1) se corre aparte, con el modelo ya congelado.

ANTES DE ENTRENAR: EL JUEZ ESTA BIEN MONTADO
==============================================================================
1. El modelo tiene que ser la revision fijada, y `model.safetensors` tiene que dar el
   hash esperado. Si no, se detiene.
2. Sin entrenar, en fp32, sobre `calibra` y con la plantilla fija, tiene que dar el AUC
   0,7285 de `19` (media de las dos direcciones; 194 pares tras la Enmienda 5), con
   tolerancia 0,005. Si no, algo cambio
   —plantilla, tokenizador o modelo— y se detiene. Es la leccion de D-034.

LAS VARIANTES
==============================================================================
    paso 1 · simetrico     un pase por par, orden al azar          P(mismo) = P(A=>B)
                           (al evaluar, media de los dos ordenes)
    paso 2 · direccional   dos pases                               P(mismo) = P(A=>B)·P(B=>A)
    paso 3 · completo      direccional + cabeza de motivo (0,3) + peso w en los pares
                           `dificil` (escalon o seniority distintos)
                           grilla: w en {1, 2, 3} x aumento {sin, con} = 6 configuraciones

P(A=>B) es la probabilidad de `entailment` que el NLI ya trae: se arranca de 0,7285, no de
cero. Pasos 1 y 2: una semilla, sin aumento (son para la ablacion). Paso 3: tres semillas
por configuracion (Enmienda 3).

COMO ELIGE (Enmienda 1 y 3)
==============================================================================
- EPOCA: la de mayor AUC en `calibra` (parada temprana en `calibra`, no en la plata).
- SEMILLA: por configuracion, AUC medio de las tres; se guarda la semilla MAS CERCANA A
  LA MEDIA, no la mejor, para no quedarse con un golpe de suerte.
- CONFIGURACION: la de mayor AUC medio. Si no es la mas simple (w = 1, sin aumento), solo
  gana si le gana a la simple con bootstrap pareado estratificado y un IC95 que excluya el
  cero. Si no, queda la simple.
- La plata `valida` (1.500 pares, etiqueta de Gemini o humana) se reporta al lado.

CALIBRACION: temperatura sobre el log-odds de P(mismo), ajustada en `calibra`.

REPRODUCIBILIDAD
==============================================================================
Semillas fijas, algoritmos deterministas de PyTorch, dependencias en
`requirements-cross.txt`. Cada corrida guarda su ficha: commit de git, versiones, GPU,
hashes del modelo y de los datos. En GPU el entrenamiento no es identico bit a bit entre
maquinas (sumas en otro orden, bf16); lo que es exacto es la evaluacion del modelo
guardado, y H1 se corre sobre ese modelo.

REANUDABLE
==============================================================================
Cada corrida (paso 1, paso 2 y las 18 de la grilla) se guarda en `estado/` al terminar. Si
el proceso se corta, se vuelve a lanzar el MISMO comando y las corridas hechas se leen del
disco: se pierde como mucho la corrida en curso. Solo se retoma si la huella coincide
(commit de git y cambios sin commitear, paquete, modelo, hiperparametros y versiones); si
no, se detiene en vez de mezclar corridas distintas. `--desde-cero` borra el estado.
Los pesos de cada semilla de la grilla se guardan hasta elegir el representante de su
configuracion; los demas se borran. Al terminar se borran todos los de `estado/`: los
que importan ya estan en `elegido/` y `corridas/`.

USO
    python 22_entrenar_cross.py --modelo modelos/mdeberta-xnli              (servidor)
    python 22_entrenar_cross.py --modelo <ruta> --rapido --dispositivo cpu  (prueba)
    (el mismo comando otra vez retoma; --desde-cero empieza de nuevo)

SALIDA: salidas/22_modelos/ (en .gitignore: pesos de ~1 GB por modelo)
    elegido/            el modelo de H1: pesos, tokenizador, cabeza de motivo, info.json
    corridas/<nombre>/  el representante de cada configuracion y de los pasos 1 y 2
    resultados.json     todo lo medido, y la ficha de reproducibilidad
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import random
import re
import shutil
import subprocess
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")
AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
PAQUETE = AQUI / "salidas" / "21_paquete"
SALIDA = AQUI / "salidas" / "22_modelos"

MODELO_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
REVISION = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
SHA_SAFETENSORS = "7c8e29f1115986d032e92b0fbaa0bdef1062a46f658b08705f237c05014a8541"
PLANTILLA = "El puesto de trabajo es {}."
AUC_BASE = 0.7285                # `19`, NLI congelado, media de las dos direcciones.
                                 # Era 0,748 con la v3 y 200 pares; Enmienda 5 de D-036
TOL_BASE = 0.005

MOTIVOS = ["ninguno", "p1", "p2", "p3", "p4", "p5"]
PESOS_W = (1, 2, 3)
AUMENTOS = (False, True)
SEMILLAS = (20260929, 20260930, 20261001)
LR = 2e-5
LR_CABEZA = 1e-4                 # la cabeza de motivo nace al azar: aprende mas rapido
BATCH = 32
EPOCAS = 4
CALENTAMIENTO = 0.10
DECAIMIENTO = 0.01
MAXLEN = 64
PESO_MOTIVO = 0.3
P_ERRATA = 0.30
B_BOOT = 2000

SENIORITY = {"SR", "SR.", "JR", "JR.", "SENIOR", "JUNIOR", "I", "II", "III", "IV", "V"}
PREPOS = {"DE", "DEL", "EN"}
ARTIC = {"LA", "LAS", "LOS", "EL"}


# ---------------------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------------------
def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def frase(titulo):
    return PLANTILLA.format(str(titulo).title())


def fijar_semilla(s):
    import torch
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    torch.cuda.manual_seed_all(s)


def auc(y, s):
    return float(roc_auc_score(y, s))


def boot_diferencia(y, s1, s2, rng, b=B_BOOT):
    """IC95 de AUC(s1) - AUC(s2), bootstrap pareado estratificado por clase."""
    i1, i0 = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    d = np.empty(b)
    for k in range(b):
        ix = np.concatenate([rng.choice(i1, len(i1)), rng.choice(i0, len(i0))])
        d[k] = roc_auc_score(y[ix], s1[ix]) - roc_auc_score(y[ix], s2[ix])
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def ficha(args, dispositivo):
    import sklearn
    import torch
    import transformers

    def git(*c):
        try:
            return subprocess.run(["git", *c], cwd=RAIZ, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except Exception:
            return None
    return {
        "fecha": dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": git("rev-parse", "HEAD"),
        "git_sin_commitear": bool(git("status", "--porcelain")),
        "python": platform.python_version(),
        "plataforma": platform.platform(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if dispositivo == "cuda" else None,
        "transformers": transformers.__version__,
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "modelo_id": MODELO_ID,
        "modelo_revision": REVISION,
        "modelo_sha256": SHA_SAFETENSORS,
        "argumentos": {k: str(v) for k, v in vars(args).items()},
    }


# ---------------------------------------------------------------------------------------
# datos
# ---------------------------------------------------------------------------------------
def cargar_paquete(ruta):
    man = json.loads((ruta / "manifiesto.json").read_text(encoding="utf-8"))
    if man.get("prueba_en_el_paquete") != 0:
        raise SystemExit("ALTO: el manifiesto no certifica que el paquete no trae `prueba`.")
    plata = pd.read_csv(ruta / "plata.csv", dtype={"motivo": str}, keep_default_na=False)
    calibra = pd.read_csv(ruta / "calibra.csv", keep_default_na=False)
    for col in ("comun", "raro", "particion", "etiqueta", "dificil", "motivo"):
        if col not in plata:
            raise SystemExit("plata.csv sin la columna {}".format(col))
    plata["dificil"] = plata["dificil"].astype(str).str.lower().eq("true")
    plata["etiqueta"] = plata["etiqueta"].astype(float)
    calibra["y"] = (calibra["mismo"] == "si").astype(int)
    hashes = {f: sha256(ruta / f) for f in ("plata.csv", "calibra.csv", "manifiesto.json")}
    return plata, calibra, man, hashes


def errata(titulo, rng):
    """Una errata real (D-025, `10`): letra cambiada, borrada o transpuesta, en una palabra
    de 5 letras o mas. Nunca la primera letra."""
    pal = titulo.split()
    cand = [i for i, w in enumerate(pal) if len(w) >= 5 and w.isalpha()]
    if not cand:
        return None
    i = cand[rng.integers(len(cand))]
    w = pal[i]
    j = int(rng.integers(1, len(w) - 1))
    op = rng.integers(3)
    if op == 0:
        letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        w = w[:j] + letras[rng.integers(26)] + w[j + 1:]
    elif op == 1:
        w = w[:j] + w[j + 1:]
    else:
        w = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    pal[i] = w
    nuevo = " ".join(pal)
    return nuevo if nuevo != titulo else None


def permutar(titulo):
    """Permutacion controlada (Enmienda 1): mover la marca de seniority, o intercambiar los
    segmentos unidos por `Y`. La palabra que nombra el puesto (la primera) no se mueve."""
    tok = titulo.split()
    if len(tok) < 3:
        return None
    if tok[-1] in SENIORITY:
        return " ".join([tok[0], tok[-1]] + tok[1:-1])
    if tok[1] in SENIORITY:
        return " ".join([tok[0]] + tok[2:] + [tok[1]])
    k = 1
    while k < len(tok) and tok[k] in PREPOS:
        k += 1
    if k < len(tok) and tok[k] in ARTIC:
        return None                 # `JEFE DE LA PLANTA Y ...`: permutar rompe la frase
    resto = " ".join(tok[k:])
    if " Y " in " {} ".format(resto) and resto.count(" Y ") == 1:
        a, b = resto.split(" Y ")
        if a and b and a != b:
            return " ".join(tok[:k] + [b, "Y", a])
    return None


def aumentar(t, rng):
    extra = []
    for _, f in t.iterrows():
        if rng.random() < P_ERRATA:
            lado = "comun" if rng.random() < 0.5 else "raro"
            e = errata(f[lado], rng)
            if e:
                g = f.copy()
                g[lado] = e
                extra.append(g)
        for lado in ("comun", "raro"):
            p = permutar(f[lado])
            if p:
                g = f.copy()
                g[lado] = p
                extra.append(g)
                break
    return pd.concat([t, pd.DataFrame(extra)], ignore_index=True) if extra else t


# ---------------------------------------------------------------------------------------
# modelo
# ---------------------------------------------------------------------------------------
def verificar_modelo(ruta):
    st = ruta / "model.safetensors"
    if not st.exists():
        raise SystemExit("no hay {}".format(st))
    h = sha256(st.resolve())
    if h != SHA_SAFETENSORS:
        raise SystemExit("ALTO: model.safetensors no es la revision fijada ({}).\n"
                         "  esperado {}\n  obtenido {}".format(REVISION, SHA_SAFETENSORS, h))


def construir(ruta, con_motivo, dispositivo):
    import torch
    from transformers import AutoModelForSequenceClassification

    class Juez(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.base = AutoModelForSequenceClassification.from_pretrained(
                ruta, dtype=torch.float32)
            etq = [self.base.config.id2label[i].lower()
                   for i in range(self.base.config.num_labels)]
            self.i_ent = next(k for k, e in enumerate(etq) if "entail" in e)
            self.motivo = (torch.nn.Linear(self.base.config.hidden_size, len(MOTIVOS))
                           if con_motivo else None)

        def forward(self, **x):
            out = self.base(**x, output_hidden_states=self.motivo is not None)
            p = torch.softmax(out.logits.float(), -1)[:, self.i_ent]
            h = out.hidden_states[-1][:, 0].float() if self.motivo is not None else None
            return p, h
    return Juez().to(dispositivo)


def tokens(tok, a, b, dispositivo):
    return tok([frase(x) for x in a], [frase(x) for x in b], padding=True,
               truncation=True, max_length=MAXLEN, return_tensors="pt").to(dispositivo)


def puntuar(juez, tok, a, b, dispositivo, autocast, lote=128):
    """P(a=>b) y P(b=>a) para cada par."""
    import torch
    juez.eval()
    ab, ba = [], []
    with torch.no_grad(), autocast():
        for i in range(0, len(a), lote):
            x, y = list(a[i:i + lote]), list(b[i:i + lote])
            ab.append(juez(**tokens(tok, x, y, dispositivo))[0].float().cpu().numpy())
            ba.append(juez(**tokens(tok, y, x, dispositivo))[0].float().cpu().numpy())
    return np.concatenate(ab), np.concatenate(ba)


def puntaje(modo, ab, ba):
    return (ab + ba) / 2 if modo == "simetrico" else ab * ba


# ---------------------------------------------------------------------------------------
# una corrida
# ---------------------------------------------------------------------------------------
def entrenar(nombre, modo, w, con_aumento, con_motivo, semilla, datos, ctx):
    import torch
    from transformers import get_linear_schedule_with_warmup

    fijar_semilla(semilla)
    rng = np.random.default_rng(semilla)
    dev, tok, autocast = ctx["dispositivo"], ctx["tok"], ctx["autocast"]
    plata, cal = datos["plata"], datos["calibra"]

    tr = plata[plata["particion"] == "entrena"].reset_index(drop=True)
    va = plata[plata["particion"] == "valida"].reset_index(drop=True)
    if ctx["rapido"]:
        tr = tr.sample(min(len(tr), 200), random_state=semilla).reset_index(drop=True)
        va = va.sample(min(len(va), 100), random_state=semilla).reset_index(drop=True)
    if con_aumento:
        tr = aumentar(tr, rng)
    epocas = 1 if ctx["rapido"] else EPOCAS

    juez = construir(ctx["modelo"], con_motivo, dev)
    grupos = [{"params": juez.base.parameters(), "lr": LR}]
    if juez.motivo is not None:
        grupos.append({"params": juez.motivo.parameters(), "lr": LR_CABEZA})
    opt = torch.optim.AdamW(grupos, weight_decay=DECAIMIENTO)
    pasos = epocas * int(np.ceil(len(tr) / BATCH))
    sched = get_linear_schedule_with_warmup(opt, int(CALENTAMIENTO * pasos), pasos)
    mot_ix = {m: i for i, m in enumerate(MOTIVOS)}

    historia, mejor = [], None
    t0 = time.time()
    for ep in range(1, epocas + 1):
        juez.train()
        orden = rng.permutation(len(tr))
        perdidas = []
        for i in range(0, len(orden), BATCH):
            f = tr.iloc[orden[i:i + BATCH]]
            y = torch.tensor(f["etiqueta"].to_numpy(), dtype=torch.float32, device=dev)
            peso = torch.tensor(np.where(f["dificil"].to_numpy(), w, 1.0),
                                dtype=torch.float32, device=dev)
            a, b = f["comun"].tolist(), f["raro"].tolist()
            with autocast():
                if modo == "simetrico":
                    gira = rng.random(len(a)) < 0.5
                    x = [bb if g else aa for aa, bb, g in zip(a, b, gira)]
                    z = [aa if g else bb for aa, bb, g in zip(a, b, gira)]
                    p, _ = juez(**tokens(tok, x, z, dev))
                    hm = None
                else:
                    p2, h2 = juez(**tokens(tok, a + b, b + a, dev))
                    n = len(a)
                    p = p2[:n] * p2[n:]
                    hm = (h2[:n] + h2[n:]) / 2 if h2 is not None else None
            p = p.float().clamp(1e-6, 1 - 1e-6)
            bce = -(y * torch.log(p) + (1 - y) * torch.log(1 - p))
            perdida = (peso * bce).sum() / peso.sum()
            if hm is not None:
                obj = torch.tensor([mot_ix.get(m, -100) for m in f["motivo"]],
                                   device=dev)
                if (obj >= 0).any():
                    ce = torch.nn.functional.cross_entropy(juez.motivo(hm), obj,
                                                           ignore_index=-100)
                    perdida = perdida + PESO_MOTIVO * ce
            opt.zero_grad(set_to_none=True)
            perdida.backward()
            torch.nn.utils.clip_grad_norm_(juez.parameters(), 1.0)
            opt.step()
            sched.step()
            perdidas.append(float(perdida))

        cab, cba = puntuar(juez, tok, cal["comun"].tolist(), cal["raro"].tolist(), dev,
                           autocast)
        s_cal = puntaje(modo, cab, cba)
        vab, vba = puntuar(juez, tok, va["comun"].tolist(), va["raro"].tolist(), dev,
                           autocast)
        vy = (va["etiqueta"] >= 0.5).astype(int).to_numpy()
        r = {"epoca": ep, "perdida": float(np.mean(perdidas)),
             "auc_calibra": auc(cal["y"].to_numpy(), s_cal),
             "auc_valida": auc(vy, puntaje(modo, vab, vba)),
             "segundos": round(time.time() - t0, 1)}
        historia.append(r)
        print("    {:<28} ep {}  perdida {:.4f}  AUC calibra {:.4f}  valida {:.4f}  {:.0f}s"
              .format(nombre, ep, r["perdida"], r["auc_calibra"], r["auc_valida"],
                      r["segundos"]), flush=True)
        if mejor is None or r["auc_calibra"] > mejor["auc_calibra"]:
            mejor = dict(r, estado=copy.deepcopy({k: v.detach().cpu() for k, v
                                                  in juez.state_dict().items()}),
                         s_cal=s_cal, cab=cab, cba=cba)
    del juez
    if dev == "cuda":
        torch.cuda.empty_cache()
    return {"nombre": nombre, "modo": modo, "w": w, "aumento": con_aumento,
            "motivo": con_motivo, "semilla": semilla, "n_entrena": len(tr),
            "historia": historia, "mejor": mejor}


# ---------------------------------------------------------------------------------------
# reanudar
# ---------------------------------------------------------------------------------------
def huella(args, hashes, dispositivo):
    """Lo que tiene que coincidir para retomar corridas guardadas."""
    import torch
    import transformers

    def git(*c):
        try:
            return subprocess.run(["git", *c], cwd=RAIZ, capture_output=True, text=True,
                                  check=True).stdout
        except Exception:
            return None
    h = {"git_commit": (git("rev-parse", "HEAD") or "").strip(),
         "git_diff_sha256": hashlib.sha256((git("diff", "HEAD") or "").encode()).hexdigest(),
         "datos_sha256": hashes, "modelo_sha256": SHA_SAFETENSORS, "plantilla": PLANTILLA,
         "hiper": {"LR": LR, "LR_CABEZA": LR_CABEZA, "BATCH": BATCH, "EPOCAS": EPOCAS,
                   "CALENTAMIENTO": CALENTAMIENTO, "DECAIMIENTO": DECAIMIENTO,
                   "MAXLEN": MAXLEN, "PESO_MOTIVO": PESO_MOTIVO, "P_ERRATA": P_ERRATA,
                   "PESOS_W": PESOS_W, "AUMENTOS": AUMENTOS, "SEMILLAS": SEMILLAS},
         "rapido": args.rapido, "dispositivo": dispositivo,
         "torch": torch.__version__, "transformers": transformers.__version__}
    return json.loads(json.dumps(h))


def punto_guardar(estado, c, con_pesos):
    """Guarda una corrida terminada. El directorio aparece entero o no aparece."""
    import torch
    d = estado / c["nombre"]
    tmp = estado / (c["nombre"] + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    m = c["mejor"]
    if con_pesos:
        torch.save(m["estado"], tmp / "estado.pt")
    np.savez(tmp / "puntajes.npz", s_cal=m["s_cal"], cab=m["cab"], cba=m["cba"])
    meta = {k: c[k] for k in ("nombre", "modo", "w", "aumento", "motivo", "semilla",
                              "n_entrena", "historia")}
    meta["mejor"] = {k: m[k] for k in ("epoca", "perdida", "auc_calibra", "auc_valida",
                                       "segundos")}
    (tmp / "corrida.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)


def punto_leer(estado, nombre):
    d = estado / nombre
    if not (d / "corrida.json").exists():
        return None
    c = json.loads((d / "corrida.json").read_text(encoding="utf-8"))
    z = np.load(d / "puntajes.npz")
    c["mejor"].update(s_cal=z["s_cal"], cab=z["cab"], cba=z["cba"])
    if (d / "estado.pt").exists():
        c["mejor"]["estado_ruta"] = d / "estado.pt"
    return c


def soltar_pesos(estado, c):
    c["mejor"].pop("estado", None)
    c["mejor"].pop("estado_ruta", None)
    (estado / c["nombre"] / "estado.pt").unlink(missing_ok=True)


def guardar(corrida, destino, ctx, extra=None):
    import torch
    destino.mkdir(parents=True, exist_ok=True)
    juez = construir(ctx["modelo"], corrida["motivo"], "cpu")
    pesos = corrida["mejor"].get("estado")
    if pesos is None:
        pesos = torch.load(corrida["mejor"]["estado_ruta"], map_location="cpu")
    juez.load_state_dict(pesos)
    juez.base.save_pretrained(destino)
    ctx["tok"].save_pretrained(destino)
    if juez.motivo is not None:
        torch.save(juez.motivo.state_dict(), destino / "cabeza_motivo.pt")
    info = {k: corrida[k] for k in ("nombre", "modo", "w", "aumento", "motivo", "semilla",
                                    "n_entrena")}
    info.update({"epoca": corrida["mejor"]["epoca"],
                 "auc_calibra": corrida["mejor"]["auc_calibra"],
                 "auc_valida": corrida["mejor"]["auc_valida"],
                 "plantilla": PLANTILLA, "motivos": MOTIVOS,
                 "modelo_base": MODELO_ID, "revision_base": REVISION})
    if extra:
        info.update(extra)
    (destino / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2),
                                       encoding="utf-8")


def temperatura(y, p):
    """T que minimiza la log-verosimilitud en `calibra` sobre logit(P)/T."""
    z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))
    mejor = (None, np.inf)
    for t in np.exp(np.linspace(np.log(0.05), np.log(20), 400)):
        q = 1 / (1 + np.exp(-z / t))
        q = np.clip(q, 1e-9, 1 - 1e-9)
        nll = -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))
        if nll < mejor[1]:
            mejor = (float(t), float(nll))
    return mejor


def ece(y, p, bins=10):
    e, n = 0.0, len(y)
    cortes = np.linspace(0, 1, bins + 1)
    for a, b in zip(cortes[:-1], cortes[1:]):
        m = (p >= a) & (p < b) if b < 1 else (p >= a) & (p <= b)
        if m.any():
            e += m.sum() / n * abs(y[m].mean() - p[m].mean())
    return float(e)


# ---------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", required=True, type=pathlib.Path,
                    help="carpeta con el mDeBERTa-xnli descargado en la revision fijada")
    ap.add_argument("--paquete", type=pathlib.Path, default=PAQUETE)
    ap.add_argument("--salida", type=pathlib.Path, default=SALIDA)
    ap.add_argument("--dispositivo", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--rapido", action="store_true",
                    help="prueba de punta a punta: 200 pares, 1 epoca, 1 semilla, 2 configs")
    ap.add_argument("--desde-cero", action="store_true",
                    help="borra las corridas guardadas y empieza de nuevo")
    args = ap.parse_args()

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import contextlib

    import torch
    from transformers import AutoTokenizer
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

    dev = ("cuda" if torch.cuda.is_available() else "cpu") if args.dispositivo == "auto" \
        else args.dispositivo
    usa_bf16 = dev == "cuda" and torch.cuda.is_bf16_supported()

    def autocast():
        return (torch.autocast("cuda", dtype=torch.bfloat16) if usa_bf16
                else contextlib.nullcontext())

    print("=" * 78)
    print("22 · ENTRENAR EL CROSS-ENCODER (D-036)   dispositivo {}{}{}".format(
        dev, ", bf16" if usa_bf16 else ", fp32", "   [RAPIDO]" if args.rapido else ""))
    print("=" * 78)

    verificar_modelo(args.modelo)
    plata, cal, man, hashes = cargar_paquete(args.paquete)
    print("paquete: plata {:,} ({}), calibra {} ({} si / {} no). prueba en el paquete: 0".format(
        len(plata), plata["particion"].value_counts().to_dict(), len(cal),
        int(cal["y"].sum()), int((1 - cal["y"]).sum())))

    tok = AutoTokenizer.from_pretrained(args.modelo)
    ctx = {"dispositivo": dev, "tok": tok, "autocast": autocast, "modelo": args.modelo,
           "rapido": args.rapido}
    datos = {"plata": plata, "calibra": cal}
    y_cal = cal["y"].to_numpy()

    # --- 1. el juez sin entrenar tiene que dar el AUC_BASE de `19` -------------------
    print("\n1. JUEZ SIN ENTRENAR sobre calibra, fp32 (tiene que dar {:.4f})".format(AUC_BASE))
    juez0 = construir(args.modelo, False, dev)
    ab0, ba0 = puntuar(juez0, tok, cal["comun"].tolist(), cal["raro"].tolist(), dev,
                       contextlib.nullcontext)
    del juez0
    auc0 = auc(y_cal, (ab0 + ba0) / 2)
    print("   AUC {:.4f}".format(auc0))
    if abs(auc0 - AUC_BASE) > TOL_BASE:
        raise SystemExit("ALTO: el juez sin entrenar da {:.4f} y no {:.3f}. Algo cambio: "
                         "plantilla, tokenizador o modelo.".format(auc0, AUC_BASE))
    auc_cos = auc(y_cal, cal["sim"].to_numpy(float))
    print("   coseno en los mismos pares: {:.4f}".format(auc_cos))

    # --- reanudar: solo si la huella coincide -------------------------------------------
    estado = args.salida / ("estado_rapido" if args.rapido else "estado")
    if args.desde_cero and estado.exists():
        shutil.rmtree(estado)
        print("\n--desde-cero: estado anterior borrado")
    hu = huella(args, hashes, dev)
    if (estado / "huella.json").exists():
        vieja = json.loads((estado / "huella.json").read_text(encoding="utf-8"))
        if vieja != hu:
            dif = sorted(k for k in set(vieja) | set(hu) if vieja.get(k) != hu.get(k))
            raise SystemExit("ALTO: hay corridas guardadas en {} de otra configuracion "
                             "(cambia: {}). No se mezclan. Para empezar de nuevo: "
                             "--desde-cero".format(estado, ", ".join(dif)))
        hechas = sorted(p.parent.name for p in estado.glob("*/corrida.json"))
        print("\nREANUDANDO: {} corrida(s) ya hechas en {}".format(len(hechas), estado))
    else:
        estado.mkdir(parents=True, exist_ok=True)
        (estado / "huella.json").write_text(json.dumps(hu, indent=2), encoding="utf-8")
    retomadas = []

    def correr(nombre, modo, w, aum, motivo, semilla):
        c = punto_leer(estado, nombre)
        if c is not None:
            retomadas.append(nombre)
            print("    {:<28} ya hecha: ep {}  AUC calibra {:.4f}  valida {:.4f}  (retomada)"
                  .format(nombre, c["mejor"]["epoca"], c["mejor"]["auc_calibra"],
                          c["mejor"]["auc_valida"]), flush=True)
            return c, False
        return entrenar(nombre, modo, w, aum, motivo, semilla, datos, ctx), True

    res = {"ficha": ficha(args, dev), "datos_sha256": hashes,
           "paquete_manifiesto": man, "auc_sin_entrenar": auc0, "auc_coseno": auc_cos,
           "corridas": [], "grilla": {}, "retomadas": retomadas}
    semillas = SEMILLAS[:1] if args.rapido else SEMILLAS
    grilla = [(1, False), (2, True)] if args.rapido else [(w, a) for w in PESOS_W
                                                           for a in AUMENTOS]

    def registrar(c):
        m = c["mejor"]
        res["corridas"].append({k: c[k] for k in ("nombre", "modo", "w", "aumento",
                                                  "motivo", "semilla", "n_entrena",
                                                  "historia")}
                               | {"epoca_elegida": m["epoca"],
                                  "auc_calibra": m["auc_calibra"],
                                  "auc_valida": m["auc_valida"]})

    # --- 2. pasos 1 y 2: ablacion, una semilla, sin aumento ------------------------------
    print("\n2. PASOS 1 Y 2 (ablacion: una semilla, sin aumento)")
    ablacion = {}
    for modo in ("simetrico", "direccional"):
        c, nueva = correr("paso_" + modo, modo, 1, False, False, SEMILLAS[0])
        registrar(c)
        ablacion[modo] = c
        if nueva:
            if not args.rapido:
                guardar(c, args.salida / "corridas" / c["nombre"], ctx)
            punto_guardar(estado, c, con_pesos=False)
        c["mejor"].pop("estado", None)

    # --- 3. paso 3: la grilla, tres semillas --------------------------------------------
    print("\n3. PASO 3: grilla w x aumento, {} semilla(s) por configuracion".format(
        len(semillas)))
    reps = {}
    for w, aum in grilla:
        nom = "completo_w{}_{}".format(w, "con_aum" if aum else "sin_aum")
        corr = []
        for s in semillas:
            c, nueva = correr("{}_s{}".format(nom, s), "direccional", w, aum, True, s)
            if nueva:
                punto_guardar(estado, c, con_pesos=not args.rapido)
            registrar(c)
            corr.append(c)
        aucs = [c["mejor"]["auc_calibra"] for c in corr]
        media = float(np.mean(aucs))
        rep = min(corr, key=lambda c: abs(c["mejor"]["auc_calibra"] - media))
        for c in corr:
            if c is not rep:
                soltar_pesos(estado, c)
        reps[(w, aum)] = rep
        res["grilla"][nom] = {"w": w, "aumento": aum, "auc_por_semilla": aucs,
                              "auc_media": media, "auc_sd": float(np.std(aucs)),
                              "semilla_representante": rep["semilla"],
                              "auc_valida_representante": rep["mejor"]["auc_valida"]}
        print("   {:<26} AUC calibra medio {:.4f} (sd {:.4f})  representante s{}".format(
            nom, media, float(np.std(aucs)), rep["semilla"]), flush=True)

    # --- 4. eleccion con desempate a favor de la mas simple ----------------------------
    simple = (1, False)
    medias = {k: res["grilla"]["completo_w{}_{}".format(k[0], "con_aum" if k[1]
                                                        else "sin_aum")]["auc_media"]
              for k in reps}
    mejor_k = max(medias, key=medias.get)
    rng = np.random.default_rng(SEMILLAS[0])
    eleccion = {"mejor_por_media": list(mejor_k), "simple": list(simple)}
    if mejor_k == simple:
        elegido_k, motivo = simple, "la mejor por AUC medio ya es la mas simple"
    else:
        lo, hi = boot_diferencia(y_cal, reps[mejor_k]["mejor"]["s_cal"],
                                 reps[simple]["mejor"]["s_cal"], rng)
        eleccion["ic95_mejor_menos_simple"] = [lo, hi]
        if lo > 0:
            elegido_k, motivo = mejor_k, "le gana a la simple con IC95 sobre cero"
        else:
            elegido_k, motivo = simple, "no le gana a la simple con IC95 sobre cero"
    eleccion.update({"elegida": list(elegido_k), "razon": motivo})
    print("\n4. ELECCION: w={} aumento={}  ({})".format(elegido_k[0], elegido_k[1], motivo))

    # --- 5. calibracion ---------------------------------------------------------------
    elegido = reps[elegido_k]
    s = elegido["mejor"]["s_cal"]
    t, nll = temperatura(y_cal, s)
    z = np.log(np.clip(s, 1e-6, 1 - 1e-6) / np.clip(1 - s, 1e-6, 1))
    s_t = 1 / (1 + np.exp(-z / t))
    calib = {"temperatura": t, "nll": nll, "ece_antes": ece(y_cal, s),
             "ece_despues": ece(y_cal, s_t)}
    print("5. CALIBRACION: T = {:.3f}   ECE {:.3f} -> {:.3f}".format(
        t, calib["ece_antes"], calib["ece_despues"]))

    # --- 6. por estrato, y la ablacion lado a lado ------------------------------------
    por_estrato = {}
    for e, g in cal.groupby("estrato"):
        ix = g.index.to_numpy()
        if g["y"].nunique() == 2:
            por_estrato[e] = {"n": len(ix), "auc_elegido": auc(y_cal[ix], s[ix]),
                              "auc_coseno": auc(y_cal[ix], cal["sim"].to_numpy(float)[ix])}
    abl = {"sin_entrenar": auc0, "coseno": auc_cos,
           "paso1_simetrico": ablacion["simetrico"]["mejor"]["auc_calibra"],
           "paso2_direccional": ablacion["direccional"]["mejor"]["auc_calibra"],
           "paso3_elegido": elegido["mejor"]["auc_calibra"]}
    print("\n6. ABLACION en calibra (optimista: calibra tambien eligio la epoca)")
    for k, v in abl.items():
        print("   {:<20} {:.4f}".format(k, v))

    res.update({"eleccion": eleccion, "calibracion": calib, "por_estrato_calibra":
                por_estrato, "ablacion_calibra": abl})
    args.salida.mkdir(parents=True, exist_ok=True)
    if not args.rapido:
        guardar(elegido, args.salida / "elegido", ctx, {"temperatura": t,
                                                         "eleccion": eleccion})
        for k, c in reps.items():
            guardar(c, args.salida / "corridas" / "completo_w{}_{}".format(
                k[0], "con_aum" if k[1] else "sin_aum"), ctx)
    (args.salida / ("resultados_rapido.json" if args.rapido else "resultados.json")
     ).write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float),
                  encoding="utf-8")
    for f in estado.glob("*/estado.pt"):      # ya estan en `elegido/` y `corridas/`
        f.unlink()
    if retomadas:
        print("\n({} corrida(s) retomadas del disco)".format(len(retomadas)))
    print("\nresultados -> {}".format(args.salida))
    if args.rapido:
        print("(--rapido: no se guardan pesos; los numeros NO sirven para decidir nada)")


if __name__ == "__main__":
    main()
