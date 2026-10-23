# Dominio

Las decisiones de metodo viven en `docs/registro_decisiones.md` (D-001...D-092) y las
cifras medidas en `docs/mediciones.md`. El codigo cita la decision donde la aplica.

## Glosario

- **Puesto / celda**: un titulo de cargo de la base con sus estadisticos. Varias
  **grafias** del mismo puesto forman un **grupo** (`VENDEDOR`, `VENDEDORA`, `VEDEDOR`).
- **Homologar**: llevar el titulo del cliente a un puesto de la base: tal cual, capa 0
  (abreviaturas, erratas, genero), grados, sinonimos aprobados, tipeo, juez, traduccion.
  Si nada lo resuelve, la referencia sale **por analogia** (vecinos por embedding).
- **Juez**: cross-encoder que dice si dos titulos son el mismo puesto (D-036, D-048).
- **Referencia**: el centro de la banda de EMPRESAS del puesto, en dolares del ano.
  `p10`..`p90` es la banda de empresas; `p10Per`..`p90Per`, la de personas.
- **Confianza**: ALTA / MEDIA / BAJA, segun empresas detras y ancho de banda (D-069).
- **Estado de una fila**: `directa`, `directa_rubro`, `traduccion`, `analogia`,
  `sin_referencia`, `sueldo_ilegible`, `cargo_vacio`, `cargo_no_reconocido` (D-075).
- **Ancla de empresa**: la mediana de (lo que paga - lo que dice el mercado) sobre la
  nomina entera; habilita la lectura de equidad interna. Solo existe en `/informes`.
- **SBU**: salario basico unificado del ano (acuerdo ministerial). Divide todo el
  modelo: `y = log(sueldo / SBU)`. Sin SBU del ano, el informe no se emite.

## Reglas de negocio

- **Suelos de confidencialidad**: un puesto se publica con >= 3 empresas; su rubro con >= 10.
- **Cascada CIIU**: con el CIIU del cliente, cada cargo con datos directos se compara
  contra la clase, el grupo, la division o la seccion: el primer nivel con >= 30 empresas.
  La homologacion NO usa el CIIU. Los cargos por analogia tampoco.
- **Segmento** (tamano de empresa): ajusta la referencia por el nivel del cargo (D-063).
  Sale del RUC si no se pide.
- **Titulos en ingles**: van a la banda de su equivalente en espanol (D-088); los de
  direccion, con la prima del mercado que titula en ingles (D-092, precalculada).
- **Nominas guardadas**: cargo y sueldo de cada fila, con RUC, CIIU y lo que respondio el
  modelo. Nunca nombres, cedulas ni otras columnas personales.
