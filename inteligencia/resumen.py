# inteligencia/resumen.py — el párrafo de viabilidad, redactado por Bedrock.
# ─────────────────────────────────────────────────────────────────
# Es lo ÚNICO de la ficha que consume tokens: unos 790 de entrada y 250 de
# salida por caso. El mapa, la competencia y el sitio web son llamadas normales
# a una API.
#
# TRES CONDICIONES QUE NO SE NEGOCIAN (acordadas el 29-sep-2026):
#
#   1. El modelo solo redacta LO QUE SE MIDIÓ. Si un criterio quedó pendiente,
#      lo dice; no lo rellena. Un párrafo bonito con un dato inventado es peor
#      que no tener párrafo.
#   2. Va marcado como BORRADOR, con los cinco criterios y sus fuentes visibles
#      al lado. Quien firma lee la evidencia, no solo el párrafo.
#   3. NO decide ni recomienda autorizar o rechazar. Describe qué tan afín es el
#      negocio; la decisión de crédito es del comité y queda en su firma.
#
# Se usa el mismo modelo que Eco-Admin ya tiene habilitado en la cuenta
# (Sonnet 4.5), por decisión del usuario: así no hay que pedir acceso a otro
# modelo en Bedrock.
#
# Fail-open, como todo lo demás de la ficha: si Bedrock falla, el expediente
# sigue su curso sin párrafo y con el aviso puesto.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os

import boto3

_BEDROCK = None

MODELO = os.environ.get("BEDROCK_MODEL_ID",
                        "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

INSTRUCCION = """Eres analista de crédito de GPA (General de Productos para el Agua).
GPA vende DE NEGOCIO A NEGOCIO equipo para albercas, tratamiento de agua y bombeo;
sus clientes son distribuidores que REVENDEN, no consumidores finales.

Con los datos de abajo, redacta en español de México un párrafo de 4 a 6 líneas
sobre qué tan afín es este prospecto al negocio de GPA.

Reglas que debes cumplir:
- Menciona SOLO lo que viene en los datos. No supongas nada que no esté ahí.
- Si un criterio viene como "pendiente", dilo tal cual. No lo rellenes ni lo
  des por bueno ni por malo.
- NO recomiendes autorizar ni rechazar, y no sugieras un monto de crédito. Eso
  lo decide el comité. Tú describes al prospecto.
- Nada de listas ni encabezados: un solo párrafo corrido.
- Si el prospecto parece usuario final y no distribuidor, dilo con claridad."""

# Frases que delatan que el modelo se salió de su papel. No se le borra el texto
# —eso escondería el problema—, se le avisa a quien lo va a leer.
_RECOMENDACIONES = [
    "recomiendo autorizar", "recomiendo aprobar", "recomiendo rechazar",
    "se recomienda autorizar", "se recomienda aprobar", "se recomienda rechazar",
    "debe autorizarse", "debe rechazarse", "sugiero autorizar", "sugiero rechazar",
    "apruébese", "recházese", "no se le debe dar", "sí se le debe dar",
]


def _cliente():
    global _BEDROCK
    if _BEDROCK is None:
        _BEDROCK = boto3.client("bedrock-runtime",
                                region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _BEDROCK


def _datos(ficha: dict, caso: dict) -> dict:
    """Solo lo medido. Nada de adjuntos, comentarios ni datos del expediente que
    no tengan que ver con qué tan afín es el negocio."""
    lugar = ficha.get("lugar") or {}
    web = ficha.get("web") or {}
    return {
        "razonSocial": caso.get("razonSocial", ""),
        "giroDeclarado": caso.get("giro", ""),
        "operaDesde": ficha.get("inicioOps", ""),
        "lugar": {"nombre": lugar.get("nombre", ""),
                  "direccion": lugar.get("direccion", ""),
                  "categorias": lugar.get("categorias") or []},
        "competencia": {r: d.get("total") for r, d in (ficha.get("competencia") or {}).items()},
        "sitioWeb": {"responde": bool(web.get("ok")),
                     "menciona": web.get("menciona") or []},
        "redesDeclaradas": [r.get("red") for r in (ficha.get("redes") or [])],
        "criterios": [{"criterio": c["titulo"], "estado": c["estado"],
                       "detalle": c["detalle"]} for c in (ficha.get("criterios") or [])],
    }


def redacta(ficha: dict, caso: dict, cliente=None) -> tuple:
    """Devuelve (párrafo, avisos). Nunca lanza: la ficha vale sin él."""
    try:
        carga = INSTRUCCION + "\n\nDATOS:\n" + json.dumps(_datos(ficha, caso),
                                                          ensure_ascii=False, indent=1)
        r = (cliente or _cliente()).converse(
            modelId=MODELO,
            messages=[{"role": "user", "content": [{"text": carga}]}],
            # Temperatura baja: se busca que describa igual los mismos datos,
            # no que sea creativo. Esto es parte de un expediente.
            inferenceConfig={"maxTokens": 500, "temperature": 0.2},
        )
        texto = r["output"]["message"]["content"][0]["text"].strip()
    except Exception as e:
        return "", [f"No se pudo redactar el resumen ({type(e).__name__}). "
                    "Los cinco criterios están completos; el párrafo se puede "
                    "volver a pedir desde el expediente."]

    avisos = []
    bajo = texto.lower()
    if any(f in bajo for f in _RECOMENDACIONES):
        avisos.append("El resumen incluye una recomendación de autorizar o rechazar. "
                      "No le haga caso: esa decisión es del comité y queda en su firma.")
    return texto, avisos
