@echo off
chcp 65001 >nul
title Decorer - Base de datos
cd /d "%~dp0"
echo ========================================================
echo      DECORER  -  CREAR LA BASE DE DATOS (PostgreSQL)
echo ========================================================
echo.
echo Usa el mismo contenedor "pgvector" de Archivo Vivo.
echo ATENCION: borra la base "decorer" (si existe) y la crea de nuevo
echo con el inventario de SysCafe. La base "chatpdf" no se toca.
echo.
set /p OK="Continuar? (S/N): "
if /i not "%OK%"=="S" exit /b 0

rem -- Python -------------------------------------------------
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py"
if not defined PY_CMD ( where python >nul 2>&1 && set "PY_CMD=python" )
if not defined PY_CMD ( echo [ERROR] No se encontro Python. & pause & exit /b 1 )

rem -- 1. Docker y contenedor ---------------------------------
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop esta cerrado. Abrelo, espera "Engine running" y vuelve a ejecutar.
    pause & exit /b 1
)
docker start pgvector >nul 2>&1
if errorlevel 1 (
    echo        Creando el contenedor pgvector por primera vez...
    docker run -d --name pgvector --restart unless-stopped -e POSTGRES_PASSWORD=postgres -p 5432:5432 -v pgvector_data:/var/lib/postgresql/data pgvector/pgvector:pg17
)
set /a TRIES=0
:esperar_pg
docker exec pgvector pg_isready -U postgres >nul 2>&1
if not errorlevel 1 goto pg_listo
set /a TRIES+=1
if %TRIES% geq 30 ( echo [ERROR] PostgreSQL no arranco. & pause & exit /b 1 )
timeout /t 2 /nobreak >nul
goto esperar_pg
:pg_listo
echo [1/6] PostgreSQL listo.

rem -- 2. Base y scripts --------------------------------------
docker exec pgvector psql -U postgres -q -c "DROP DATABASE IF EXISTS decorer WITH (FORCE);"
docker exec pgvector psql -U postgres -q -c "CREATE DATABASE decorer;"
echo [2/6] Creando tablas, funciones y permisos...
for %%F in (01_esquema.sql 02_parametros_decorer.sql 03_conocimiento_pgvector.sql 04_reportes_y_seguridad.sql) do (
    echo        - %%F
    docker exec -i -e PGCLIENTENCODING=UTF8 pgvector psql -U postgres -d decorer -q -v ON_ERROR_STOP=1 < "database\%%F"
    if errorlevel 1 ( echo [ERROR] Fallo %%F & pause & exit /b 1 )
)

rem -- 3. Dependencias ----------------------------------------
echo [3/6] Instalando dependencias de Python...
%PY_CMD% -m pip install -r requirements.txt -q --disable-pip-version-check

rem -- 4. Inventario de SysCafe -------------------------------
echo [4/6] Cargando el inventario de SysCafe...
rem Si dejas PDFs nuevos de SysCafe en importar\ (nombre con INVENTARIO o con PRECIO), se leen primero.
for %%P in (importar\*INVENTARIO*.pdf) do (
    echo        Leyendo inventario %%~nxP ...
    %PY_CMD% importar\leer_syscafe.py "%%P" importar\syscafe_articulos.csv
)
for %%P in (importar\*PRECIO*.pdf) do (
    echo        Leyendo lista de precios %%~nxP ...
    %PY_CMD% importar\leer_precios_syscafe.py "%%P" importar\syscafe_precios.csv
)
%PY_CMD% importar\cargar_inventario.py
if errorlevel 1 ( echo [ERROR] No se pudo cargar el inventario. & pause & exit /b 1 )

rem -- 5. Conocimiento a pgvector (EmbeddingGemma 2 en llama.cpp) ---
echo [5/6] Indexando politicas y preguntas frecuentes en pgvector...
curl -s http://127.0.0.1:8081/health >nul 2>&1
if not errorlevel 1 goto llama_listo
where llama-server >nul 2>&1
if errorlevel 1 goto sin_llama
start "llama.cpp - EmbeddingGemma 2" /min llama-server -hf unsloth/embeddinggemma-2-GGUF:UD-Q4_K_XL --embeddings --port 8081 -c 2048 -b 2048 -ub 2048 --device none -ngl 0
echo        Encendiendo llama.cpp (la primera vez descarga el modelo, unos 200 MB)...
set /a TRIES=0
:esperar_llama
curl -s http://127.0.0.1:8081/health >nul 2>&1
if not errorlevel 1 goto llama_listo
set /a TRIES+=1
if %TRIES% geq 150 goto llama_tarde
timeout /t 2 /nobreak >nul
goto esperar_llama
:sin_llama
echo [AVISO] No esta llama.cpp. Instalalo con: winget install --id ggml.llamacpp --exact --source winget
echo         y luego corre: %PY_CMD% conocimiento\indexar_conocimiento.py
goto pruebas
:llama_tarde
echo [AVISO] llama.cpp no respondio a tiempo. Cuando abra, corre: %PY_CMD% conocimiento\indexar_conocimiento.py
goto pruebas
:llama_listo
%PY_CMD% conocimiento\indexar_conocimiento.py
%PY_CMD% conocimiento\indexar_conocimiento.py --buscar "lo puedo pagar por cuotas"

:pruebas
rem -- 6. Pruebas ---------------------------------------------
echo.
echo [6/6] Pruebas de transacciones y seguridad:
%PY_CMD% pruebas\prueba_transacciones.py
echo.
pause
