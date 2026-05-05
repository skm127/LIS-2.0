@echo off
title LIS Command Center
color 0B
echo ======================================================
echo    LIS - Personal AI Assistant - Initializing
echo ======================================================
echo.

echo [1/3] Building frontend assets...
cd frontend && call npm run build >nul 2>&1 && cd ..

echo [2/3] Starting LIS Server...
start "" /min cmd /c "python server.py --port 8340 || pause"

echo [3/3] Opening LIS Interface...
echo Waiting 4 seconds for server warmup...
timeout /t 4 /nobreak > nul
start msedge --app="http://localhost:8340"

echo.
echo ======================================================
echo    LIS is now online.
echo    You can close this window safely.
echo ======================================================
timeout /t 2 > nul
exit
