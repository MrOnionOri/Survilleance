const API_URL = "http://localhost:8000";
const state = {
  token: localStorage.getItem("streamwatch_token"),
  user: null,
  cameras: [],
  events: [],
  recordings: [],
  reviewCameraId: null,
};

const $ = (id) => document.getElementById(id);

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  setTimeout(() => node.classList.add("hidden"), 3200);
}

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail || "Error de API");
  }
  return response.json();
}

async function login(email, password) {
  const data = await request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  state.token = data.access_token;
  localStorage.setItem("streamwatch_token", state.token);
  await hydrate();
}

async function hydrate() {
  state.user = await request("/auth/me");
  state.cameras = await request("/cameras");
  state.events = await request(`/events${$("eventFilter").value ? `?type=${$("eventFilter").value}` : ""}`);
  if (!state.reviewCameraId && state.cameras[0]) state.reviewCameraId = state.cameras[0].id;
  await loadRecordings();
  render();
}

async function loadRecordings() {
  state.recordings = state.reviewCameraId ? await request(`/recordings?camera_id=${state.reviewCameraId}`) : [];
}

function render() {
  $("loginPanel").classList.add("hidden");
  $("appPanel").classList.remove("hidden");
  $("session").textContent = `${state.user.email} - ${state.user.role}`;
  $("cameraCount").textContent = state.cameras.length;
  $("eventCount").textContent = state.events.length;
  $("criticalCount").textContent = state.events.filter((event) => ["freeze", "black_screen", "repeated_ad"].includes(event.type)).length;
  renderCameraMosaic();
  renderCameraList();
  renderEvents();
  renderReview();
}

function renderCameraMosaic() {
  const node = $("cameraMosaic");
  node.innerHTML = state.cameras.length
    ? state.cameras.map(cameraTile).join("")
    : `<article class="camera-tile empty-tile"><strong>Sin camaras</strong><p>Agrega una camara desde Sistema.</p></article>`;

  document.querySelectorAll("[data-open-camera]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.reviewCameraId = Number(button.dataset.openCamera);
      switchView("editorView");
      await loadRecordings();
      renderReview();
    });
  });
}

function cameraTile(camera) {
  const snapshot = `${API_URL}/media/snapshots/cam_${camera.id}.jpg?ts=${Date.now()}`;
  return `
    <article class="camera-tile">
      <div class="thumb-wrap">
        <img src="${snapshot}" alt="${escapeHtml(camera.name)}" onerror="this.classList.add('missing')" />
        <div class="thumb-fallback">Sin señal</div>
      </div>
      <div class="tile-body">
        <strong>${escapeHtml(camera.name)}</strong>
        <p>${escapeHtml(camera.source)}</p>
        <div class="tile-actions">
          <span class="badge ${camera.enabled ? "" : "warn"}">${camera.enabled ? "Activa" : "Pausada"}</span>
          <button data-open-camera="${camera.id}" type="button">Editar video</button>
        </div>
      </div>
    </article>
  `;
}

function renderCameraList() {
  const cameras = $("cameras");
  cameras.innerHTML = state.cameras.length
    ? state.cameras
        .map(
          (camera) => `
            <article class="item">
              <strong>${escapeHtml(camera.name)}</strong>
              <p>${escapeHtml(camera.source)}</p>
              <span class="badge ${camera.enabled ? "" : "warn"}">${camera.enabled ? "Activa" : "Pausada"}</span>
            </article>
          `
        )
        .join("")
    : `<article class="item"><strong>Sin camaras</strong><p>Agrega una fuente para iniciar captura.</p></article>`;
}

function renderReview() {
  $("reviewCamera").innerHTML = state.cameras
    .map((camera) => `<option value="${camera.id}" ${camera.id === state.reviewCameraId ? "selected" : ""}>${escapeHtml(camera.name)}</option>`)
    .join("");

  const total = totalDuration();
  $("rangeStart").max = String(total);
  $("rangeEnd").max = String(total);
  if (Number($("rangeEnd").value) === 0 || Number($("rangeEnd").value) > total) $("rangeEnd").value = String(total);
  if (Number($("rangeStart").value) > total) $("rangeStart").value = "0";
  renderTimeline();
  updateSelectedRange();
  if (state.recordings.length && !$("reviewVideo").src) playVirtualSecond(0);
}

function renderTimeline() {
  const timeline = $("historyTimeline");
  if (!state.recordings.length) {
    timeline.innerHTML = `<div class="timeline-empty">No hay chunks grabados para esta camara.</div>`;
    $("reviewVideo").removeAttribute("src");
    $("reviewVideo").load();
    return;
  }

  timeline.innerHTML = state.recordings
    .map((chunk, index) => `<button type="button" class="chunk" data-chunk="${index}">${new Date(chunk.start_time).toLocaleTimeString()}</button>`)
    .join("");

  document.querySelectorAll("[data-chunk]").forEach((button) => {
    button.addEventListener("click", () => playChunk(Number(button.dataset.chunk), 0));
  });
}

function renderEvents() {
  const events = $("events");
  events.innerHTML = state.events.length
    ? state.events.map(eventTemplate).join("")
    : `<article class="event"><div><strong>Sin eventos</strong><p>Aun no hay evidencia registrada.</p></div></article>`;

  document.querySelectorAll("[data-label-event]").forEach((button) => {
    button.addEventListener("click", async () => {
      const eventId = Number(button.dataset.labelEvent);
      const select = document.querySelector(`[data-label-select="${eventId}"]`);
      await request("/events/label", { method: "POST", body: JSON.stringify({ event_id: eventId, label: select.value }) });
      toast("Etiqueta guardada");
    });
  });
}

function eventTemplate(event) {
  const critical = ["freeze", "black_screen", "repeated_ad"].includes(event.type);
  const warn = ["buffering", "scene_change"].includes(event.type);
  return `
    <article class="event">
      <div>
        <strong>${labelFor(event.type)} - Camara ${event.camera_id}</strong>
        <p>${new Date(event.timestamp).toLocaleString()} - Confianza ${(event.confidence * 100).toFixed(0)}%</p>
        ${event.image_path ? `<p>${escapeHtml(event.image_path)}</p>` : ""}
        <div class="label-row">
          <select data-label-select="${event.id}">
            ${eventTypes().map((type) => `<option value="${type}" ${type === event.type ? "selected" : ""}>${labelFor(type)}</option>`).join("")}
          </select>
          <button data-label-event="${event.id}" type="button">Etiquetar</button>
        </div>
      </div>
      <span class="badge ${critical ? "critical" : warn ? "warn" : ""}">${event.type}</span>
    </article>
  `;
}

function switchView(viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("hidden", view.id !== viewId));
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === viewId));
}

function playVirtualSecond(second) {
  const chunk = chunkAtSecond(second);
  if (chunk) playChunk(chunk.index, chunk.offset);
}

function playChunk(index, offset) {
  const chunk = state.recordings[index];
  if (!chunk) return;
  const video = $("reviewVideo");
  const absoluteUrl = `${API_URL}${chunk.url}`;
  if (video.src !== absoluteUrl) video.src = absoluteUrl;
  video.onloadedmetadata = () => {
    video.currentTime = Math.min(offset, Math.max(video.duration - 0.2, 0));
  };
  video.play().catch(() => {});
}

function chunkAtSecond(second) {
  let cursor = 0;
  for (let index = 0; index < state.recordings.length; index += 1) {
    const chunk = state.recordings[index];
    const next = cursor + chunk.duration_seconds;
    if (second >= cursor && second <= next) return { chunk, index, offset: second - cursor };
    cursor = next;
  }
  return null;
}

function chunksInRange(start, end) {
  let cursor = 0;
  return state.recordings.filter((chunk) => {
    const chunkStart = cursor;
    const chunkEnd = cursor + chunk.duration_seconds;
    cursor = chunkEnd;
    return chunkStart < end && chunkEnd > start;
  });
}

function totalDuration() {
  return state.recordings.reduce((sum, chunk) => sum + chunk.duration_seconds, 0);
}

function selectedTimes() {
  const start = Math.min(Number($("rangeStart").value), Number($("rangeEnd").value));
  const end = Math.max(Number($("rangeStart").value), Number($("rangeEnd").value));
  const first = state.recordings[0];
  if (!first) return null;
  const base = new Date(first.start_time).getTime();
  return {
    startOffset: start,
    endOffset: end,
    startTime: new Date(base + start * 1000),
    endTime: new Date(base + end * 1000),
    chunks: chunksInRange(start, end),
  };
}

function updateSelectedRange() {
  const selected = selectedTimes();
  $("selectedRange").textContent = selected
    ? `Rango: ${selected.startTime.toLocaleString()} a ${selected.endTime.toLocaleString()} (${Math.round(selected.endOffset - selected.startOffset)}s)`
    : "Sin grabaciones disponibles.";
}

function labelFor(type) {
  return (
    {
      normal: "Normal",
      freeze: "Freeze",
      black_screen: "Pantalla negra",
      buffering: "Buffering",
      ad: "Anuncio",
      repeated_ad: "Anuncio repetido",
      scene_change: "Cambio de escena",
    }[type] || type
  );
}

function eventTypes() {
  return ["normal", "freeze", "black_screen", "buffering", "ad", "repeated_ad", "scene_change"];
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await login($("email").value, $("password").value);
    toast("Sesion iniciada");
  } catch (error) {
    toast(error.message);
  }
});

$("cameraForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await request("/cameras", {
      method: "POST",
      body: JSON.stringify({ name: $("cameraName").value, source: $("cameraSource").value, enabled: true }),
    });
    $("cameraName").value = "";
    $("cameraSource").value = "";
    await hydrate();
    toast("Camara agregada");
  } catch (error) {
    toast(error.message);
  }
});

$("manualEventForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = selectedTimes();
  if (!selected || selected.endOffset === selected.startOffset) {
    toast("Selecciona un rango valido");
    return;
  }
  try {
    await request("/events/manual", {
      method: "POST",
      body: JSON.stringify({
        camera_id: state.reviewCameraId,
        type: $("manualEventType").value,
        start_time: selected.startTime.toISOString(),
        end_time: selected.endTime.toISOString(),
        recording_paths: selected.chunks.map((chunk) => chunk.path),
        notes: $("manualNotes").value,
      }),
    });
    $("manualNotes").value = "";
    await hydrate();
    toast("Rango guardado para IA");
  } catch (error) {
    toast(error.message);
  }
});

$("reviewCamera").addEventListener("change", async () => {
  state.reviewCameraId = Number($("reviewCamera").value);
  $("rangeStart").value = "0";
  $("rangeEnd").value = "0";
  $("reviewVideo").removeAttribute("src");
  $("reviewVideo").load();
  await loadRecordings();
  renderReview();
});

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));
$("rangeStart").addEventListener("input", () => {
  updateSelectedRange();
  playVirtualSecond(Number($("rangeStart").value));
});
$("rangeEnd").addEventListener("input", updateSelectedRange);
$("refreshButton").addEventListener("click", () => hydrate().catch((error) => toast(error.message)));
$("eventFilter").addEventListener("change", () => hydrate().catch((error) => toast(error.message)));
$("reviewVideo").addEventListener("ended", () => {
  const video = $("reviewVideo");
  const index = state.recordings.findIndex((chunk) => `${API_URL}${chunk.url}` === video.src);
  if (index >= 0 && index < state.recordings.length - 1) playChunk(index + 1, 0);
});

if (state.token) {
  hydrate().catch(() => {
    localStorage.removeItem("streamwatch_token");
    state.token = null;
  });
}
