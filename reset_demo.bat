@echo off
setlocal
cd /d "%~dp0"
echo Esto borrara la base local de RouteOps V0.3.
choice /M "Continuar"
if errorlevel 2 exit /b
if exist routeops_v03.db del routeops_v03.db
echo Base eliminada. Ejecuta run_routeops.bat para recrearla.
pause
endlocal
