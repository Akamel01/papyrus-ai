@echo off
echo Starting SME Research Assistant...

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Docker Desktop is not running.
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo Building and Starting Containers...
docker-compose up -d --build

echo.
echo ========================================================
echo System is starting up!
echo --------------------------------------------------------
echo Web UI:    http://localhost:8502
echo Qdrant:    http://localhost:6333
echo Redis:     localhost:6379
echo Ollama:    http://localhost:11434
echo ========================================================
echo.
echo Use 'docker-compose logs -f app' to view application logs.
pause
