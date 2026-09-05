@echo off
setlocal
cd /d "%~dp0"
if not exist "certs\routeops-lan-ca.crt" (
  echo Primero ejecuta RouteOps LAN al menos una vez para generar el certificado.
  pause
  exit /b 1
)
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
certutil -addstore -f Root "certs\routeops-lan-ca.crt"
echo.
echo Certificado RouteOps LAN CA instalado en Windows.
pause
endlocal
