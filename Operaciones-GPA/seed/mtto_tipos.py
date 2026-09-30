# -*- coding: utf-8 -*-
# seed/mtto_tipos.py — Los 23 tipos de activo del Plan de Mantenimiento: procedimiento,
# puntos de revisión, material y herramienta. SON DATOS de carga inicial: después se
# editan desde Plan Mtto → Catálogos → Tipos, y el importador NO los sobreescribe.
#
#   · 10 tipos vienen de «PLAN DE MANTENIMIENTO - SAULO.xlsx» (esPropuesta=False).
#   · 13 tipos NO están descritos en ningún archivo de GPA: son las PROPUESTAS de
#     docs/mantenimiento/PROCEDIMIENTOS-PROPUESTOS.md (esPropuesta=True), con los
#     datos técnicos que solo Mantenimiento puede dar marcados ⟨confirmar⟩.
#   · EXT: por decisión del usuario (DECISIONES.md #3) la actividad es la REVISIÓN
#     del extintor por GPA, no la gestión de la recarga.
# Material y herramienta no vienen de ningún archivo: son punto de partida.
# ─────────────────────────────────────────────────────────────────

PROTOCOLO_SUPERVISION = (
    "El trabajo del proveedor NO es un trámite: la actividad se cierra cuando GPA verificó que "
    "se ejecutó lo acordado. ANTES (la semana previa): confirmar fecha y hora por escrito, tener "
    "la orden de servicio o contrato con el alcance, avisar a la sucursal y verificar que el "
    "proveedor traiga su documentación vigente ⟨confirmar cuál exige GPA: póliza, DC-3, alta "
    "patronal⟩. DURANTE: alguien de GPA acompaña la ejecución, verifica los puntos críticos del "
    "tipo y que el personal externo trabaje con su equipo de protección; si el proveedor va a "
    "hacer menos de lo acordado, se detiene y se reporta antes de que termine. DESPUÉS: recibir "
    "el reporte u orden de servicio firmada con lo hecho y las refacciones cambiadas, verificar "
    "en el equipo los criterios de aceptación, fotografiar equipo y reporte, registrar garantía y "
    "fecha del siguiente servicio. NO SE ACEPTA: reporte sin detalle o firmado sin que GPA viera "
    "el trabajo; refacciones cobradas que no se pueden mostrar; equipo con una falla ya reportada "
    "sin atender; servicio en fecha distinta sin aviso. En esos casos NO se cierra como completada: "
    "se registra la incidencia y queda pendiente hasta que el proveedor regrese.")


def _t(pref, nombre, procedimiento, puntos, materiales=(), herramienta=(), supervision="", propuesta=False):
    return {"pref": pref, "nombre": nombre, "procedimiento": procedimiento, "puntos": list(puntos),
            "materiales": list(materiales), "herramienta": list(herramienta),
            "supervision": supervision, "esPropuesta": bool(propuesta)}


TIPOS = [
    # ── Con procedimiento escrito (SAULO) ─────────────────────────
    _t("AIR", "Mini split / aire acondicionado",
       "Realizar limpieza y mantenimiento del equipo confirmando su buen funcionamiento; en caso de "
       "falla, realizar reparación.",
       ["Filtros lavados", "Serpentín limpio", "Drenaje sin obstrucción", "Enfría a temperatura",
        "Sin fuga de gas"],
       ["Filtro de repuesto · 1 pza", "Desengrasante · 1 L"],
       ["Hidrolavadora", "Escalera 2 m", "Termómetro"]),
    _t("FON", "Fontanería",
       "Realizar inspección de tuberías, drenajes y coladeras con el fin de detectar alguna fuga, "
       "desgaste o mal funcionamiento. Revisar llaves de agua que el flujo sea correcto; en caso de "
       "falla realizar reparación o solicitar cambio.",
       ["Tuberías sin fuga", "Coladeras destapadas", "Llaves con flujo correcto", "WC y regaderas sin goteo"],
       ["Cinta teflón · 2 pzas", "Sellador de roscas · 1 pza"],
       ["Llave stilson", "Sonda destapadora", "Cubeta"]),
    _t("ILU", "Iluminación",
       "Revisar iluminación de los niveles 1 a 6: lámparas y focos. Reemplazar lo fundido y confirmar "
       "el encendido por circuito.",
       ["Nivel 1 a 3", "Nivel 4 a 6", "Exteriores y patio", "Lámparas fundidas repuestas"],
       ["Lámpara LED 48 W · 6 pzas", "Balastro · 1 pza"],
       ["Escalera de tijera 4 m", "Multímetro", "Arnés"]),
    _t("PIN", "Pintura",
       "Revisar pintura y acabados en oficinas, áreas comunes y exteriores; en caso de requerir "
       "mantenimiento, aplicarlo.",
       ["Oficinas", "Áreas comunes", "Exteriores", "Aplicación donde se requirió"],
       ["Pintura vinílica · 20 L", "Sellador · 5 L", "Rodillos · 2 pzas"],
       ["Brocha y charola", "Andamio", "Lija"]),
    _t("MOB", "Mobiliario de oficina",
       "Revisar rieles, bisagras y madera de escritorios, sillas, clósets y gabinetes; que no estén "
       "flojos y estén en buen estado. En caso de ser necesaria la reparación, aplicarla; si no, "
       "solicitar cambio.",
       ["Escritorios", "Sillas", "Clósets y gabinetes"],
       ["Tornillería surtida · 1 caja", "Bisagras · 4 pzas"],
       ["Desarmadores", "Taladro"]),
    _t("TAB", "Eléctrico a tableros",
       "Mantenimiento preventivo a tableros: medición de amperaje, balance de cargas, reapriete de "
       "tornillos y terminales, limpieza y lubricado, identificación de circuitos, revisión de "
       "polaridad y voltaje de contactos y buen funcionamiento de apagadores. Revisar que la tubería "
       "esté en buen estado.",
       ["Medición de amperaje", "Balance de cargas", "Reapriete de terminales", "Limpieza y lubricado",
        "Circuitos identificados", "Tubería en buen estado"],
       ["Cinta de aislar · 2 pzas", "Limpiador de contactos · 1 pza"],
       ["Multímetro", "Pinza amperimétrica", "Torquímetro", "EPP dieléctrico"]),
    _t("ELE", "Eléctrico interno",
       "Revisar cableado, tubería, contactos y apagadores; que se encuentren en buen estado y "
       "funcionando. En caso de encontrar falla, realizar reparación.",
       ["Cableado", "Tubería", "Contactos y apagadores", "Sin puntos calientes"],
       ["Cable THW · 10 m", "Contactos · 4 pzas"],
       ["Multímetro", "Pinzas", "EPP dieléctrico"]),
    _t("IMP", "Impermeabilización",
       "Revisar que los techos se encuentren en buen estado y limpios; en caso de detectar grietas o "
       "desgaste en el impermeabilizante, realizar reparación.",
       ["Láminas o azotea revisadas", "Grietas selladas", "Impermeabilizante en buen estado"],
       ["Impermeabilizante · 19 L", "Sellador de láminas · 1 pza"],
       ["Escalera 6 m", "Arnés", "Espátula"]),
    _t("CNL", "Limpieza de canaletas",
       "Realizar limpieza de canaletas y revisar su buen funcionamiento.",
       ["Canaletas limpias", "Sin estancamiento", "Sujeción firme"],
       ["Bolsas para residuo · 5 pzas"],
       ["Escalera 6 m", "Arnés", "Manguera"]),
    _t("BAJ", "Bajantes pluviales",
       "Realizar limpieza en bajantes y revisar su buen funcionamiento.",
       ["Bajantes destapados", "Sin fuga", "Descarga libre"],
       ["Sellador · 1 pza"],
       ["Sonda", "Escalera 6 m", "Arnés"]),

    # ── Propuestas (ningún archivo de GPA las describe) ──────────
    _t("FUM", "Fumigación",
       "Aplicar el protocolo de supervisión. Antes del servicio, acordar con el proveedor qué áreas se "
       "tratan y con qué producto, y avisar al personal para que despeje alimentos, utensilios y áreas "
       "de descanso. Durante la aplicación, verificar que se traten todas las áreas del alcance "
       "—almacén, oficinas, comedor, baños, patios y registros sanitarios— y no solo las visibles. "
       "Después, recibir el certificado o constancia de aplicación con el producto y la dosis usados, "
       "y respetar el tiempo de reingreso que indique el proveedor. Si se sigue viendo plaga entre "
       "servicios, es incidencia del proveedor: se exige revisita dentro de la garantía.",
       ["Áreas del alcance tratadas, incluidos registros y patios",
        "Producto, dosis y número de registro sanitario asentados",
        "Personal y alimentos retirados durante la aplicación", "Tiempo de reingreso respetado",
        "Certificado o constancia recibida"],
       ["Señalización de área tratada"], ["Resguardo del certificado"],
       "Lo ejecuta el proveedor y GPA lo supervisa. Verifica que se traten TODAS las áreas del alcance "
       "—incluidos registros y patios—, no solo las visibles, y recibe el certificado con producto y dosis.",
       True),
    _t("MON", "Montacargas",
       "Aplicar el protocolo de supervisión. El servicio se programa por HORAS de operación, no solo por "
       "calendario: tomar la lectura del horómetro antes del servicio y asentarla, porque determina el "
       "siguiente. Verificar que el proveedor ejecute el servicio que corresponde a esas horas "
       "⟨confirmar la tabla de servicios por horas de cada marca: Doosan, Hyster, Nissan, Cat⟩. Durante "
       "la ejecución, verificar frenos, claxon, torreta, cinturón y el estado de las horquillas. Después, "
       "probar el equipo en piso con carga antes de aceptar el servicio. Un montacargas con falla de "
       "frenos, dirección u horquillas se etiqueta FUERA DE SERVICIO y no se usa hasta repararlo.",
       ["Horómetro leído y asentado", "Servicio ejecutado corresponde a las horas acumuladas",
        "Frenos, claxon, torreta y cinturón funcionando", "Horquillas sin grietas ni deformación",
        "Sin fuga de aceite hidráulico ni de combustible", "Equipo probado en piso con carga",
        "Orden de servicio y refacciones cambiadas verificadas"],
       [], ["El horómetro se lee con el equipo encendido"],
       "Lo ejecuta el proveedor y GPA lo supervisa. Acompaña el servicio, lee el horómetro antes, "
       "verifica frenos, horquillas y fugas, y prueba el equipo en piso con carga antes de aceptarlo.",
       True),
    _t("OSM", "Ósmosis y dispensadores de agua",
       "Cerrar la alimentación y despresurizar antes de abrir los portafiltros. Cambiar el prefiltro de "
       "sedimentos y el filtro de carbón activado en cada servicio. Revisar la membrana y medir la "
       "calidad del agua a la salida con el medidor de TDS; si la lectura sube por encima de ⟨confirmar "
       "umbral⟩, cambiar la membrana. Desinfectar el portafiltro y la tubería antes de rearmar. Purgar "
       "hasta que el agua salga clara y sin sabor a cloro. Verificar que no haya fuga en las conexiones "
       "y anotar la fecha del cambio en la etiqueta del equipo.",
       ["Prefiltro de sedimentos cambiado", "Filtro de carbón cambiado", "Membrana revisada y TDS medido",
        "Portafiltro desinfectado", "Sin fuga en conexiones", "Purgado y con sabor normal",
        "Etiqueta con la fecha del cambio actualizada"],
       ["Prefiltro de sedimentos · 2 pzas", "Filtro de carbón · 1 pza",
        "Membrana ⟨confirmar modelo: equipos de 100 GPD⟩", "Desinfectante", "Cinta teflón"],
       ["Llave de portafiltros", "Medidor de TDS", "Cubeta", "Franela"], "", True),
    _t("TRA", "Traspaletas",
       "Revisar el estado de las ruedas de carga y de dirección, y cambiar las que estén ovaladas o con "
       "el material desprendido. Verificar que la bomba hidráulica levante y sostenga la carga sin "
       "bajarse sola; si baja, revisar el nivel de aceite y el sello. Revisar que las horquillas no estén "
       "dobladas ni con grietas. Engrasar los puntos de articulación y el eje de dirección. Comprobar "
       "que la palanca opere en sus tres posiciones —subir, neutral y bajar— y que el freno de pie "
       "detenga.",
       ["Ruedas de carga y dirección en buen estado", "Levanta y sostiene sin bajarse sola",
        "Sin fuga de aceite hidráulico", "Horquillas rectas y sin grietas", "Articulaciones engrasadas",
        "Palanca opera en las tres posiciones"],
       ["Grasa multiusos", "Aceite hidráulico", "Ruedas de repuesto ⟨confirmar medida⟩"],
       ["Pistola de grasa", "Juego de llaves", "Llaves allen", "Gato de apoyo"], "", True),
    _t("CAR", "Carritos de carga",
       "Revisar ruedas y rodamientos y cambiar los que estén trabados o con juego. Verificar que la "
       "estructura no tenga dobleces, soldaduras abiertas ni tornillería floja. Revisar que las manijas "
       "estén firmes y sin filo. Limpiar y lubricar los rodamientos. Confirmar que el carrito rueda "
       "derecho y no se va de lado.",
       ["Ruedas y rodamientos giran libres", "Estructura sin dobleces ni soldaduras abiertas",
        "Tornillería apretada", "Manijas firmes y sin filo", "Rueda derecho"],
       ["Rodamientos", "Tornillería", "Lubricante"],
       ["Juego de llaves", "Desarmadores", "Martillo de goma"], "", True),
    _t("DIA", "Diablos de carga",
       "Revisar la presión y el estado de las llantas; si son neumáticas, inflarlas a ⟨confirmar "
       "presión⟩. Verificar que los rodamientos giren sin juego. Revisar la estructura y las soldaduras, "
       "especialmente la unión de la pisadera con el bastidor, que es donde fallan. Comprobar que la "
       "pisadera no esté doblada y que las agarraderas estén firmes.",
       ["Llantas con presión y sin desgaste", "Rodamientos sin juego",
        "Soldaduras íntegras, en especial la pisadera", "Pisadera recta", "Agarraderas firmes"],
       ["Llantas o cámaras de repuesto", "Tornillería"],
       ["Juego de llaves", "Bomba de aire", "Manómetro"], "", True),
    _t("JAR", "Jardinería",
       "Podar pasto, setos y ramas bajas, cuidando que ninguna rama toque cables eléctricos, cámaras, "
       "luminarias ni bardas perimetrales. Retirar hierba de registros, coladeras y juntas de piso. "
       "Revisar el sistema de riego si existe, y reparar fugas o aspersores tapados. Retirar el residuo "
       "el mismo día: acumulado atrae plaga y compromete la fumigación.",
       ["Pasto y setos podados", "Sin ramas sobre cables, cámaras o luminarias",
        "Registros y coladeras libres de hierba", "Riego sin fugas y aspersores destapados",
        "Residuo retirado el mismo día"],
       ["Bolsas para residuo · 10 pzas", "Combustible para la desbrozadora"],
       ["Desbrozadora", "Tijeras de poda", "Rastrillo", "Escoba", "Guantes y gafas"], "", True),
    _t("CIS", "Cisterna, aljibe o tinaco",
       "Aplicar el protocolo de supervisión. TRABAJO EN ESPACIO CONFINADO: nadie de GPA entra; la "
       "supervisión se hace desde afuera. Antes: programar el vaciado avisando a la sucursal (se queda "
       "sin agua varias horas) y verificar que el proveedor traiga procedimiento de espacio confinado y "
       "que su personal no entre solo ⟨confirmar si GPA exige permiso de trabajo escrito⟩. Durante: "
       "verificar que se lave piso, muros y tapa, no solo el fondo, y que la desinfección se haga con el "
       "producto y el tiempo de contacto correctos. Después: tapa sellada y con candado, flotador "
       "cerrando bien, y conservar la constancia de limpieza y desinfección con fecha.",
       ["Vaciado y lavado de piso, muros y tapa", "Desinfección con tiempo de contacto respetado",
        "Flotador cerrando correctamente", "Tapa sellada y con candado",
        "Sin fuga en la tubería de alimentación", "Constancia de limpieza y desinfección recibida"],
       [], [],
       "Lo ejecuta el proveedor y GPA lo supervisa desde afuera: es espacio confinado y nadie de GPA "
       "entra. Verifica lavado de piso, muros y tapa, y recibe la constancia de limpieza y desinfección.",
       True),
    _t("ALA", "Alarma",
       "Avisar a la central de monitoreo antes de empezar, para que las señales de prueba no se tomen "
       "como evento real. Probar cada sensor recorriendo su zona y confirmar que el panel lo registre. "
       "Probar la sirena y verificar que se escuche en todo el inmueble. Revisar la batería de respaldo "
       "y cambiarla si tiene más de ⟨confirmar vida útil⟩ o si no sostiene la prueba de corte de "
       "energía. Confirmar con la central que las señales llegaron. Dar de baja los códigos de usuario "
       "de personal que ya no trabaja en GPA.",
       ["Central de monitoreo avisada antes y después", "Cada sensor probado y registrado en el panel",
        "Sirena audible en todo el inmueble", "Batería de respaldo probada con corte de energía",
        "Señales confirmadas por la central", "Códigos de usuario depurados"],
       ["Batería de respaldo ⟨confirmar tipo⟩"],
       ["Desarmadores", "Multímetro", "Escalera"], "", True),
    _t("PLZ", "Plantas de luz",
       "Revisar nivel y estado del aceite, del refrigerante y del combustible, y que el combustible no "
       "esté contaminado ni con más de ⟨confirmar tiempo⟩ de almacenado. Revisar la batería de arranque "
       "y sus bornes. Limpiar o cambiar el filtro de aire. ARRANCAR la planta y probarla con carga real, "
       "no solo en vacío, durante ⟨confirmar minutos⟩, y verificar que la transferencia opere. Revisar "
       "que no haya fuga de aceite ni de combustible y que el escape esté libre y al exterior. Anotar las "
       "horas del horómetro. Si no arranca o no sostiene carga es un correctivo inmediato: es equipo de "
       "emergencia.",
       ["Aceite, refrigerante y combustible en nivel", "Batería y bornes en buen estado",
        "Filtro de aire limpio o cambiado", "Arranca y sostiene carga real", "Transferencia opera",
        "Sin fuga de aceite ni combustible", "Escape libre y al exterior", "Horómetro anotado"],
       ["Aceite", "Filtro de aire · 1 pza", "Filtro de combustible · 1 pza", "Refrigerante",
        "Batería si aplica"],
       ["Juego de llaves", "Multímetro", "Embudo", "Recipiente para aceite usado"], "", True),
    _t("VEN", "Extractores y ventilación",
       "Aplicar el protocolo de supervisión. Cortar y bloquear la energía antes de cualquier trabajo. El "
       "servicio consiste en desmontar y lavar hélices y carcasa, retirando polvo y grasa que "
       "desbalancean el equipo; cambiar o tensar las bandas; engrasar o cambiar los baleros del motor; "
       "limpiar y reapretar las conexiones eléctricas; y medir el amperaje del motor en operación para "
       "compararlo con el de placa ⟨confirmar tolerancia aceptable⟩. Si vibra después del servicio, "
       "exigir balanceo. Pintura anticorrosiva donde la carcasa lo requiera. Probar en operación antes "
       "de aceptar. (La revisión mensual de condición GRL-SH-FO-3 es otro instrumento y no forma parte "
       "de esta actividad.)",
       ["Energía cortada y bloqueada durante el trabajo", "Hélices y carcasa desmontadas y lavadas",
        "Bandas cambiadas o tensadas", "Baleros engrasados o cambiados",
        "Conexiones eléctricas limpias y reapretadas", "Amperaje medido y dentro de lo esperado",
        "Sin vibración ni ruido anormal al probarlo", "Libre paso del aire confirmado"],
       [], ["Confirmación de bloqueo de energía"],
       "Lo ejecuta el proveedor y GPA lo supervisa. Verifica que la energía quede bloqueada, que se "
       "laven hélices y carcasa, que se cambien o tensen bandas y se engrasen baleros, y que no vibre "
       "al probarlo.", True),
    _t("BAS", "Básculas",
       "Aplicar el protocolo de supervisión. Verificar que el proveedor realice el contraste con pesas "
       "patrón certificadas y muestre el certificado de calibración de sus pesas. Revisar la nivelación "
       "de la plataforma antes del contraste: desnivelada da error aunque esté bien calibrada. Verificar "
       "el cero y la repetibilidad en tres puntos de la escala ⟨confirmar cuáles exige GPA⟩. Conservar "
       "el certificado de calibración con su vigencia: es el documento que se presenta a un cliente o a "
       "una autoridad.",
       ["Plataforma nivelada y limpia", "Cero correcto", "Contraste con pesas patrón certificadas",
        "Repetibilidad verificada", "Certificado de calibración recibido y vigente"],
       [], ["Nivel de burbuja (verificar antes de que llegue el proveedor)"],
       "Lo ejecuta el proveedor y GPA lo supervisa. Verifica la nivelación antes del contraste, que las "
       "pesas patrón estén certificadas, y recibe el certificado de calibración vigente.", True),
    _t("EXT", "Extintores",
       "REVISIÓN del extintor por personal de GPA (la recarga la ejecuta el proveedor certificado y NO "
       "es esta actividad). Recorrer cada extintor de la sucursal contra el plano de ubicación: que esté "
       "en su lugar, accesible y señalizado; manómetro en zona verde; sello y pasador intactos; etiqueta "
       "legible con fecha de recarga vigente; manguera y boquilla sin obstrucción ni grietas; cilindro "
       "sin corrosión ni golpes; colgado a la altura correcta. Un extintor con presión baja, sello roto "
       "o recarga vencida se etiqueta fuera de servicio, se coloca sustituto y se solicita al proveedor. "
       "Actualizar el inventario con las fechas de vencimiento.",
       ["En su lugar, accesible y señalizado", "Manómetro en zona verde", "Sello y pasador intactos",
        "Etiqueta legible con fecha de recarga vigente", "Manguera y boquilla sin obstrucción ni grietas",
        "Cilindro sin corrosión ni golpes", "Todos los extintores de la sucursal revisados",
        "Inventario de vencimientos actualizado"],
       ["Etiquetas de fuera de servicio · 3 pzas", "Extintores sustitutos si aplica"],
       ["Plano de ubicación", "Inventario con fechas de vencimiento", "Franela"], "", True),
]

assert len(TIPOS) == 23, len(TIPOS)
assert len({t["pref"] for t in TIPOS}) == 23
