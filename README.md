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

En LAN, otros equipos deben entrar usando la IP del equipo donde corre Docker:

- Frontend: http://192.168.1.150:5173
- API docs: http://192.168.1.150:8000/docs

El frontend detecta el host desde la URL, asi que al abrir `http://192.168.1.150:5173` consultara automaticamente al backend en `http://192.168.1.150:8000`. Si Windows pregunta por firewall, permite conexiones privadas para los puertos `5173` y `8000`.

Usuario inicial por defecto:

- Email: `admin@streamwatch.example.com`
- Password: `admin123`

Configurable con variables de entorno en `docker-compose.yml`.

## Rama local sin Docker + MySQL

Esta rama `no-docker-mysql` permite correr la plataforma sin Docker ni WSL.

Requisitos en Windows:

- Python 3.12+
- Node.js 22+
- MySQL Server 8+
- Git

Crear base de datos y usuario:

```powershell
mysql -u root -p < scripts/mysql-init.sql
```

La URL por defecto para esta rama es:

```text
mysql+pymysql://streamwatch:streamwatch@localhost:3306/streamwatch?charset=utf8mb4
```

Puedes cambiarla con la variable `DATABASE_URL` o copiando:

```powershell
copy backend\.env.mysql.example backend\.env
```

Arrancar backend local:

```powershell
.\scripts\run-local-backend-mysql.ps1
```

Arrancar frontend local:

```powershell
.\scripts\run-local-frontend.ps1
```

Arrancar worker local para webcams/camaras conectadas a la computadora:

```powershell
.\scripts\run-local-worker.ps1
```

URLs:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs

Notas:

- El backend crea las tablas automaticamente al iniciar.
- MySQL reemplaza a PostgreSQL en esta rama.
- El worker local no usa Docker y puede abrir camaras fisicas de Windows.
- Para camaras IP/RTSP tambien puedes registrarlas desde **Fuentes**.

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

## Secciones administrativas

- **Fuentes**: altas dinamicas de camaras, fuentes RTSP/locales, estado y recalibracion de ROI.
- **Usuarios**: altas de usuarios y asignacion de roles.
- **Sistema**: categorias IA y acciones de entrenamiento.
- **IA Lab**: videos/chunks, eventos, etiquetas, entrenamiento y seleccion de modelos activos.
- **Campo de pruebas**: vivo de camara con overlay de detecciones recientes y modelo activo.

## IA Lab y modelos

La seccion **IA Lab** concentra todo lo relacionado con datos y deep learning:

- resumen de videos/chunks, eventos y etiquetas
- distribucion de etiquetas por categoria
- constructor visual de dataset con tarjetas de evidencia
- guardado de datasets versionados
- entrenamiento de modelos por proposito
- registro de artefactos externos
- seleccion del modelo activo para cada uso

Los propositos iniciales son:

- `event_classifier`
- `ad_fingerprint`
- `roi_detector`
- `quality_detector`

Al entrenar desde la plataforma, el backend genera una version con esta forma:

```text
<purpose>_e<epochs>_<yyyymmdd>_<hhmmss>
```

Ejemplo:

```text
event_classifier_e0010_20260415_153000
```

Cada modelo guarda version, ruta del artefacto, epochs, accuracy, estado, resumen del dataset y si esta activo. Solo admin/supervisor pueden entrenar, registrar artefactos o activar un modelo; analistas pueden revisar datos y versiones.

En **Campo de pruebas** puedes seleccionar camara y proposito de modelo. La vista registra temporalmente esa camara para procesamiento en vivo, abre el vivo por WebSocket, consulta detecciones recientes del worker y dibuja el ROI/recuadro con el nombre detectado. Este modo no graba chunks si la camara no esta dentro de una prueba formal. Hoy usa las detecciones existentes; al conectar inferencia real, el mismo panel puede mostrar predicciones del modelo activo.

El flujo visual recomendado es:

1. Revisar eventos en **IA Lab > Constructor visual de dataset**
2. Buscar por camara, categoria o id en la lista izquierda
3. Revisar la evidencia grande al centro con el ROI usado en la deteccion
4. Agregar o quitar la evidencia del dataset
4. Guardar un dataset con nombre y notas
5. Entrenar usando ese dataset desde **Nuevo entrenamiento**

Tambien puedes reutilizar datasets guardados:

- **Cargar al constructor**: reemplaza la seleccion actual con las evidencias de ese dataset y guarda el nuevo dataset como derivado.
- **Combinar**: agrega las evidencias de ese dataset a la seleccion actual.

## Region de pantalla y categorias

Los detectores no tienen que analizar toda la camara. Cada camara puede tener una ROI de pantalla en coordenadas normalizadas:

- `roi_x`
- `roi_y`
- `roi_width`
- `roi_height`

Los valores van de `0` a `1`. Por ejemplo, si la pantalla ocupa casi todo el centro de la imagen, una ROI aproximada podria ser `x=0.10`, `y=0.12`, `width=0.80`, `height=0.72`. Si la ROI queda vacia, se analiza todo el frame.

Las detecciones de `black_screen`, `freeze` y `scene_change` se calculan sobre esa zona de contenido, no sobre toda la camara. Esto permite apuntar una webcam a una TV o monitor y detectar sucesos dentro de la reproduccion.

Desde **Fuentes > Fuentes registradas > Recalibrar ROI** puedes marcar el rectangulo visualmente sobre el ultimo snapshot de la camara. El boton **Sugerir pantalla** intenta proponer una ROI a partir del contenido visible; si no encuentra una zona confiable, usa un marco central que puedes ajustar arrastrando de nuevo.

Si una camara se mueve durante una prueba, se puede recalibrar la ROI sin desbloquear la camara. La fuente, el estado y el borrado siguen bloqueados mientras la prueba esta corriendo.

Las categorias de sucesos son editables desde **Sistema > Categorias IA**. Las categorias creadas ahi aparecen en el editor y en eventos para etiquetar rangos de video y alimentar el entrenamiento. La gestion de usuarios vive en la seccion **Usuarios**.

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

Salida esperada (ejemplo):

```text
camera_0=ok mean_intensity=126.31 snapshot=camera_probe/camera_0.jpg
camera_1=not_available
camera_2=ok mean_intensity=84.57 snapshot=camera_probe/camera_2.jpg
```

Interpretacion rapida:

- `camera_N=ok`: ese `N` es el numero que debes registrar en **Fuentes > Fuente** (por ejemplo `0` o `2`).
- `not_available`: no existe camara en ese indice.
- `no_frame`: la camara abre pero no entrego frame util; prueba cerrar apps que la esten usando y vuelve a ejecutar.
- `mean_intensity` muy bajo (cercano a `0`): imagen muy oscura/negra, prueba otro indice o espera unos segundos.

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
