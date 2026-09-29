# Herramientas del importador

Cuatro scripts en Python que leen el plan **desde el archivo `.xlsx` original** —incluidos
los colores de las celdas— y producen los catálogos que usa el módulo. Son la única
implementación probada de cómo se lee el plan; el importador del módulo en Operaciones-GPA
debe portar esta lógica, no reinventarla.

**Ninguno escribe en el Excel original.** Leen una copia y escriben archivos nuevos en la
carpeta `mantenimiento-gpa/`.

## Requisitos

- Python 3.12 con `openpyxl` (`pip install openpyxl`).
- Una copia de `CALENDARIO MANTENIMIENTO 2025 SCS.xlsx`. Por omisión se busca en
  `C:\Users\Gerencia-\Downloads\99_Por_Clasificar\`. Para usar otra ruta:
  `set MTTO_PLAN_XLSX=C:\ruta\al\archivo.xlsx` antes de correr.
- En Windows: `set PYTHONIOENCODING=utf-8` para que no tropiece con acentos.

## Orden de ejecución

| # | Script | Lee | Escribe | Qué hace |
|---|---|---|---|---|
| 1 | `codificar.py` | el xlsx | `CATALOGO-CODIGOS-mantenimiento-GPA.xlsx` | Recodifica los 233 activos a `TIPO-SUC-##` y explica cada cambio |
| 2 | `plan_semanas.py` | el xlsx + catálogo | `PLAN-2026-semanas-limite.xlsx` | Semanas límite por activo, las 546 ejecuciones, tono por sucursal y el **acta de importación** |
| 3 | `gen_plan_js.py` | el xlsx + catálogo | `herramientas/plan.js` | El plan como literal JS para la app independiente |

`leer_colores.py` es el lector común: los otros tres lo importan. También se puede correr
solo para ver el diagnóstico completo de tonos, cobertura y marcas por periodicidad.

```
cd "C:\Users\Gerencia-\Documents\01 Gerencia Administrativa\CLAUDE\mantenimiento-gpa\herramientas"
set PYTHONIOENCODING=utf-8
python codificar.py
python plan_semanas.py
python gen_plan_js.py
```

## Cifras que deben salir

Si el archivo fuente es el mismo, estos números no cambian. Si cambian, algo se leyó mal:

| Cifra | Valor |
|---|---:|
| Activos y servicios | 233 |
| Vencimientos (celdas pintadas) | 546 |
| Activos sin ninguna semana | 3 |
| Filas del acta de importación | 57 |
| Semana 1 de 2026 empieza | 29-dic-2025 |

## Lo que el lector ya sabe y que no hay que redescubrir

- Los números de semana están en la **fila 6** de la hoja; las filas 7 y 8 son fórmulas
  de fecha. El encabezado tiene 53 columnas para 52 semanas: la 52 está repetida.
- Los datos empiezan en la **fila 10**. La 9 es encabezado del calendario y trae 12 celdas
  pintadas que no son actividades.
- Una fila es **sección** cuando tiene descripción y ningún otro dato (modelo, serie,
  ubicación, código, periodicidad, responsabilidad). No basta contar celdas llenas: algunas
  secciones arrastran etiquetas de mes en las últimas columnas.
- Las secciones `GDL CEDIS`, `GDL CALZADA`, `NAVE MEX`, `NAVE MTY`, `NAVE CANCUN`,
  `NAVE PV` y `NAVE LOS CABOS` son **sitios**, no áreas: sus filas van al área
  `SERVICIOS GENERALES` y el sitio sale del nombre de la sección.
- La **sucursal se toma de la columna E**, nunca del color. El color solo se cruza contra
  ella para detectar errores de captura.
- Dos sucursales usan **colores de tema** (`theme9/+0.80`, `theme5/+0.60`), no RGB fijo.
  Para mostrarlos hay que resolverlos contra la paleta del libro; para importar no hace
  falta: basta saber que la celda está pintada.
- El blanco (`FFFFFFFF`, `00000000`, tema 0 sin matiz) **no cuenta** como marca.
