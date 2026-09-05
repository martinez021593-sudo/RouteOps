@echo off
setlocal
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Solicitando permisos de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo Configurando Windows Firewall SOLO para perfil PRIVADO...
netsh advfirewall firewall delete rule name="RouteOps LAN Setup 5000" >nul 2>&1
netsh advfirewall firewall delete rule name="RouteOps LAN HTTPS 5443" >nul 2>&1
netsh advfirewall firewall add rule name="RouteOps LAN Setup 5000" dir=in action=allow protocol=TCP localport=5000 profile=private
netsh advfirewall firewall add rule name="RouteOps LAN HTTPS 5443" dir=in action=allow protocol=TCP localport=5443 profile=private
echo.
echo Reglas creadas. No se han abierto puertos en el router.
pause
endlocal
