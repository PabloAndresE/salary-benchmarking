@echo off
REM Corre el universo en local, desacoplado de cualquier sesion interactiva.
REM
REM Se lanza como tarea programada de Windows (ver infra/README o el comando schtasks
REM mas abajo) porque un proceso lanzado desde un shell hijo muere cuando ese shell se
REM reinicia: la corrida se caia sola cada vez que se reiniciaba la sesion del agente.
REM
REM El salt se lee de Secret Manager en cada arranque; nunca se persiste en disco.
REM La corrida es reanudable: el estado es la tabla destino, asi que relanzarla continua
REM donde quedo.
REM
REM   schtasks /create /tn benchmarking-universo /tr "<ruta>\correr_universo_local.cmd" /sc once /st 00:00 /f
REM   schtasks /run    /tn benchmarking-universo
REM   schtasks /end    /tn benchmarking-universo     (para pararla)

cd /d "%~dp0.."

for /f "delims=" %%s in ('gcloud secrets versions access latest --secret^=benchmarking-pipeline-salt --project^=act-cicd-stage-prueba') do set PIPELINE_SALT=%%s
if "%PIPELINE_SALT%"=="" (
  echo [correr_universo] ERROR: no se pudo leer el salt de Secret Manager >> corrida_universo.err.log
  exit /b 1
)

set PYTHONPATH=src
echo [correr_universo] arranque %DATE% %TIME% >> corrida_universo.log
.venv\Scripts\python.exe -u -m benchmarking.cli construir-universo --batch-size=100 >> corrida_universo.log 2>> corrida_universo.err.log
echo [correr_universo] fin %DATE% %TIME% (codigo %ERRORLEVEL%) >> corrida_universo.log
