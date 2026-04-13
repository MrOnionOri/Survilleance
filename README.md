# StreamWatch AI

MVP para monitoreo inteligente de streaming y publicidad. Incluye:

- Backend FastAPI con JWT, RBAC, camaras, eventos, labels y modelos.
- Motor hibrido inicial con detectores por reglas para pantalla negra, freeze y cambio de escena.
- Worker preparado para procesar streams con OpenCV.
- Dashboard Svelte para visualizar camaras, editar video, etiquetar evidencia y gestionar permisos por rol.
- Docker Compose con backend, frontend, worker y PostgreSQL.

## Estructura

```text
backend/       API FastAPI
frontend-svelte/ Dashboard Svelte
worker/        Procesamiento de video y reglas MVP
recordings/    Chunks por camara
events/        Evidencia generada
dataset/       Etiquetas para entrenamiento
models/        Modelos versionados
```

## Arranque rapido

```bash
docker compose up --build db backend frontend
```

Servicios:

- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs
- Frontend Svelte: http://localhost:5173
- PostgreSQL: localhost:5432

Usuario inicial por defecto:

- Email: `admin@streamwatch.example.com`
- Password: `admin123`

Configurable con variables de entorno en `docker-compose.yml`.

## Desarrollo local backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Revision manual de video

El flujo recomendado es crear una **prueba de monitoreo** antes de revisar:

1. Ir a **Pruebas**
2. Capturar nombre, descripcion, duracion, segundos por chunk y camaras participantes
3. Iniciar prueba
4. Abrir el **Editor de monitoreo**

El worker guarda chunks MP4 continuamente mientras la camara este activa. La deteccion de errores no controla la grabacion; solo genera eventos y evidencias encima del historial continuo. Si una camara participa en una prueba activa, el worker usa el `chunk_seconds` de esa prueba.

Los chunks se guardan en:

```text
recordings/test_<test_id>/cam_<camera_id>/YYYY-MM-DD/HH-MM-SS.mp4
```

El dashboard solo carga los chunks de la prueba seleccionada. Esto evita mezclar grabaciones de diferentes estudios o momentos. El editor muestra esos chunks como una sola linea de tiempo virtual en **Editor de monitoreo**. Desde ahi puedes:

- reproducir el historial por camara
- seleccionar inicio y fin con controles de rango
- asignar el tipo de error
- guardar el rango como evento manual y label para entrenamiento
- cambiar la camara principal dentro de una prueba multi-camara

Nota: el chunk actual termina de ser reproducible cuando FFmpeg lo cierra al rotar. Con `CHUNK_SECONDS=60`, un video nuevo puede tardar hasta 60 segundos en aparecer completo en el editor.

## Video en vivo

El vivo del mosaico no abre la camara desde Chrome. El worker captura la camara una sola vez y manda frames JPEG al backend por WebSocket:

```text
worker -> ws://backend/ws/cameras/<id>/stream -> frontend
```

Esto evita conflictos como `Device in use`, porque Chrome ya no compite por la webcam. El boton **Ver en vivo** del mosaico se conecta al stream del worker.

## Permisos en frontend

La API aplica RBAC real y el frontend Svelte oculta opciones segun rol:

| Rol | Camaras | Editor / Etiquetado | Entrenamiento | Sistema |
| --- | --- | --- | --- | --- |
| Admin | Si | Si | Si | Si |
| Supervisor | Si | Si | Si | No |
| Analista | Si | Si | No | No |
| Viewer | Si | No | No | No |

Si ejecutas el worker fuera de Docker para usar webcam local en Windows, apunta el directorio de datos a la raiz del proyecto:

```powershell
$env:STREAMWATCH_DATA_DIR="d:\dev\Projectos Mixtos\Survilleance"
```

## Worker y camaras locales

El sistema soporta fuentes locales y online al mismo tiempo usando dos workers con filtros:

- Worker Docker: procesa fuentes online/network, como `rtsp://...`, `http://...`.
- Worker local Windows: procesa webcams locales, como `0`, `1`, `2`.

El servicio `worker` esta en un perfil opcional de Docker y tiene `WORKER_SOURCE_SCOPE=network`, asi evita intentar abrir webcams locales desde Linux. Para camaras RTSP o fuentes visibles desde Docker:

```bash
docker compose --profile worker up --build
```

Para webcam local en Windows, ejecuta solo `db backend frontend` en Docker:

```powershell
docker compose up --build db backend frontend
```

Luego corre el worker local desde PowerShell. Si no tienes `.venv`, el script lo crea:

```powershell
cd "d:\dev\Projectos Mixtos\Survilleance"
.\scripts\run-local-worker.ps1
```

Si quieres instalar dependencias antes:

```powershell
.\scripts\setup-local-worker.ps1
```

Para encontrar el indice correcto de la webcam y descartar camaras negras:

```powershell
.\scripts\probe-local-cameras.ps1
```

El script guarda imagenes en:

```text
worker/camera_probe/camera_0.jpg
worker/camera_probe/camera_1.jpg
```

Usa como fuente el indice cuya imagen se vea bien y tenga `mean_intensity` razonable. Si una camara sale negra, prueba otra app cerrada, permisos de Windows, otro indice o espera unos segundos por auto-exposicion.

En el dashboard puedes registrar ambos tipos:

```text
Camara laptop -> 0
Camara USB -> 1
Camara IP -> rtsp://usuario:password@192.168.1.50:554/stream1
Stream online -> http://servidor/video.mp4
```

## Variables principales

| Variable | Descripcion | Default |
| --- | --- | --- |
| `DATABASE_URL` | URL SQLAlchemy | `sqlite:///./streamwatch.db` |
| `JWT_SECRET` | Secreto JWT | `change-me` |
| `ADMIN_EMAIL` | Usuario inicial | `admin@streamwatch.local` |
| `ADMIN_PASSWORD` | Password inicial | `admin123` |
| `STREAMWATCH_DATA_DIR` | Directorio de evidencia | `./data` |

## Roadmap implementado

Este repo deja lista la Fase 1 y una base funcional de Fase 2:

- Captura y reglas: modulo `worker/app/detectors.py`
- Eventos y dashboard: API + frontend
- Dataset y etiquetado: endpoint de labels y estructura `dataset/`
- Entrenamiento IA: endpoints y tabla de modelos preparados para integrar pipelines
