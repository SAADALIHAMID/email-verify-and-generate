@echo off
REM ============================================
REM   EMAIL VERIFIER - AUTO STARTUP
REM ============================================

:: Set Project Path
set PROJECT_PATH=D:\email verify

:: Change to main project folder
cd /d "%PROJECT_PATH%"

echo.
echo ============================================
echo   EMAIL VERIFIER STARTUP
echo ============================================
echo.
echo [1/2] Starting FastAPI Backend...
echo       Port: 8000
echo       Folder: %PROJECT_PATH%
echo.

REM Start FastAPI in new terminal window
start "FASTAPI-BACKEND (Port 8000)" cmd /k "cd /d "%PROJECT_PATH%" && python -m uvicorn app.api:app --reload --host 0.0.0.0 --port 8000"

REM Wait for API to start
timeout /t 3 /nobreak

echo [2/2] Starting Streamlit Dashboard...
echo       URL: http://localhost:8501
echo       Folder: %PROJECT_PATH%
echo.

REM Start Streamlit in new terminal window
start "STREAMLIT-DASHBOARD (localhost:8501)" cmd /k "cd /d "%PROJECT_PATH%" && streamlit run streamlit_app_improved.py"

echo.
echo ============================================
echo   BOTH SERVICES STARTED!
echo ============================================
echo.
echo FastAPI:  http://localhost:8000
echo Streamlit: http://localhost:8501
echo.
echo Press any key to close this window...
echo ============================================
pause >nul
exit