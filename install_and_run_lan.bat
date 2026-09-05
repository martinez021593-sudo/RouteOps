@echo off
setlocal
cd /d "%~dp0"
echo.
echo ===============================================
echo   RouteOps V0.3 - Smart Dispatch LAN
echo ===============================================
echo.
where py >nul 2>&1
if %errorlevel%==0 (set PY=py) else (set PY=python)
if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual...
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR instalando dependencias.
  pause
  exit /b 1
)
echo.
echo Si Windows Firewall pregunta, permite acceso solo en redes PRIVADAS.
start "" http://127.0.0.1:5000
python lan_server.py
endlocal
