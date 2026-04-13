const API_URL = "http://localhost:8000";
const state = {
  token: localStorage.getItem("streamwatch_token"),
  user: null,
  cameras: [],
  events: [],
};

const $ = (id) => document.getElementById(id);

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  setTimeout(() => node.classList.add("hidden"), 3200);
}

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
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
  render();
}

function render() {
  $("loginPanel").classList.add("hidden");
  $("appPanel").classList.remove("hidden");
  $("session").textContent = `${state.user.email} · ${state.user.role}`;
  $("cameraCount").textContent = state.cameras.length;
  $("eventCount").textContent = state.events.length;
  $("criticalCount").textContent = state.events.filter((event) =>
    ["freeze", "black_screen", "repeated_ad"].includes(event.type)
  ).length;
  renderCameras();
  renderEvents();
}

function renderCameras() {
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
    : `<article class="item"><strong>Sin cámaras</strong><p>Agrega una fuente para iniciar captura.</p></article>`;
}

function renderEvents() {
  const events = $("events");
  events.innerHTML = state.events.length
    ? state.events.map(eventTemplate).join("")
    : `<article class="event"><div><strong>Sin eventos</strong><p>Aún no hay evidencia registrada.</p></div></article>`;

  document.querySelectorAll("[data-label-event]").forEach((button) => {
    button.addEventListener("click", async () => {
      const eventId = Number(button.dataset.labelEvent);
      const select = document.querySelector(`[data-label-select="${eventId}"]`);
      await request("/events/label", {
        method: "POST",
        body: JSON.stringify({ event_id: eventId, label: select.value }),
      });
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
        <strong>${labelFor(event.type)} · Cámara ${event.camera_id}</strong>
        <p>${new Date(event.timestamp).toLocaleString()} · Confianza ${(event.confidence * 100).toFixed(0)}%</p>
        ${event.image_path ? `<p>${escapeHtml(event.image_path)}</p>` : ""}
        <div class="label-row">
          <select data-label-select="${event.id}">
            ${["normal", "freeze", "black_screen", "buffering", "ad", "repeated_ad", "scene_change"]
              .map((type) => `<option value="${type}" ${type === event.type ? "selected" : ""}>${labelFor(type)}</option>`)
              .join("")}
          </select>
          <button data-label-event="${event.id}" type="button">Etiquetar</button>
        </div>
      </div>
      <span class="badge ${critical ? "critical" : warn ? "warn" : ""}">${event.type}</span>
    </article>
  `;
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
    toast("Sesión iniciada");
  } catch (error) {
    toast(error.message);
  }
});

$("cameraForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await request("/cameras", {
      method: "POST",
      body: JSON.stringify({
        name: $("cameraName").value,
        source: $("cameraSource").value,
        enabled: true,
      }),
    });
    $("cameraName").value = "";
    $("cameraSource").value = "";
    await hydrate();
    toast("Cámara agregada");
  } catch (error) {
    toast(error.message);
  }
});

$("refreshButton").addEventListener("click", () => hydrate().catch((error) => toast(error.message)));
$("eventFilter").addEventListener("change", () => hydrate().catch((error) => toast(error.message)));

if (state.token) {
  hydrate().catch(() => {
    localStorage.removeItem("streamwatch_token");
    state.token = null;
  });
}

