# Deuda tecnica

Por prioridad. Lo que no cumple una regla FROZEN se registra aqui, no se suaviza la regla.

## Alta

1. **Migrar los embeddings fuera del SDK `vertexai`.** Google lo marco deprecado
   (`TextEmbeddingModel`, aviso en el log al arrancar: "will be removed on June 24, 2026").
   Hoy funciona con `google-cloud-aiplatform==2.3.0`. Pasar a `google-genai` y comprobar
   contra la foto que los embeddings no cambian.
2. **Medir el arranque en frio en Cloud Run.** Desde el H200 (fuera de Google): bajar los
   artefactos 53-63 s, crear el cliente de Vertex 18,6 s, primera llamada 9,2 s, primer
   `referenciar` 6,4 s. En la red de Google deberia ser mucho menos; no esta medido.
3. **Secciones FROZEN de `CLAUDE.md` y `.claude/rules/` reconstruidas desde el documento
   del estandar**, no copiadas de `plantilla-backend-python` (no estaba disponible).
   Verificarlas literal. Lo mismo con la seleccion de reglas de ruff (hoy las clasicas).

## Media

4. **Tests de comportamiento detras del adaptador v1.3** (`tests/fakes/cliente_v13.py`):
   ~70 tests de `test_servicio.py`, `test_segmento_del_ruc.py` y `test_registro_nominas.py`
   hablan el contrato viejo. Migrarlos al contrato nuevo, al espejo de `src/` y con
   `pytestmark` por modulo, y retirar el adaptador.
5. **`api/responses/` vacio**: el contenido de las respuestas se declara como
   `dict[str, Any]`. Tiparlo con DTOs (el detalle lleva columnas del cliente dinamicas).
6. **Banderas de experimentos en `domain/base_referencia.py`**: ramas `*_placebo` y
   opciones medidas y no adoptadas. Quitarlas dejando fijo lo de la v1.3, contra la foto.
7. **`domain/idioma.py` mezcla reglas de texto con la carga del traductor** (MarianMT):
   la carga deberia vivir en `infrastructure/modelos/`.

## Baja

8. **`capacidades` en `/salud` pasa a camelCase** (`rucAIndustria`): son nombres de
   capacidad, no campos; valorar dejarlas como claves de dato.
9. **El cache de embeddings se vacia entero** al pasar de 50.000 titulos nuevos.
