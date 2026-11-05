@echo off
chcp 65001 >nul
title Decorer - Backend del agente
cd /d "%~dp0backend"
echo ========================================================
echo        DECORER  -  BACKEND DEL AGENTE (FastAPI)
echo ========================================================
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py"
if not defined PY_CMD ( where python >nul 2>&1 && set "PY_CMD=python" )
if not defined PY_CMD ( echo [ERROR] No se encontro Python. & pause & exit /b 1 )

docker start pgvector >nul 2>&1
if not exist ".env" copy ".env.example" ".env" >nul
echo [1/3] Instalando dependencias...
%PY_CMD% -m pip install -r requirements.txt -q --disable-pip-version-check

echo        Voz de Deco (Piper, es_MX-claude-high: la primera vez se descarga, tarda un poco)...
if not exist "voz_modelos\es_MX-claude-high.onnx" %PY_CMD% -m piper.download_voices es_MX-claude-high --download-dir voz_modelos
echo        (El oido, faster-whisper "small", se descarga solo la primera vez que hable por el microfono.)

echo        Para leer facturas por foto: abra Ollama (ollama pull qwen2.5vl:3b la primera vez).

echo [2/3] llama.cpp (EmbeddingGemma 2) para buscar en las politicas...
curl -s http://127.0.0.1:8081/health >nul 2>&1
if not errorlevel 1 goto llama_ok
where llama-server >nul 2>&1
if errorlevel 1 ( echo        No esta llama.cpp: el agente usara la busqueda de texto de respaldo. & goto servidor )
start "llama.cpp - EmbeddingGemma 2" /min llama-server -hf unsloth/embeddinggemma-2-GGUF:UD-Q4_K_XL --embeddings --port 8081 -c 2048 -b 2048 -ub 2048 --device none -ngl 0
echo        Encendido en una ventana minimizada.
:llama_ok

:servidor
echo [3/3] Inicio: http://localhost:8010  · Chat: http://localhost:8010/chat  · API: http://localhost:8010/docs
echo        Panel del duenio: http://localhost:8010/dueno   (clave: decorer2026, se cambia en backend\.env)
echo        Para hablar con Deco en la consola, abre otra ventana y corre:
echo        cd backend  y luego  %PY_CMD% chat_consola.py
echo.
start "" /min cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8010"
%PY_CMD% -m uvicorn main:app --reload --host 0.0.0.0 --port 8010
pause
