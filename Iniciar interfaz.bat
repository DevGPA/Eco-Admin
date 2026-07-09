@echo off
REM ================================================================
REM  Inicia la interfaz web local de Facturas PDF (GPA).
REM  Doble clic para arrancar. Se abre solo en el navegador.
REM  NO cierres esta ventana negra mientras uses la interfaz.
REM ================================================================
title Facturas PDF - GPA (no cerrar mientras se usa)
cd /d "%~dp0"

echo Iniciando interfaz... espera a que diga "Abre en tu navegador".
echo.

REM Preferir el lanzador oficial de Python (py). Si no existe, usar python.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 app.py
) else (
    python app.py
)

echo.
echo ------------------------------------------------------------
echo La interfaz se detuvo o hubo un error al iniciar.
echo Si ves un mensaje de error arriba, toma captura y compartelo.
echo ------------------------------------------------------------
pause
