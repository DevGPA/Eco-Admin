# tools/probar_textract.ps1
# Asistente para probar el OCR (Textract) sobre un PDF real, en Windows.
# Te pide tus claves AWS (NO se guardan) y la ruta del PDF, y corre el motor.
#
# Uso:
#   .\tools\probar_textract.ps1
#   .\tools\probar_textract.ps1 "C:\ruta\al\documento.pdf"
param([string]$Pdf)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

# Localizar Python 3.12
$py = "C:\Users\Gerencia-\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Host "No encontre Python. Instala Python 3.12." -ForegroundColor Red; exit 1 }

# Credenciales AWS (solo para esta sesion; no se guardan en disco)
if (-not $env:AWS_ACCESS_KEY_ID) {
    Write-Host "`n--- Credenciales AWS (con permiso textract:AnalyzeDocument) ---" -ForegroundColor Cyan
    $env:AWS_ACCESS_KEY_ID = Read-Host "AWS Access Key ID"
    $sec = Read-Host "AWS Secret Access Key" -AsSecureString
    $env:AWS_SECRET_ACCESS_KEY = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
if (-not $env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION = "us-east-1" }

# Ruta del PDF
if (-not $Pdf) { $Pdf = Read-Host "`nRuta del PDF a probar" }
$Pdf = $Pdf.Trim('"')

# Asegurar dependencias
& $py -m pip install --quiet --disable-pip-version-check boto3 pymupdf

# Correr el diagnostico
& $py "$PSScriptRoot\probar_textract.py" "$Pdf"
