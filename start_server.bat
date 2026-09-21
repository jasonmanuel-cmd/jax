@echo off
REM JAX local dev launcher. Secrets are loaded from .env (never hardcode them here).
REM Copy .env.example to .env and fill in real values first.
cd /d "%~dp0"

if not exist ".env" (
  echo ERROR: .env not found. Copy .env.example to .env and fill in your values.
  exit /b 1
)

REM Load KEY=VALUE lines from .env into the environment
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  if not "%%A"=="" set "%%A=%%B"
)

.venv\Scripts\python.exe -m uvicorn core.app.main:create_app --factory --host 127.0.0.1 --port 8788
