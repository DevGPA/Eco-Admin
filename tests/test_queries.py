# Tests de db/queries.py — el monitor debe devolver SOLO solicitudes (#META),
# no los items de índice CP#/FV# que también caen en estado-fecha-idx.
import db.queries as queries


class FakeTable:
    """Simula query con FilterExpression(SK==#META) y paginación."""
    def __init__(self, items):
        self.items = items

    def query(self, **kw):
        flt = kw.get("FilterExpression")
        out = self.items
        if flt is not None:
            # Reproduce Attr("SK").eq("#META"): solo items con SK == "#META".
            out = [i for i in out if i.get("SK") == "#META"]
        return {"Items": out}


# Una solicitud AUTO_RECHAZADA genera 3 items en estado-fecha-idx:
#   #META (con código/monto)  +  CP#folio  +  FV#folio  (sin código/monto)
DATA = [
    {"SK": "#META", "PK": "SOL#1", "estado": "AUTO_RECHAZADA",
     "fechaEmision": "2026-05-07", "codigoMotor": "R-301", "folioCP": "118533650",
     "montoBaseUSD": "2885.74"},
    {"SK": "SOL#1", "PK": "CP#118533650", "estado": "AUTO_RECHAZADA",
     "fechaEmision": "2026-05-07"},                       # item índice CP (basura)
    {"SK": "SOL#1", "PK": "FV#FA1", "estado": "AUTO_RECHAZADA",
     "fechaEmision": "2026-05-07"},                       # item índice FV (basura)
    {"SK": "#META", "PK": "SOL#2", "estado": "AUTO_RECHAZADA",
     "fechaEmision": "2026-05-08", "codigoMotor": "R-101", "folioCP": "118574983",
     "montoBaseUSD": "82.25"},
]


def test_rango_fecha_solo_devuelve_meta(monkeypatch):
    monkeypatch.setattr(queries, "_table", lambda: FakeTable(DATA))
    items = queries.get_por_rango_fecha("AUTO_RECHAZADA", "2025-01-01", "2027-12-31")
    assert len(items) == 2                          # 2 solicitudes, NO 6
    assert all(i["SK"] == "#META" for i in items)
    assert all(i.get("codigoMotor") for i in items)  # ninguna tarjeta "undefined"
    assert {i["folioCP"] for i in items} == {"118533650", "118574983"}


def test_cola_revision_solo_meta(monkeypatch):
    data = [
        {"SK": "#META", "PK": "SOL#9", "estado": "EN_REVISION",
         "fechaEmision": "2026-06-12", "codigoMotor": "R-301", "folioCP": "X"},
        {"SK": "SOL#9", "PK": "CP#X", "estado": "EN_REVISION", "fechaEmision": "2026-06-12"},
    ]
    monkeypatch.setattr(queries, "_table", lambda: FakeTable(data))
    items = queries.get_cola_revision("2025-01-01")
    assert len(items) == 1 and items[0]["SK"] == "#META"


def test_paginacion_acumula(monkeypatch):
    # Si DynamoDB pagina (LastEvaluatedKey), _query_meta debe juntar todo.
    class Paginada:
        def __init__(self):
            self.n = 0
        def query(self, **kw):
            self.n += 1
            if self.n == 1:
                return {"Items": [{"SK": "#META", "PK": "SOL#a", "estado": "EN_REVISION",
                                   "codigoMotor": "R-301"}],
                        "LastEvaluatedKey": {"PK": "x"}}
            return {"Items": [{"SK": "#META", "PK": "SOL#b", "estado": "EN_REVISION",
                               "codigoMotor": "R-101"}]}
    p = Paginada()   # una sola instancia (el loop llama _table() en cada vuelta)
    monkeypatch.setattr(queries, "_table", lambda: p)
    items = queries.get_cola_revision()
    assert len(items) == 2
