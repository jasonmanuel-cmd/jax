@echo off
REM JAX local dev launcher. Secrets are loaded from .env (never hardcode them here).
REM Copy .env.example to .env and fill in real values first.
cd /d "%~dp0"

if not exist ".env" (
  echo ERROR: .env not found. Copy .env.example to .env and fill in your values.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found. Create it first:  python -m venv .venv
  echo        then:  .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

REM start_server.py loads .env with python-dotenv, the same loader the app
REM uses. Parsing .env in batch would silently mishandle quotes and spaces.
.venv\Scripts\python.exe start_server.py
