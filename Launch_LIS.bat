@echo off
title LIS Command Center
color 0B
echo.
echo ========================================================
echo                 BOOTING LIS NEURAL CORE
echo ========================================================
echo.

echo [1/3] Starting Python Backend Swarm...
start /min cmd /c "title LIS Backend && python server.py"

echo [2/3] Starting Vite Frontend Server...
cd frontend
start /min cmd /c "title LIS Frontend && npm run dev"
cd ..

echo [3/3] Waiting for systems to synchronize...
timeout /t 3 /nobreak >nul

echo.
echo Launching Web Interface in Microsoft Edge...
start msedge http://localhost:5173 --app=http://localhost:5173

exit
