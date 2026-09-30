# mantenimiento/ — Módulo «Plan Mtto» (plan y control de mantenimiento) de GPA Operaciones.
#
#   logica.py  reglas puras: semanas del plan, estatus derivado, asignación,
#              nivel de acceso, reinicio del reloj por correctivo, año siguiente.
#   datos.py   lectura/escritura en la tabla única (prefijos MP, MPC, CAT#ACTIVO…).
#   rutas.py   las rutas /mantenimiento/* que enruta handler.py.
#
# Todo es ADITIVO respecto al resto de la app: rutas nuevas, prefijos nuevos.
# El diseño vive en docs/mantenimiento/ (ESPECIFICACION.md manda).
