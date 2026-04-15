<script>
  import { onDestroy } from "svelte";

  const API_URL = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`;
  const defaultEventTypes = ["normal", "freeze", "black_screen", "buffering", "ad", "repeated_ad", "scene_change"];

  let token = localStorage.getItem("streamwatch_token") || "";
  let user = null;
  let cameras = [];
  let categories = [];
  let events = [];
  let recordings = [];
  let recordingStatuses = [];
  let tests = [];
  let models = [];
  let datasets = [];
  let datasetStats = null;
  let activeTest = null;
  let activeView = "cameras";
  let eventFilter = "";
  let reviewCameraId = null;
  let rangeStart = 0;
  let rangeEnd = 0;
  let manualEventType = "freeze";
  let manualNotes = "";
  let email = "admin@streamwatch.example.com";
  let password = "admin123";
  let cameraName = "";
  let cameraSource = "";
  let cameraRoiX = "";
  let cameraRoiY = "";
  let cameraRoiWidth = "";
  let cameraRoiHeight = "";
  let editingCameraId = null;
  let editCameraName = "";
  let editCameraSource = "";
  let editCameraEnabled = true;
  let editCameraRoiX = "";
  let editCameraRoiY = "";
  let editCameraRoiWidth = "";
  let editCameraRoiHeight = "";
  let categoryKey = "";
  let categoryName = "";
  let categoryDescription = "";
  let categoryCritical = false;
  let trainPurpose = "event_classifier";
  let trainEpochs = 10;
  let trainDatasetId = "";
  let trainNotes = "";
  let trainActivate = true;
  let modelName = "";
  let modelPurpose = "event_classifier";
  let modelVersion = "";
  let modelPath = "";
  let modelEpochs = "";
  let modelAccuracy = "";
  let modelActivate = false;
  let datasetName = "";
  let datasetDescription = "";
  let parentDatasetId = null;
  let datasetFilter = "";
  let datasetCameraFilter = "";
  let datasetSearch = "";
  let selectedAiEventId = null;
  let aiCorrectedLabel = "";
  let bulkDatasetLabel = "";
  let selectedDatasetEvents = [];
  let aiDatasetEvents = [];
  let aiPreviewEvent = null;
  let fieldCameraId = "";
  let fieldPurpose = "event_classifier";
  let fieldEvents = [];
  let fieldCamera = null;
  let fieldPolling = null;
  let newUserEmail = "";
  let newUserPassword = "";
  let newUserRole = "viewer";
  let testName = "";
  let testDescription = "";
  let testDurationMinutes = 240;
  let testChunkSeconds = 60;
  let testCameraIds = [];
  let toastMessage = "";
  let videoEl;
  let canvasEl;
  let timelineEl;
  let isPlaying = false;
  let virtualTime = 0;
  let currentChunkIndex = -1;
  let draggingSelection = false;
  let liveSockets = {};
  let liveFrameUrls = {};
  let roiCamera = null;
  let roiBox = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
  let roiDragging = false;
  let roiDragStart = null;

  $: role = user?.role || "guest";
  $: canConfigure = role === "admin";
  $: canTrain = role === "admin" || role === "supervisor";
  $: canLabel = canTrain || role === "analyst";
  $: visibleViews = [
    { id: "cameras", label: "Camaras", show: true },
    { id: "tests", label: "Pruebas", show: canLabel },
    { id: "editor", label: "Editor de monitoreo", show: canLabel },
    { id: "events", label: "Eventos", show: true },
    { id: "ai_lab", label: "IA Lab", show: canLabel },
    { id: "field_test", label: "Campo de pruebas", show: canLabel },
    { id: "sources", label: "Fuentes", show: canConfigure },
    { id: "users", label: "Usuarios", show: canConfigure },
    { id: "system", label: "Sistema", show: canConfigure || canTrain },
  ].filter((view) => view.show);
  $: totalDuration = recordings.reduce((sum, chunk) => sum + chunk.duration_seconds, 0);
  $: criticalCount = events.filter((event) => isCritical(event.type)).length;
  $: selected = selectedTimes();
  $: eventTypes = categories.length ? categories.map((category) => category.key) : defaultEventTypes;
  $: {
    datasetSearch;
    datasetFilter;
    datasetCameraFilter;
    events;
    cameras;
    categories;
    aiDatasetEvents = filteredDatasetEvents();
  }
  $: {
    selectedAiEventId;
    aiDatasetEvents;
    aiPreviewEvent = aiDatasetEvents.find((event) => event.id === selectedAiEventId) || aiDatasetEvents[0] || null;
  }
  $: if (aiPreviewEvent && (!aiCorrectedLabel || !eventTypes.includes(aiCorrectedLabel))) {
    aiCorrectedLabel = latestLabelForEvent(aiPreviewEvent);
  }
  $: if (!bulkDatasetLabel && eventTypes.length) {
    bulkDatasetLabel = eventTypes[0];
  }
  $: {
    fieldCameraId;
    cameras;
    fieldCamera = selectedFieldCamera();
  }

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_URL}${path}`, { ...options, headers });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(detail.detail || "Error de API");
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function login() {
    try {
      const data = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      token = data.access_token;
      localStorage.setItem("streamwatch_token", token);
      await hydrate();
      notify("Sesion iniciada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function hydrate() {
    user = await api("/auth/me");
    cameras = await api(`/cameras${user?.role === "admin" ? "?include_disabled=true" : ""}`);
    categories = await api("/categories");
    events = await api(`/events${eventFilter ? `?type=${eventFilter}` : ""}`);
    recordingStatuses = await api("/recordings/status");
    tests = await api("/tests");
    if (["admin", "supervisor", "analyst"].includes(user?.role)) {
      datasetStats = await api("/dataset/stats");
      datasets = await api("/datasets");
      models = await api("/models");
    }
    if (activeTest) {
      activeTest = tests.find((test) => test.id === activeTest.id) || activeTest;
    }
    if (!reviewCameraId && cameras[0]) reviewCameraId = cameras[0].id;
    if (!fieldCameraId && cameras[0]) fieldCameraId = String(cameras[0].id);
    await loadRecordings();
    if (!visibleViews.some((view) => view.id === activeView)) activeView = visibleViews[0]?.id || "cameras";
  }

  async function loadRecordings() {
    if (!reviewCameraId || !activeTest) {
      recordings = [];
      return;
    }
    const params = new URLSearchParams({
      camera_id: String(reviewCameraId),
      test_id: String(activeTest.id),
      duration_seconds: String(activeTest.chunk_seconds || 60),
      start_time: activeTest.started_at,
      end_time: activeTest.ends_at,
    });
    recordings = await api(`/recordings?${params.toString()}`);
    if (rangeEnd === 0 || rangeEnd > totalDuration) rangeEnd = totalDuration;
    if (rangeStart > totalDuration) rangeStart = 0;
    virtualTime = 0;
    currentChunkIndex = -1;
    drawEditorPlaceholder();
  }

  async function createTest() {
    if (!canTrain) return;
    if (!testCameraIds.length) {
      notify("Selecciona al menos una camara");
      return;
    }
    try {
      const created = await api("/tests", {
        method: "POST",
        body: JSON.stringify({
          name: testName,
          description: testDescription,
          camera_ids: testCameraIds.map(Number),
          duration_minutes: Number(testDurationMinutes),
          chunk_seconds: Number(testChunkSeconds),
        }),
      });
      testName = "";
      testDescription = "";
      testCameraIds = [];
      activeTest = created;
      reviewCameraId = created.camera_ids[0];
      activeView = "editor";
      rangeStart = 0;
      rangeEnd = 0;
      await hydrate();
      notify("Prueba iniciada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function openTest(test) {
    activeTest = test;
    reviewCameraId = test.camera_ids[0];
    rangeStart = 0;
    rangeEnd = 0;
    activeView = "editor";
    await loadRecordings();
  }

  async function finishTest(test) {
    if (!canTrain) return;
    try {
      activeTest = await api(`/tests/${test.id}/finish`, { method: "PATCH" });
      await hydrate();
      notify("Prueba finalizada");
    } catch (error) {
      notify(error.message);
    }
  }

  function toggleTestCamera(cameraId) {
    testCameraIds = testCameraIds.includes(cameraId)
      ? testCameraIds.filter((id) => id !== cameraId)
      : [...testCameraIds, cameraId];
  }

  function testCameras(test = activeTest) {
    if (!test) return cameras.filter((camera) => camera.enabled);
    return cameras.filter((camera) => test.camera_ids.includes(camera.id));
  }

  function roiPayload(prefix = "") {
    const read = (name) => {
      const value = prefix === "edit" ? { x: editCameraRoiX, y: editCameraRoiY, width: editCameraRoiWidth, height: editCameraRoiHeight }[name] : { x: cameraRoiX, y: cameraRoiY, width: cameraRoiWidth, height: cameraRoiHeight }[name];
      return value === "" || value === null || value === undefined ? null : Number(value);
    };
    return {
      roi_x: read("x"),
      roi_y: read("y"),
      roi_width: read("width"),
      roi_height: read("height"),
    };
  }

  function clamp(value, min = 0, max = 1) {
    return Math.max(min, Math.min(max, value));
  }

  function startRoiCalibration(camera) {
    roiCamera = camera;
    if (camera.roi_width && camera.roi_height) {
      roiBox = {
        x: Number(camera.roi_x || 0),
        y: Number(camera.roi_y || 0),
        width: Number(camera.roi_width),
        height: Number(camera.roi_height),
      };
    } else {
      roiBox = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
    }
  }

  function closeRoiCalibration() {
    roiCamera = null;
    roiDragging = false;
    roiDragStart = null;
  }

  function roiBoxStyle() {
    return `left:${roiBox.x * 100}%;top:${roiBox.y * 100}%;width:${roiBox.width * 100}%;height:${roiBox.height * 100}%;`;
  }

  function roiPoint(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: clamp((event.clientX - rect.left) / rect.width),
      y: clamp((event.clientY - rect.top) / rect.height),
    };
  }

  function startRoiDrag(event) {
    roiDragging = true;
    roiDragStart = roiPoint(event);
    roiBox = { x: roiDragStart.x, y: roiDragStart.y, width: 0.01, height: 0.01 };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function updateRoiDrag(event) {
    if (!roiDragging || !roiDragStart) return;
    const point = roiPoint(event);
    roiBox = {
      x: Math.min(roiDragStart.x, point.x),
      y: Math.min(roiDragStart.y, point.y),
      width: Math.max(0.01, Math.abs(point.x - roiDragStart.x)),
      height: Math.max(0.01, Math.abs(point.y - roiDragStart.y)),
    };
  }

  function stopRoiDrag() {
    roiDragging = false;
    roiDragStart = null;
  }

  function useCenteredRoi() {
    roiBox = { x: 0.08, y: 0.08, width: 0.84, height: 0.84 };
  }

  async function suggestRoiFromSnapshot(camera) {
    try {
      const response = await fetch(snapshotUrl(camera));
      if (!response.ok) throw new Error("No hay snapshot disponible");
      const bitmap = await createImageBitmap(await response.blob());
      const canvas = document.createElement("canvas");
      canvas.width = 160;
      canvas.height = 90;
      const context = canvas.getContext("2d");
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
      let minX = canvas.width;
      let minY = canvas.height;
      let maxX = 0;
      let maxY = 0;
      let matches = 0;
      for (let y = 0; y < canvas.height; y += 1) {
        for (let x = 0; x < canvas.width; x += 1) {
          const offset = (y * canvas.width + x) * 4;
          const r = data[offset];
          const g = data[offset + 1];
          const b = data[offset + 2];
          const brightness = (r + g + b) / 3;
          const contrast = Math.max(r, g, b) - Math.min(r, g, b);
          if (brightness > 45 && (contrast > 14 || brightness > 115)) {
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x);
            maxY = Math.max(maxY, y);
            matches += 1;
          }
        }
      }
      if (matches < 80) {
        useCenteredRoi();
        notify("No pude detectar pantalla; use un marco central");
        return;
      }
      const padX = canvas.width * 0.03;
      const padY = canvas.height * 0.03;
      roiBox = {
        x: clamp((minX - padX) / canvas.width),
        y: clamp((minY - padY) / canvas.height),
        width: clamp((maxX - minX + padX * 2) / canvas.width, 0.05, 1),
        height: clamp((maxY - minY + padY * 2) / canvas.height, 0.05, 1),
      };
      notify("Sugerencia de pantalla aplicada");
    } catch (error) {
      useCenteredRoi();
      notify(error.message || "No pude leer el snapshot");
    }
  }

  async function saveRoiCalibration() {
    if (!roiCamera) return;
    const round = (value) => Math.round(value * 1000) / 1000;
    try {
      await api(`/cameras/${roiCamera.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          roi_x: round(roiBox.x),
          roi_y: round(roiBox.y),
          roi_width: round(roiBox.width),
          roi_height: round(roiBox.height),
        }),
      });
      closeRoiCalibration();
      await hydrate();
      notify("ROI guardado");
    } catch (error) {
      notify(error.message);
    }
  }

  async function clearRoiCalibration() {
    if (!roiCamera) return;
    try {
      await api(`/cameras/${roiCamera.id}`, {
        method: "PATCH",
        body: JSON.stringify({ roi_x: null, roi_y: null, roi_width: null, roi_height: null }),
      });
      closeRoiCalibration();
      await hydrate();
      notify("ROI eliminado");
    } catch (error) {
      notify(error.message);
    }
  }

  async function addCamera() {
    if (!canConfigure) return;
    try {
      await api("/cameras", {
        method: "POST",
        body: JSON.stringify({ name: cameraName, source: cameraSource, enabled: true, ...roiPayload() }),
      });
      cameraName = "";
      cameraSource = "";
      cameraRoiX = "";
      cameraRoiY = "";
      cameraRoiWidth = "";
      cameraRoiHeight = "";
      await hydrate();
      notify("Camara agregada");
    } catch (error) {
      notify(error.message);
    }
  }

  function startEditCamera(camera) {
    editingCameraId = camera.id;
    editCameraName = camera.name;
    editCameraSource = camera.source;
    editCameraEnabled = camera.enabled;
    editCameraRoiX = camera.roi_x ?? "";
    editCameraRoiY = camera.roi_y ?? "";
    editCameraRoiWidth = camera.roi_width ?? "";
    editCameraRoiHeight = camera.roi_height ?? "";
  }

  function cancelEditCamera() {
    editingCameraId = null;
    editCameraName = "";
    editCameraSource = "";
    editCameraEnabled = true;
    editCameraRoiX = "";
    editCameraRoiY = "";
    editCameraRoiWidth = "";
    editCameraRoiHeight = "";
  }

  async function updateCamera(cameraId) {
    if (!canConfigure) return;
    try {
      await api(`/cameras/${cameraId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: editCameraName,
          source: editCameraSource,
          enabled: editCameraEnabled,
          ...roiPayload("edit"),
        }),
      });
      cancelEditCamera();
      await hydrate();
      notify("Camara actualizada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function disableCamera(cameraId) {
    if (!canConfigure) return;
    try {
      await api(`/cameras/${cameraId}`, { method: "DELETE" });
      await hydrate();
      notify("Camara desactivada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function setCameraEnabled(cameraId, enabled) {
    if (!canConfigure) return;
    try {
      await api(`/cameras/${cameraId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      });
      await hydrate();
      notify(enabled ? "Camara activada" : "Camara pausada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function createUser() {
    if (!canConfigure) return;
    try {
      await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email: newUserEmail, password: newUserPassword, role: newUserRole }),
      });
      newUserEmail = "";
      newUserPassword = "";
      newUserRole = "viewer";
      notify("Usuario creado");
    } catch (error) {
      notify(error.message);
    }
  }

  async function saveManualEvent() {
    if (!canLabel || !selected || selected.endOffset === selected.startOffset) {
      notify("Selecciona un rango valido");
      return;
    }
    try {
      await api("/events/manual", {
        method: "POST",
        body: JSON.stringify({
          camera_id: reviewCameraId,
          type: manualEventType,
          start_time: selected.startTime.toISOString(),
          end_time: selected.endTime.toISOString(),
          recording_paths: selected.chunks.map((chunk) => chunk.path),
          notes: manualNotes,
        }),
      });
      manualNotes = "";
      await hydrate();
      notify("Rango guardado para IA");
    } catch (error) {
      notify(error.message);
    }
  }

  async function labelEvent(event, label) {
    if (!canLabel) return;
    try {
      await api("/events/label", {
        method: "POST",
        body: JSON.stringify({ event_id: event.id, label }),
      });
      notify("Etiqueta guardada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function createCategory() {
    if (!canConfigure) return;
    try {
      await api("/categories", {
        method: "POST",
        body: JSON.stringify({
          key: categoryKey.trim(),
          name: categoryName.trim(),
          description: categoryDescription || null,
          critical: categoryCritical,
        }),
      });
      categoryKey = "";
      categoryName = "";
      categoryDescription = "";
      categoryCritical = false;
      await hydrate();
      notify("Categoria creada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function trainModel() {
    if (!canTrain) return;
    try {
      const model = await api("/train", {
        method: "POST",
        body: JSON.stringify({
          purpose: trainPurpose,
          epochs: Number(trainEpochs),
          dataset_id: trainDatasetId ? Number(trainDatasetId) : null,
          notes: trainNotes || null,
          activate: trainActivate,
        }),
      });
      trainNotes = "";
      await hydrate();
      notify(`Modelo creado: ${model.version}`);
    } catch (error) {
      notify(error.message);
    }
  }

  async function registerModel() {
    if (!canTrain) return;
    try {
      const payload = {
        version: modelVersion || null,
        name: modelName || null,
        purpose: modelPurpose,
        path: modelPath,
        epochs: modelEpochs === "" ? null : Number(modelEpochs),
        accuracy: modelAccuracy === "" ? null : Number(modelAccuracy),
        active: modelActivate,
      };
      const model = await api("/models", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      modelName = "";
      modelVersion = "";
      modelPath = "";
      modelEpochs = "";
      modelAccuracy = "";
      modelActivate = false;
      await hydrate();
      notify(`Artefacto registrado: ${model.version}`);
    } catch (error) {
      notify(error.message);
    }
  }

  async function activateModel(model) {
    if (!canTrain) return;
    try {
      await api(`/models/${model.id}/activate`, { method: "PATCH" });
      await hydrate();
      notify(`Modelo activo: ${model.version}`);
    } catch (error) {
      notify(error.message);
    }
  }

  async function refreshFieldEvents() {
    if (!fieldCameraId || !token) return;
    try {
      fieldEvents = await api(`/events?camera_id=${fieldCameraId}&limit=20`);
    } catch (error) {
      notify(error.message);
    }
  }

  async function startFieldCamera(camera) {
    await api(`/field-tests/cameras/${camera.id}`, { method: "POST" });
    startLive(camera);
    startFieldPolling();
  }

  async function stopFieldCamera() {
    if (fieldCameraId) {
      await api(`/field-tests/cameras/${fieldCameraId}`, { method: "DELETE" }).catch(() => null);
      stopLive(Number(fieldCameraId));
    }
    stopFieldPolling();
  }

  function startFieldPolling() {
    if (fieldPolling) clearInterval(fieldPolling);
    refreshFieldEvents();
    fieldPolling = setInterval(refreshFieldEvents, 2500);
  }

  function stopFieldPolling() {
    if (fieldPolling) clearInterval(fieldPolling);
    fieldPolling = null;
  }

  function openFieldTest(camera) {
    fieldCameraId = String(camera.id);
    activeView = "field_test";
    startFieldCamera(camera).catch((error) => notify(error.message));
  }

  function selectedFieldCamera() {
    return cameras.find((camera) => camera.id === Number(fieldCameraId));
  }

  function latestFieldDetection() {
    return fieldEvents[0] || null;
  }

  function activeModelForPurpose(purpose) {
    return models.find((model) => model.purpose === purpose && model.active);
  }

  function filteredDatasetEvents() {
    const search = datasetSearch.trim().toLowerCase();
    return events.filter((event) => {
      const camera = cameras.find((item) => item.id === event.camera_id);
      const matchesCategory = !datasetFilter || event.type === datasetFilter;
      const matchesCamera = !datasetCameraFilter || event.camera_id === Number(datasetCameraFilter);
      const effectiveLabel = latestLabelForEvent(event);
      const text = `${event.id} ${event.type} ${effectiveLabel} ${labelFor(effectiveLabel)} ${camera?.name || ""} ${event.camera_id}`.toLowerCase();
      return matchesCategory && matchesCamera && (!search || text.includes(search));
    });
  }

  function toggleDatasetEvent(eventId) {
    selectedDatasetEvents = selectedDatasetEvents.includes(eventId)
      ? selectedDatasetEvents.filter((id) => id !== eventId)
      : [...selectedDatasetEvents, eventId];
    selectedAiEventId = eventId;
  }

  function handleDatasetEventClick(mouseEvent, event) {
    if (mouseEvent.ctrlKey || mouseEvent.metaKey) {
      toggleDatasetEvent(event.id);
      return;
    }
    selectAiEvent(event);
  }

  function selectAiEvent(event) {
    selectedAiEventId = event.id;
    aiCorrectedLabel = latestLabelForEvent(event);
  }

  function selectDatasetFilter(type) {
    datasetFilter = type;
    selectedDatasetEvents = aiDatasetEvents.map((event) => event.id);
  }

  function clearDatasetSelection() {
    selectedDatasetEvents = [];
  }

  function selectedDatasetEventObjects() {
    return selectedDatasetEvents
      .map((eventId) => events.find((event) => event.id === eventId))
      .filter(Boolean);
  }

  function loadDatasetIntoBuilder(dataset) {
    selectedDatasetEvents = [...dataset.event_ids];
    parentDatasetId = dataset.id;
    datasetName = `${dataset.name} derivado`;
    datasetDescription = `Derivado de ${dataset.version}${dataset.description ? ` - ${dataset.description}` : ""}`;
    selectedAiEventId = dataset.event_ids[0] || null;
    notify(`Dataset cargado al constructor: ${dataset.name}`);
  }

  function mergeDatasetIntoBuilder(dataset) {
    selectedDatasetEvents = Array.from(new Set([...selectedDatasetEvents, ...dataset.event_ids]));
    parentDatasetId = parentDatasetId || dataset.id;
    selectedAiEventId = selectedAiEventId || dataset.event_ids[0] || null;
    notify(`Dataset combinado: ${dataset.name}`);
  }

  function parentDatasetLabel() {
    if (!parentDatasetId) return "";
    const dataset = datasets.find((item) => item.id === parentDatasetId);
    return dataset ? `Derivado de ${dataset.name}` : "Dataset derivado";
  }

  async function createDataset() {
    if (!canLabel || !selectedDatasetEvents.length) {
      notify("Selecciona eventos para el dataset");
      return;
    }
    try {
      const dataset = await api("/datasets", {
        method: "POST",
        body: JSON.stringify({
          name: datasetName || `dataset_${new Date().toISOString().slice(0, 10)}`,
          description: datasetDescription || null,
          event_ids: selectedDatasetEvents,
          parent_dataset_id: parentDatasetId,
        }),
      });
      datasetName = "";
      datasetDescription = "";
      parentDatasetId = null;
      selectedDatasetEvents = [];
      await hydrate();
      notify(`Dataset creado: ${dataset.version}`);
    } catch (error) {
      notify(error.message);
    }
  }

  async function saveCorrectedLabel(event) {
    if (!canLabel || !event || !aiCorrectedLabel) return;
    try {
      await api("/events/label", {
        method: "POST",
        body: JSON.stringify({
          event_id: event.id,
          label: aiCorrectedLabel,
          notes: `Correccion desde IA Lab. Prediccion original: ${event.type}`,
        }),
      });
      await hydrate();
      notify(`Etiqueta corregida: ${labelFor(aiCorrectedLabel)}`);
    } catch (error) {
      notify(error.message);
    }
  }

  async function saveEventLabel(event, label) {
    if (!canLabel || !event || !label) return;
    try {
      await api("/events/label", {
        method: "POST",
        body: JSON.stringify({
          event_id: event.id,
          label,
          notes: `Correccion desde seleccion de dataset. Prediccion original: ${event.type}`,
        }),
      });
      await hydrate();
      notify(`Etiqueta actualizada: ${labelFor(label)}`);
    } catch (error) {
      notify(error.message);
    }
  }

  async function applyBulkLabel() {
    if (!canLabel || !selectedDatasetEvents.length || !bulkDatasetLabel) {
      notify("Selecciona evidencias y una categoria");
      return;
    }
    try {
      await api("/events/labels/bulk", {
        method: "POST",
        body: JSON.stringify({
          event_ids: selectedDatasetEvents,
          label: bulkDatasetLabel,
          notes: "Correccion masiva desde IA Lab",
        }),
      });
      await hydrate();
      notify(`${selectedDatasetEvents.length} evidencias corregidas como ${labelFor(bulkDatasetLabel)}`);
    } catch (error) {
      notify(error.message);
    }
  }

  function cameraForEvent(event) {
    return cameras.find((camera) => camera.id === event?.camera_id);
  }

  function eventMetadata(event) {
    if (!event?.metadata_json) return {};
    try {
      return JSON.parse(event.metadata_json);
    } catch {
      return {};
    }
  }

  function latestLabelForEvent(event) {
    if (!event?.labels?.length) return event?.type;
    return [...event.labels].sort((a, b) => new Date(a.created_at) - new Date(b.created_at)).at(-1)?.label || event.type;
  }

  function roiForEvent(event) {
    const metadata = eventMetadata(event);
    if (metadata.analysis_region === "screen_roi") {
      return {
        x: Number(metadata.roi_x || 0),
        y: Number(metadata.roi_y || 0),
        width: Number(metadata.roi_width || 1),
        height: Number(metadata.roi_height || 1),
        source: "ROI usado en deteccion",
      };
    }
    const camera = cameraForEvent(event);
    if (camera?.roi_width && camera?.roi_height) {
      return {
        x: Number(camera.roi_x || 0),
        y: Number(camera.roi_y || 0),
        width: Number(camera.roi_width),
        height: Number(camera.roi_height),
        source: "ROI actual de camara",
      };
    }
    return null;
  }

  function roiStyle(roi) {
    if (!roi) return "";
    return `left:${roi.x * 100}%;top:${roi.y * 100}%;width:${roi.width * 100}%;height:${roi.height * 100}%;`;
  }

  function streamUrl(cameraId) {
    const protocol = API_URL.startsWith("https://") ? "wss://" : "ws://";
    const host = API_URL.replace(/^https?:\/\//, "");
    return `${protocol}${host}/ws/cameras/${cameraId}/stream?mode=viewer&token=${encodeURIComponent(token)}`;
  }

  function startLive(camera) {
    stopLive(camera.id);
    const socket = new WebSocket(streamUrl(camera.id));
    socket.binaryType = "blob";
    socket.onmessage = (event) => {
      const previousUrl = liveFrameUrls[camera.id];
      const nextUrl = URL.createObjectURL(event.data);
      liveFrameUrls = { ...liveFrameUrls, [camera.id]: nextUrl };
      if (previousUrl) URL.revokeObjectURL(previousUrl);
    };
    socket.onopen = () => notify("Stream del worker conectado");
    socket.onerror = () => notify("No se pudo conectar el stream del worker");
    socket.onclose = () => {
      const nextSockets = { ...liveSockets };
      delete nextSockets[camera.id];
      liveSockets = nextSockets;
    };
    liveSockets = { ...liveSockets, [camera.id]: socket };
  }

  function stopLive(cameraId) {
    const socket = liveSockets[cameraId];
    if (socket) {
      socket.close();
      const nextSockets = { ...liveSockets };
      delete nextSockets[cameraId];
      liveSockets = nextSockets;
    }
    const frameUrl = liveFrameUrls[cameraId];
    if (frameUrl) {
      URL.revokeObjectURL(frameUrl);
      const nextFrames = { ...liveFrameUrls };
      delete nextFrames[cameraId];
      liveFrameUrls = nextFrames;
    }
  }

  function stopAllLive() {
    Object.keys(liveSockets).forEach((cameraId) => stopLive(cameraId));
  }

  async function openEditor(cameraId) {
    if (!canLabel) return;
    const test = tests.find((candidate) => candidate.status === "running" && candidate.camera_ids.includes(cameraId));
    if (!test) {
      notify("Abre o crea una prueba para editar esta camara");
      activeView = "tests";
      return;
    }
    activeTest = test;
    reviewCameraId = cameraId;
    activeView = "editor";
    rangeStart = 0;
    rangeEnd = 0;
    await loadRecordings();
  }

  async function changeReviewCamera() {
    reviewCameraId = Number(reviewCameraId);
    pauseEditor();
    rangeStart = 0;
    rangeEnd = 0;
    if (videoEl) {
      videoEl.removeAttribute("src");
      videoEl.load();
    }
    await loadRecordings();
  }

  async function seekEditor(second, autoplay = false) {
    virtualTime = Math.max(0, Math.min(Number(second), totalDuration));
    const chunk = chunkAtSecond(second);
    if (!chunk || !videoEl) {
      drawEditorPlaceholder();
      return;
    }
    const url = `${API_URL}${chunk.chunk.url}`;
    const needsSource = videoEl.src !== url;
    currentChunkIndex = chunk.index;
    if (needsSource) {
      videoEl.src = url;
      await new Promise((resolve) => {
        videoEl.onloadedmetadata = resolve;
        videoEl.load();
      });
    }
    const realDuration = Number.isFinite(videoEl.duration) && videoEl.duration > 0 ? videoEl.duration : chunk.chunk.duration_seconds;
    const safeOffset = Math.max(0, Math.min(chunk.offset, Math.max(realDuration - 0.35, 0)));
    videoEl.currentTime = safeOffset;
    drawEditorFrame();
    if (autoplay) {
      await videoEl.play().catch(() => {});
      isPlaying = true;
    }
  }

  function playEditor() {
    if (!recordings.length) return;
    seekEditor(virtualTime, true);
  }

  function pauseEditor() {
    if (videoEl) videoEl.pause();
    isPlaying = false;
  }

  function toggleEditorPlayback() {
    if (isPlaying) pauseEditor();
    else playEditor();
  }

  function onEditorTimeUpdate() {
    if (currentChunkIndex < 0 || !videoEl) return;
    const base = recordings.slice(0, currentChunkIndex).reduce((sum, chunk) => sum + chunk.duration_seconds, 0);
    virtualTime = Math.min(base + videoEl.currentTime, totalDuration);
    drawEditorFrame();
  }

  function playNextChunk() {
    if (currentChunkIndex >= 0 && currentChunkIndex < recordings.length - 1) {
      const nextBase = recordings.slice(0, currentChunkIndex + 1).reduce((sum, chunk) => sum + chunk.duration_seconds, 0);
      seekEditor(nextBase, true);
      return;
    }
    pauseEditor();
  }

  function drawEditorFrame() {
    if (!canvasEl) return;
    const context = canvasEl.getContext("2d");
    const width = canvasEl.clientWidth || 960;
    const height = Math.round((width * 9) / 16);
    if (canvasEl.width !== width || canvasEl.height !== height) {
      canvasEl.width = width;
      canvasEl.height = height;
    }
    context.fillStyle = "#101816";
    context.fillRect(0, 0, width, height);
    if (videoEl && videoEl.videoWidth) {
      const scale = Math.min(width / videoEl.videoWidth, height / videoEl.videoHeight);
      const drawWidth = videoEl.videoWidth * scale;
      const drawHeight = videoEl.videoHeight * scale;
      context.drawImage(videoEl, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
    } else {
      context.fillStyle = "#d7e6df";
      context.font = "700 18px Segoe UI";
      context.textAlign = "center";
      context.fillText("Selecciona un punto de la linea de tiempo", width / 2, height / 2);
    }
  }

  function drawEditorPlaceholder() {
    requestAnimationFrame(drawEditorFrame);
  }

  function chunkAtSecond(second) {
    let cursor = 0;
    for (let index = 0; index < recordings.length; index += 1) {
      const chunk = recordings[index];
      const next = cursor + chunk.duration_seconds;
      if (second >= cursor && second < next) return { chunk, index, offset: second - cursor };
      cursor = next;
    }
    if (recordings.length && second >= totalDuration) {
      const index = recordings.length - 1;
      const start = recordings.slice(0, index).reduce((sum, chunk) => sum + chunk.duration_seconds, 0);
      return { chunk: recordings[index], index, offset: Math.max(0, Math.min(second - start, recordings[index].duration_seconds - 0.35)) };
    }
    return null;
  }

  function chunksInRange(start, end) {
    let cursor = 0;
    return recordings.filter((chunk) => {
      const chunkStart = cursor;
      const chunkEnd = cursor + chunk.duration_seconds;
      cursor = chunkEnd;
      return chunkStart < end && chunkEnd > start;
    });
  }

  function timelineSecond(event) {
    if (!timelineEl || totalDuration === 0) return 0;
    const rect = timelineEl.getBoundingClientRect();
    const x = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
    return (x / rect.width) * totalDuration;
  }

  function startTimelineSelection(event) {
    if (!recordings.length) return;
    pauseEditor();
    draggingSelection = true;
    const second = timelineSecond(event);
    rangeStart = second;
    rangeEnd = second;
    seekEditor(second, false);
  }

  function moveTimelineSelection(event) {
    if (!draggingSelection) return;
    rangeEnd = timelineSecond(event);
  }

  function endTimelineSelection(event) {
    if (!draggingSelection) return;
    draggingSelection = false;
    rangeEnd = timelineSecond(event);
    if (Math.abs(rangeEnd - rangeStart) < 1) {
      seekEditor(rangeEnd, false);
    }
  }

  function percent(value) {
    if (!totalDuration) return 0;
    return Math.max(0, Math.min(100, (value / totalDuration) * 100));
  }

  function chunkWidth(chunk) {
    if (!totalDuration) return 0;
    return (chunk.duration_seconds / totalDuration) * 100;
  }

  function selectedTimes() {
    const start = Math.min(Number(rangeStart), Number(rangeEnd));
    const end = Math.max(Number(rangeStart), Number(rangeEnd));
    const first = recordings[0];
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

  function formatDuration(seconds) {
    const rounded = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(rounded / 3600);
    const minutes = Math.floor((rounded % 3600) / 60);
    const secs = rounded % 60;
    return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
  }

  function snapshotUrl(camera) {
    return `${API_URL}/media/snapshots/cam_${camera.id}.jpg?ts=${Date.now()}`;
  }

  function recordingStatus(cameraId) {
    return recordingStatuses.find((status) => status.camera_id === cameraId);
  }

  function categoryFor(type) {
    return categories.find((category) => category.key === type);
  }

  function labelFor(type) {
    return categoryFor(type)?.name || type;
  }

  function isCritical(type) {
    const category = categoryFor(type);
    return category ? category.critical : ["freeze", "black_screen", "repeated_ad"].includes(type);
  }

  function modelPurposeLabel(purpose) {
    return (
      {
        event_classifier: "Clasificador de sucesos",
        ad_fingerprint: "Fingerprint de anuncios",
        roi_detector: "Detector de pantalla",
        quality_detector: "Calidad de video",
      }[purpose] || purpose
    );
  }

  function modelStatusLabel(model) {
    if (model.active) return "Activo";
    return model.status || "Registrado";
  }

  function evidenceUrl(path) {
    if (!path) return "";
    const normalized = String(path).replaceAll("\\", "/");
    for (const marker of ["/events/", "/recordings/", "/snapshots/"]) {
      const index = normalized.indexOf(marker);
      if (index >= 0) return `${API_URL}/media/${normalized.slice(index + 1)}`;
    }
    return "";
  }

  function datasetSummary(dataset) {
    if (!dataset?.summary_json) return "";
    try {
      const summary = JSON.parse(dataset.summary_json);
      return `${summary.events || 0} eventos`;
    } catch {
      return "";
    }
  }

  function notify(message) {
    toastMessage = message;
    setTimeout(() => {
      toastMessage = "";
    }, 3200);
  }

  function logout() {
    stopFieldPolling();
    if (fieldCameraId) api(`/field-tests/cameras/${fieldCameraId}`, { method: "DELETE" }).catch(() => null);
    stopAllLive();
    token = "";
    user = null;
    localStorage.removeItem("streamwatch_token");
  }

  onDestroy(() => {
    stopFieldPolling();
    if (fieldCameraId) api(`/field-tests/cameras/${fieldCameraId}`, { method: "DELETE" }).catch(() => null);
    stopAllLive();
  });

  if (token) {
    hydrate().catch(() => logout());
  }
</script>

<main class="shell">
  <section class="topbar">
    <div>
      <p class="eyebrow">StreamWatch AI</p>
      <h1>Consola de monitoreo</h1>
    </div>
    {#if user}
      <div class="session">
        <strong>{user.email}</strong>
        <span>{role}</span>
        <button type="button" class="secondary" on:click={logout}>Salir</button>
      </div>
    {/if}
  </section>

  {#if !user}
    <section class="panel auth-panel">
      <div>
        <h2>Acceso</h2>
        <p>Ingresa con tu cuenta para ver solo las opciones permitidas para tu rol.</p>
      </div>
      <form class="form-row" on:submit|preventDefault={login}>
        <input bind:value={email} type="email" aria-label="Email" />
        <input bind:value={password} type="password" aria-label="Password" />
        <button type="submit">Entrar</button>
      </form>
    </section>
  {:else}
    <section class="workspace">
      <nav class="tabs" aria-label="Secciones">
        {#each visibleViews as view}
          <button type="button" class:active={activeView === view.id} on:click={() => (activeView = view.id)}>{view.label}</button>
        {/each}
      </nav>

      <section class="metrics">
        <article><span>{cameras.length}</span><p>Camaras</p></article>
        <article><span>{events.length}</span><p>Eventos</p></article>
        <article><span>{criticalCount}</span><p>Alertas criticas</p></article>
      </section>

      {#if activeView === "cameras"}
        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>Mosaico de camaras</h2>
              <p>Miniaturas recientes de todas las fuentes activas.</p>
            </div>
            <button type="button" on:click={hydrate}>Actualizar</button>
          </div>
          <div class="camera-mosaic">
            {#if cameras.length}
              {#each cameras as camera}
                <article class="camera-tile">
                  <div class="thumb-wrap">
                    {#if liveFrameUrls[camera.id]}
                      <img src={liveFrameUrls[camera.id]} alt={`Stream ${camera.name}`} />
                    {:else}
                      <img src={snapshotUrl(camera)} alt={camera.name} on:error={(event) => (event.currentTarget.style.display = "none")} />
                    {/if}
                    <div class="thumb-fallback">Sin senal</div>
                  </div>
                  <div class="tile-body">
                    <strong>{camera.name}</strong>
                    <p>{camera.source}</p>
                    <p class="recording-line">
                      {#if recordingStatus(camera.id)?.chunk_count}
                        Grabando historial - {recordingStatus(camera.id).chunk_count} chunks{recordingStatus(camera.id).latest_start_time ? ` - ultimo ${new Date(recordingStatus(camera.id).latest_start_time).toLocaleTimeString()}` : ""}
                      {:else}
                        Sin chunks grabados todavia
                      {/if}
                    </p>
                    <div class="tile-actions">
                      <span class:warn={!camera.enabled} class="badge">{camera.enabled ? "Activa" : "Pausada"}</span>
                      {#if liveSockets[camera.id]}
                        <button type="button" class="secondary" on:click={() => stopLive(camera.id)}>Detener vivo</button>
                      {:else}
                        <button type="button" on:click={() => startLive(camera)}>Ver en vivo</button>
                      {/if}
                      {#if canLabel}
                        <button type="button" class="secondary" on:click={() => openFieldTest(camera)}>Probar IA</button>
                        <button type="button" on:click={() => openEditor(camera.id)}>Editar video</button>
                      {/if}
                    </div>
                  </div>
                </article>
              {/each}
            {:else}
              <article class="item"><strong>Sin camaras</strong><p>{canConfigure ? "Agrega una camara desde Sistema." : "Aun no hay camaras registradas."}</p></article>
            {/if}
          </div>
        </section>
      {/if}

      {#if activeView === "tests" && canLabel}
        <section class="tests-layout">
          {#if canTrain}
            <div class="panel">
              <h2>Nueva prueba</h2>
              <p>Define el estudio antes de revisar varias horas de grabacion.</p>
              <form class="test-form" on:submit|preventDefault={createTest}>
                <input bind:value={testName} placeholder="Prueba Netflix sala QA" aria-label="Nombre de prueba" />
                <input bind:value={testDescription} placeholder="Descripcion del objetivo" aria-label="Descripcion" />
                <label>Duracion minutos <input bind:value={testDurationMinutes} type="number" min="1" max="10080" /></label>
                <label>Chunk segundos <input bind:value={testChunkSeconds} type="number" min="5" max="3600" /></label>
                <div class="camera-checks">
                  {#each cameras.filter((camera) => camera.enabled) as camera}
                    <button
                      type="button"
                      class:selected={testCameraIds.includes(camera.id)}
                      class:locked={camera.locked_by_test_id}
                      disabled={camera.locked_by_test_id}
                      on:click={() => toggleTestCamera(camera.id)}
                    >
                      <strong>{camera.name}</strong>
                      <span>{camera.source}</span>
                      {#if camera.locked_by_test_id}
                        <em>En prueba: {camera.locked_by_test_name}</em>
                      {:else if testCameraIds.includes(camera.id)}
                        <em>Seleccionada</em>
                      {:else}
                        <em>Disponible</em>
                      {/if}
                    </button>
                  {/each}
                </div>
                <button type="submit">Iniciar prueba</button>
              </form>
            </div>
          {/if}

          <div class="panel">
            <h2>Pruebas</h2>
            <div class="list">
              {#if tests.length}
                {#each tests as test}
                  <article class="item">
                    <div class="camera-row">
                      <div>
                        <strong>{test.name}</strong>
                        <p>{test.description || "Sin descripcion"}</p>
                        <p>{new Date(test.started_at).toLocaleString()} a {new Date(test.ends_at).toLocaleString()} - {test.camera_ids.length} camaras - chunks {test.chunk_seconds}s</p>
                        <span class:warn={test.status !== "running"} class="badge">{test.status}</span>
                      </div>
                      <div class="row-actions">
                        <button type="button" on:click={() => openTest(test)}>Abrir editor</button>
                        {#if canTrain && test.status === "running"}
                          <button type="button" class="secondary" on:click={() => finishTest(test)}>Finalizar</button>
                        {/if}
                      </div>
                    </div>
                  </article>
                {/each}
              {:else}
                <article class="item"><strong>Sin pruebas</strong><p>Crea una prueba para abrir el editor de monitoreo.</p></article>
              {/if}
            </div>
          </div>
        </section>
      {/if}

      {#if activeView === "editor" && canLabel}
        <section class="editor-layout">
          <div class="panel video-editor">
            <div class="panel-head">
              <div>
                <h2>{activeTest ? activeTest.name : "Editor de monitoreo"}</h2>
                <p>{activeTest ? `${activeTest.camera_ids.length} camaras - ${new Date(activeTest.started_at).toLocaleString()} a ${new Date(activeTest.ends_at).toLocaleString()}` : "Selecciona una prueba para cargar su timeline."}</p>
              </div>
              <select value={activeTest?.id || ""} on:change={async (event) => { const next = tests.find((test) => test.id === Number(event.currentTarget.value)); if (next) await openTest(next); }} aria-label="Prueba activa en editor">
                <option value="">Selecciona prueba</option>
                {#each tests as test}
                  <option value={test.id}>{test.name}</option>
                {/each}
              </select>
            </div>

            {#if activeTest}
              <div class="editor-subhead">
                <select bind:value={reviewCameraId} on:change={changeReviewCamera} aria-label="Camara para revision">
                  {#each testCameras() as camera}
                    <option value={camera.id}>{camera.name}</option>
                  {/each}
                </select>
              </div>
            {/if}

            {#if activeTest}
              <div class="custom-editor">
                <canvas bind:this={canvasEl} class="editor-canvas"></canvas>
                <video bind:this={videoEl} class="decode-video" muted playsinline on:timeupdate={onEditorTimeUpdate} on:ended={playNextChunk}></video>
                <div class="editor-controls">
                  <button type="button" on:click={toggleEditorPlayback}>{isPlaying ? "Pausar" : "Reproducir"}</button>
                  <button type="button" class="secondary" on:click={() => seekEditor(Math.max(0, virtualTime - 10), isPlaying)}>-10s</button>
                  <button type="button" class="secondary" on:click={() => seekEditor(Math.min(totalDuration, virtualTime + 10), isPlaying)}>+10s</button>
                  <strong>{formatDuration(virtualTime)} / {formatDuration(totalDuration)}</strong>
                </div>
              </div>
            {:else}
              <div class="editor-empty">Elige una prueba para ver sus grabaciones sin mezclar historiales.</div>
            {/if}

            {#if activeTest}
              <div
              bind:this={timelineEl}
              class="editor-timeline"
              role="slider"
              tabindex="0"
              aria-label="Linea de tiempo de la prueba"
              on:pointerdown={startTimelineSelection}
              on:pointermove={moveTimelineSelection}
              on:pointerup={endTimelineSelection}
              on:pointerleave={endTimelineSelection}
            >
              {#if recordings.length}
                {#each recordings as chunk}
                  <div class="timeline-chunk" style={`width: ${chunkWidth(chunk)}%`}>
                    <span>{new Date(chunk.start_time).toLocaleTimeString()}</span>
                  </div>
                {/each}
                <div class="timeline-playhead" style={`left: ${percent(virtualTime)}%`}></div>
                <div
                  class="timeline-selection"
                  style={`left: ${percent(Math.min(rangeStart, rangeEnd))}%; width: ${Math.abs(percent(rangeEnd) - percent(rangeStart))}%`}
                ></div>
              {:else}
                <div class="timeline-empty">No hay chunks grabados para esta camara.</div>
              {/if}
              </div>
            {/if}

            <p class="selected-range">
              {#if selected}
                Rango: {selected.startTime.toLocaleString()} a {selected.endTime.toLocaleString()} ({Math.round(selected.endOffset - selected.startOffset)}s)
              {:else}
                Sin grabaciones disponibles.
              {/if}
            </p>

            {#if activeTest}
              <div class="multi-camera-strip">
                {#each testCameras() as camera}
                  <button type="button" class:active={camera.id === reviewCameraId} on:click={async () => { reviewCameraId = camera.id; rangeStart = 0; rangeEnd = 0; await loadRecordings(); }}>
                    <img src={snapshotUrl(camera)} alt={camera.name} on:error={(event) => (event.currentTarget.style.display = "none")} />
                    <span>{camera.name}</span>
                  </button>
                {/each}
              </div>
            {/if}
          </div>

          <aside class="panel clip-panel">
            <h2>Clasificacion</h2>
            <p>Arrastra sobre la linea de tiempo para crear un rango y asignarle una categoria para IA.</p>
            <form class="manual-event-form stacked" on:submit|preventDefault={saveManualEvent}>
              <select bind:value={manualEventType} aria-label="Tipo de error">
                {#each eventTypes as type}
                  <option value={type}>{labelFor(type)}</option>
                {/each}
              </select>
              <input bind:value={manualNotes} placeholder="Notas para entrenamiento" aria-label="Notas" />
              <button type="submit">Guardar rango</button>
            </form>
          </aside>
        </section>
      {/if}

      {#if activeView === "events"}
        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>Eventos</h2>
              <p>{canLabel ? "Puedes corregir etiquetas segun tu rol." : "Vista de solo lectura."}</p>
            </div>
            <select bind:value={eventFilter} on:change={hydrate} aria-label="Filtro de evento">
              <option value="">Todos</option>
              {#each eventTypes as type}
                <option value={type}>{labelFor(type)}</option>
              {/each}
            </select>
          </div>
          <div class="timeline">
            {#if events.length}
              {#each events as event}
                <article class="event">
                  <div>
                    <strong>{labelFor(event.type)} - Camara {event.camera_id}</strong>
                    <p>{new Date(event.timestamp).toLocaleString()} - Confianza {Math.round(event.confidence * 100)}%</p>
                    {#if event.image_path}<p>{event.image_path}</p>{/if}
                    {#if canLabel}
                      <div class="label-row">
                        <select on:change={(e) => labelEvent(event, e.currentTarget.value)}>
                          {#each eventTypes as type}
                            <option value={type} selected={type === event.type}>{labelFor(type)}</option>
                          {/each}
                        </select>
                      </div>
                    {/if}
                  </div>
                  <span class:critical={isCritical(event.type)} class:warn={!isCritical(event.type) && ["buffering", "scene_change"].includes(event.type)} class="badge">{labelFor(event.type)}</span>
                </article>
              {/each}
            {:else}
              <article class="event"><div><strong>Sin eventos</strong><p>Aun no hay evidencia registrada.</p></div></article>
            {/if}
          </div>
        </section>
      {/if}

      {#if activeView === "field_test" && canLabel}
        <section class="field-layout">
          <div class="panel field-main">
            <div class="panel-head">
              <div>
                <h2>Campo de pruebas</h2>
                <p>Valida en vivo lo que el sistema detecta con el modelo activo y las reglas actuales.</p>
              </div>
              <button type="button" on:click={refreshFieldEvents}>Actualizar detecciones</button>
            </div>

            <div class="field-controls">
              <label>
                Camara
                <select bind:value={fieldCameraId} on:change={() => { const camera = selectedFieldCamera(); if (camera) startFieldCamera(camera).catch((error) => notify(error.message)); }}>
                  {#each cameras as camera}
                    <option value={camera.id}>{camera.name} - {camera.source}</option>
                  {/each}
                </select>
              </label>
              <label>
                Modelo / uso
                <select bind:value={fieldPurpose}>
                  <option value="event_classifier">Clasificador de sucesos</option>
                  <option value="ad_fingerprint">Fingerprint de anuncios</option>
                  <option value="roi_detector">Detector de pantalla</option>
                  <option value="quality_detector">Calidad de video</option>
                </select>
              </label>
            <div class="model-chip">
                {#if activeModelForPurpose(fieldPurpose)}
                  <span class="badge">Usando {activeModelForPurpose(fieldPurpose).version}</span>
                {:else}
                  <span class="badge warn">Sin modelo activo</span>
                {/if}
              </div>
            </div>
            <button type="button" class="secondary" on:click={stopFieldCamera}>Detener campo</button>

            {#if fieldCamera}
              <div class="field-stage">
                {#if liveFrameUrls[fieldCamera.id]}
                  <img src={liveFrameUrls[fieldCamera.id]} alt={`Vivo ${fieldCamera.name}`} />
                {:else}
                  <img src={snapshotUrl(fieldCamera)} alt={fieldCamera.name} />
                {/if}

                {#if latestFieldDetection()}
                  {#if roiForEvent(latestFieldDetection())}
                    <div class="field-detection-box" style={roiStyle(roiForEvent(latestFieldDetection()))}>
                      <span>{labelFor(latestFieldDetection().type)}</span>
                    </div>
                  {:else}
                    <div class="field-detection-label">
                      {labelFor(latestFieldDetection().type)}
                    </div>
                  {/if}
                {/if}
              </div>
            {:else}
              <div class="timeline-empty">Selecciona una camara para iniciar el campo de pruebas.</div>
            {/if}
          </div>

          <aside class="panel field-side">
            <h2>Detecciones recientes</h2>
            <p>Estas detecciones llegan del worker. Si hay ROI, se pinta sobre el vivo.</p>
            <div class="list">
              {#if fieldEvents.length}
                {#each fieldEvents as event}
                  <article class="item compact-event">
                    <span class:critical={isCritical(event.type)} class="badge">{labelFor(event.type)}</span>
                    <strong>{Math.round(event.confidence * 100)}% confianza</strong>
                    <p>{new Date(event.timestamp).toLocaleTimeString()}</p>
                    <p>{roiForEvent(event)?.source || "Sin ROI"}</p>
                  </article>
                {/each}
              {:else}
                <article class="item"><strong>Sin detecciones</strong><p>Abre el vivo o espera nuevas detecciones del worker.</p></article>
              {/if}
            </div>
          </aside>
        </section>
      {/if}

      {#if activeView === "ai_lab" && canLabel}
        <section class="admin-layout">
          <div class="panel">
            <h2>Datos de entrenamiento</h2>
            <p>Videos, eventos y etiquetas disponibles para preparar modelos.</p>
            <div class="metrics compact">
              <article><strong>{datasetStats?.recordings || 0}</strong><span>Videos/chunks</span></article>
              <article><strong>{datasetStats?.events || 0}</strong><span>Eventos</span></article>
              <article><strong>{datasetStats?.labels || 0}</strong><span>Etiquetas</span></article>
            </div>
            <div class="tag-list">
              {#each Object.entries(datasetStats?.categories || {}) as [key, count]}
                <span class:critical={isCritical(key)} class="badge">{labelFor(key)}: {count}</span>
              {/each}
            </div>
          </div>

          <div class="panel wide">
            <div class="panel-head">
              <div>
                <h2>Constructor visual de dataset</h2>
                <p>Busca evidencia a la izquierda, revisa al centro y gestiona seleccionados a la derecha. Ctrl + click o doble click agrega multiples.</p>
              </div>
              <span class="badge">{selectedDatasetEvents.length} seleccionados</span>
            </div>

            <section class="dataset-curator">
              <aside class="dataset-sidebar">
                <input bind:value={datasetSearch} placeholder="Buscar por camara, categoria o id" aria-label="Buscar evidencia" />
                <select bind:value={datasetCameraFilter} aria-label="Filtrar por camara">
                  <option value="">Todas las camaras</option>
                  {#each cameras as camera}
                    <option value={camera.id}>{camera.name} - {camera.source}</option>
                  {/each}
                </select>
                <select bind:value={datasetFilter} aria-label="Filtrar por categoria">
                  <option value="">Todas las categorias</option>
                  {#each eventTypes as type}
                    <option value={type}>{labelFor(type)}</option>
                  {/each}
                </select>
                <div class="dataset-toolbar compact-toolbar">
                  <button type="button" class="secondary" disabled={!datasetFilter} on:click={() => selectDatasetFilter(datasetFilter)}>Seleccionar visibles</button>
                  <button type="button" class="secondary" on:click={clearDatasetSelection}>Limpiar</button>
                </div>

                <div class="dataset-event-list">
                  {#each aiDatasetEvents as event}
                    <button
                      type="button"
                      class:selected={selectedDatasetEvents.includes(event.id)}
                      class:active={aiPreviewEvent?.id === event.id}
                      class="dataset-event-row"
                      on:click={(mouseEvent) => handleDatasetEventClick(mouseEvent, event)}
                      on:dblclick={() => toggleDatasetEvent(event.id)}
                    >
                      <span class:critical={isCritical(latestLabelForEvent(event))} class="badge">{labelFor(latestLabelForEvent(event))}</span>
                      <strong>{cameraForEvent(event)?.name || `Camara ${event.camera_id}`}</strong>
                      <small>{cameraForEvent(event)?.source || `ID ${event.camera_id}`}</small>
                      <small>{new Date(event.timestamp).toLocaleString()}</small>
                    </button>
                  {:else}
                    <div class="timeline-empty">Sin evidencia con esos filtros.</div>
                  {/each}
                </div>
              </aside>

              <div class="dataset-preview">
                {#if aiPreviewEvent}
                  <div class="dataset-preview-stage">
                    {#if evidenceUrl(aiPreviewEvent.image_path)}
                      <img src={evidenceUrl(aiPreviewEvent.image_path)} alt={labelFor(aiPreviewEvent.type)} />
                    {:else}
                      <img src={snapshotUrl({ id: aiPreviewEvent.camera_id })} alt={`Camara ${aiPreviewEvent.camera_id}`} />
                    {/if}
                    {#if roiForEvent(aiPreviewEvent)}
                      <div class="preview-roi" style={roiStyle(roiForEvent(aiPreviewEvent))}></div>
                    {/if}
                  </div>
                  <div class="dataset-preview-info">
                    <div>
                      <h3>{labelFor(latestLabelForEvent(aiPreviewEvent))}</h3>
                      <p>{cameraForEvent(aiPreviewEvent)?.name || `Camara ${aiPreviewEvent.camera_id}`} - {new Date(aiPreviewEvent.timestamp).toLocaleString()}</p>
                      <p>Prediccion original: {labelFor(aiPreviewEvent.type)}</p>
                      <p>{roiForEvent(aiPreviewEvent)?.source || "Sin ROI registrado para esta evidencia"}</p>
                    </div>
                    <div class="correction-tools">
                      <label>
                        Etiqueta correcta
                        <select bind:value={aiCorrectedLabel}>
                          {#each eventTypes as type}
                            <option value={type}>{labelFor(type)}</option>
                          {/each}
                        </select>
                      </label>
                      <button type="button" class="secondary" on:click={() => saveCorrectedLabel(aiPreviewEvent)}>Guardar correccion</button>
                      <button type="button" on:click={() => toggleDatasetEvent(aiPreviewEvent.id)}>
                        {selectedDatasetEvents.includes(aiPreviewEvent.id) ? "Quitar del dataset" : "Agregar al dataset"}
                      </button>
                    </div>
                  </div>
                {:else}
                  <div class="timeline-empty">Selecciona una evidencia para revisarla.</div>
                {/if}
              </div>

              <aside class="dataset-selected-panel">
                <div class="selected-panel-head">
                  <div>
                    <h3>Dentro del dataset</h3>
                    <p>{selectedDatasetEvents.length} evidencias</p>
                  </div>
                  <button type="button" class="secondary" on:click={clearDatasetSelection}>Vaciar</button>
                </div>

                <div class="selected-dataset-list">
                  {#each selectedDatasetEventObjects() as selectedEvent}
                    <article class:active={aiPreviewEvent?.id === selectedEvent.id} class="selected-dataset-item">
                      <button type="button" class="selected-thumb" on:click={() => selectAiEvent(selectedEvent)}>
                        {#if evidenceUrl(selectedEvent.image_path)}
                          <img src={evidenceUrl(selectedEvent.image_path)} alt={labelFor(latestLabelForEvent(selectedEvent))} />
                        {:else}
                          <img src={snapshotUrl({ id: selectedEvent.camera_id })} alt={`Camara ${selectedEvent.camera_id}`} />
                        {/if}
                      </button>
                      <div>
                        <strong>{cameraForEvent(selectedEvent)?.name || `Camara ${selectedEvent.camera_id}`}</strong>
                        <small>Original: {labelFor(selectedEvent.type)}</small>
                        <select value={latestLabelForEvent(selectedEvent)} on:change={(event) => saveEventLabel(selectedEvent, event.currentTarget.value)} aria-label="Categoria de evidencia seleccionada">
                          {#each eventTypes as type}
                            <option value={type}>{labelFor(type)}</option>
                          {/each}
                        </select>
                      </div>
                      <button type="button" class="secondary" on:click={() => toggleDatasetEvent(selectedEvent.id)}>Quitar</button>
                    </article>
                  {:else}
                    <div class="timeline-empty">Usa Ctrl + click o doble click para agregar evidencias.</div>
                  {/each}
                </div>
              </aside>
            </section>

            {#if canLabel}
              <form class="dataset-create" on:submit|preventDefault={createDataset}>
                <input bind:value={datasetName} placeholder="Dataset pantalla negra v1" aria-label="Nombre del dataset" />
                <input bind:value={datasetDescription} placeholder="Notas: prueba nocturna, TV sala, muestra balanceada" aria-label="Descripcion del dataset" />
                <button type="submit">Guardar dataset</button>
              </form>
              {#if parentDatasetId}
                <div class="derived-note">
                  <span>{parentDatasetLabel()}</span>
                  <button type="button" class="secondary" on:click={() => (parentDatasetId = null)}>Quitar origen</button>
                </div>
              {/if}
              <div class="bulk-label-bar">
                <span>{selectedDatasetEvents.length} evidencias seleccionadas</span>
                <select bind:value={bulkDatasetLabel} aria-label="Categoria masiva">
                  {#each eventTypes as type}
                    <option value={type}>{labelFor(type)}</option>
                  {/each}
                </select>
                <button type="button" class="secondary" disabled={!selectedDatasetEvents.length} on:click={applyBulkLabel}>Aplicar categoria</button>
              </div>
            {/if}
          </div>

          <div class="panel wide">
            <h2>Datasets guardados</h2>
            <div class="list">
              {#if datasets.length}
                {#each datasets as dataset}
                  <article class="item model-item">
                    <div>
                      <strong>{dataset.name}</strong>
                      <p>{dataset.version}</p>
                      {#if dataset.parent_dataset_id}<p>Derivado de dataset #{dataset.parent_dataset_id}</p>{/if}
                      <p>{dataset.description || "Sin notas"} - {datasetSummary(dataset)}</p>
                    </div>
                    <div class="row-actions">
                      <span class="badge">{dataset.event_ids.length} clips</span>
                      <button type="button" on:click={() => loadDatasetIntoBuilder(dataset)}>Cargar al constructor</button>
                      <button type="button" class="secondary" on:click={() => mergeDatasetIntoBuilder(dataset)}>Combinar</button>
                    </div>
                  </article>
                {/each}
              {:else}
                <article class="item"><strong>Sin datasets</strong><p>Selecciona evidencia y guarda tu primer dataset.</p></article>
              {/if}
            </div>
          </div>

          {#if canTrain}
            <div class="panel">
              <h2>Nuevo entrenamiento</h2>
              <p>Genera una version con prefijo de proposito, epochs y fecha.</p>
              <form class="training-form" on:submit|preventDefault={trainModel}>
                <select bind:value={trainPurpose} aria-label="Uso del modelo">
                  <option value="event_classifier">Clasificador de sucesos</option>
                  <option value="ad_fingerprint">Fingerprint de anuncios</option>
                  <option value="roi_detector">Detector de pantalla</option>
                  <option value="quality_detector">Calidad de video</option>
                </select>
                <input bind:value={trainEpochs} type="number" min="1" max="100000" aria-label="Epochs" />
                <select bind:value={trainDatasetId} aria-label="Dataset de entrenamiento">
                  <option value="">Usar todos los datos etiquetados</option>
                  {#each datasets as dataset}
                    <option value={dataset.id}>{dataset.name} - {dataset.event_ids.length} clips</option>
                  {/each}
                </select>
                <input bind:value={trainNotes} placeholder="Notas del entrenamiento" aria-label="Notas" />
                <label class="check-row">
                  <input bind:checked={trainActivate} type="checkbox" />
                  Activar al terminar
                </label>
                <button type="submit">Entrenar modelo</button>
              </form>
            </div>

            <div class="panel">
              <h2>Registrar artefacto</h2>
              <p>Agrega modelos externos, checkpoints o versiones ya entrenadas.</p>
              <form class="training-form" on:submit|preventDefault={registerModel}>
                <input bind:value={modelName} placeholder="Nombre visible" aria-label="Nombre del modelo" />
                <select bind:value={modelPurpose} aria-label="Uso del artefacto">
                  <option value="event_classifier">Clasificador de sucesos</option>
                  <option value="ad_fingerprint">Fingerprint de anuncios</option>
                  <option value="roi_detector">Detector de pantalla</option>
                  <option value="quality_detector">Calidad de video</option>
                </select>
                <input bind:value={modelVersion} placeholder="version opcional: event_classifier_e0010_20260415_153000" aria-label="Version" />
                <input bind:value={modelPath} placeholder="/data/models/.../model.pt" aria-label="Ruta del artefacto" />
                <input bind:value={modelEpochs} type="number" min="1" placeholder="Epochs" aria-label="Epochs del artefacto" />
                <input bind:value={modelAccuracy} type="number" min="0" max="1" step="0.001" placeholder="Accuracy 0.92" aria-label="Accuracy" />
                <label class="check-row">
                  <input bind:checked={modelActivate} type="checkbox" />
                  Activar
                </label>
                <button type="submit">Registrar modelo</button>
              </form>
            </div>
          {/if}

          <div class="panel wide">
            <h2>Versiones de modelos</h2>
            <p>Selecciona que artefacto usar para cada proposito.</p>
            <div class="list">
              {#if models.length}
                {#each models as model}
                  <article class="item model-item">
                    <div>
                      <strong>{model.name || model.version}</strong>
                      <p>{model.version}</p>
                      <p>{modelPurposeLabel(model.purpose)} - {model.path}</p>
                      <p>
                        Epochs {model.epochs || "n/a"} - Accuracy {model.accuracy === null || model.accuracy === undefined ? "n/a" : `${Math.round(model.accuracy * 1000) / 10}%`} - {new Date(model.created_at).toLocaleString()}
                      </p>
                    </div>
                    <div class="row-actions">
                      <span class:critical={model.active} class="badge">{modelStatusLabel(model)}</span>
                      {#if canTrain && !model.active}
                        <button type="button" on:click={() => activateModel(model)}>Usar este</button>
                      {/if}
                    </div>
                  </article>
                {/each}
              {:else}
                <article class="item"><strong>Sin modelos</strong><p>Aun no hay artefactos registrados.</p></article>
              {/if}
            </div>
          </div>
        </section>
      {/if}

      {#if activeView === "sources" && canConfigure}
        <section class="admin-layout">
          <div class="panel">
            <h2>Agregar camara</h2>
            <p>Registra fuentes dinamicamente. Si la camara se mueve, recalibra la ROI para que los detectores miren la pantalla correcta.</p>
            <form class="camera-form" on:submit|preventDefault={addCamera}>
              <input bind:value={cameraName} placeholder="cam_01" aria-label="Nombre de camara" />
              <input bind:value={cameraSource} placeholder="rtsp://... o 0" aria-label="Fuente" />
              <input bind:value={cameraRoiX} type="number" min="0" max="1" step="0.01" placeholder="ROI x 0.10" aria-label="ROI x" />
              <input bind:value={cameraRoiY} type="number" min="0" max="1" step="0.01" placeholder="ROI y 0.15" aria-label="ROI y" />
              <input bind:value={cameraRoiWidth} type="number" min="0.01" max="1" step="0.01" placeholder="ROI ancho 0.80" aria-label="ROI ancho" />
              <input bind:value={cameraRoiHeight} type="number" min="0.01" max="1" step="0.01" placeholder="ROI alto 0.70" aria-label="ROI alto" />
              <button type="submit">Agregar</button>
            </form>
            <p class="hint">La ROI define la pantalla dentro de la camara. Puedes capturarla con el boton Calibrar ROI despues de tener un snapshot.</p>
          </div>

          <div class="panel wide">
            <h2>Fuentes registradas</h2>
            <p>Administra camaras, fuentes RTSP/locales y recalibracion visual de ROI.</p>
            <div class="list">
              {#each cameras as camera}
                <article class="item">
                  {#if editingCameraId === camera.id}
                    <form class="camera-edit-form" on:submit|preventDefault={() => updateCamera(camera.id)}>
                      <input bind:value={editCameraName} aria-label="Nombre de camara" />
                      <input bind:value={editCameraSource} aria-label="Fuente de camara" />
                      <input bind:value={editCameraRoiX} type="number" min="0" max="1" step="0.01" placeholder="ROI x" aria-label="ROI x" />
                      <input bind:value={editCameraRoiY} type="number" min="0" max="1" step="0.01" placeholder="ROI y" aria-label="ROI y" />
                      <input bind:value={editCameraRoiWidth} type="number" min="0.01" max="1" step="0.01" placeholder="ROI ancho" aria-label="ROI ancho" />
                      <input bind:value={editCameraRoiHeight} type="number" min="0.01" max="1" step="0.01" placeholder="ROI alto" aria-label="ROI alto" />
                      <label class="check-row">
                        <input bind:checked={editCameraEnabled} type="checkbox" />
                        Activa
                      </label>
                      <button type="submit">Guardar</button>
                      <button type="button" class="secondary" on:click={cancelEditCamera}>Cancelar</button>
                    </form>
                  {:else}
                    <div class="camera-row">
                      <div>
                        <strong>{camera.name}</strong>
                        <p>{camera.source}</p>
                        {#if camera.roi_width && camera.roi_height}
                          <p>ROI pantalla: x {camera.roi_x}, y {camera.roi_y}, ancho {camera.roi_width}, alto {camera.roi_height}</p>
                        {:else}
                          <p>ROI pantalla: frame completo</p>
                        {/if}
                        <span class:warn={!camera.enabled} class="badge">{camera.enabled ? "Activa" : "Pausada"}</span>
                        {#if camera.locked_by_test_id}
                          <span class="badge lock">En prueba: {camera.locked_by_test_name}</span>
                        {/if}
                      </div>
                      {#if canConfigure}
                        <div class="row-actions">
                          <button type="button" class="secondary" on:click={() => startRoiCalibration(camera)}>Recalibrar ROI</button>
                          {#if camera.locked_by_test_id}
                            <button type="button" class="secondary" disabled>Bloqueada</button>
                          {:else}
                            <button type="button" on:click={() => startEditCamera(camera)}>Editar</button>
                            {#if camera.enabled}
                              <button type="button" class="secondary" on:click={() => setCameraEnabled(camera.id, false)}>Pausar</button>
                              <button type="button" class="danger" on:click={() => disableCamera(camera.id)}>Borrar</button>
                            {:else}
                              <button type="button" on:click={() => setCameraEnabled(camera.id, true)}>Reactivar</button>
                            {/if}
                          {/if}
                        </div>
                      {/if}
                    </div>
                  {/if}
                </article>
              {/each}
            </div>
          </div>
        </section>
      {/if}

      {#if activeView === "users" && canConfigure}
        <section class="admin-layout">
          <div class="panel">
            <h2>Usuarios y roles</h2>
            <p>Crea accesos con opciones visibles segun permisos.</p>
            <form class="user-form" on:submit|preventDefault={createUser}>
              <input bind:value={newUserEmail} type="email" placeholder="usuario@empresa.com" aria-label="Email de usuario" />
              <input bind:value={newUserPassword} type="password" placeholder="password temporal" aria-label="Password de usuario" />
              <select bind:value={newUserRole} aria-label="Rol de usuario">
                <option value="viewer">Viewer</option>
                <option value="analyst">Analista</option>
                <option value="supervisor">Supervisor</option>
                <option value="admin">Admin</option>
              </select>
              <button type="submit">Crear usuario</button>
            </form>
          </div>
        </section>
      {/if}

      {#if activeView === "system" && (canConfigure || canTrain)}
        <section class="admin-layout">
          {#if canConfigure}
            <div class="panel">
              <h2>Categorias IA</h2>
              <p>Crea sucesos que luego podran usarse como etiquetas para entrenamiento.</p>
              <form class="user-form" on:submit|preventDefault={createCategory}>
                <input bind:value={categoryKey} placeholder="audio_desync" aria-label="Clave de categoria" />
                <input bind:value={categoryName} placeholder="Audio desincronizado" aria-label="Nombre de categoria" />
                <input bind:value={categoryDescription} placeholder="Descripcion" aria-label="Descripcion de categoria" />
                <label class="check-row">
                  <input bind:checked={categoryCritical} type="checkbox" />
                  Critica
                </label>
                <button type="submit">Crear categoria</button>
              </form>
              <div class="tag-list">
                {#each categories as category}
                  <span class:critical={category.critical} class="badge">{category.name}</span>
                {/each}
              </div>
            </div>
          {/if}

          {#if canTrain}
            <div class="panel">
              <h2>Entrenamiento</h2>
              <p>Disponible para admin y supervisor.</p>
              <button type="button" on:click={trainModel}>Enviar entrenamiento</button>
            </div>
          {/if}
        </section>
      {/if}
    </section>
  {/if}

  {#if toastMessage}
    <div class="toast">{toastMessage}</div>
  {/if}

  {#if roiCamera}
    <div class="modal-backdrop">
      <section class="roi-modal">
        <div class="panel-head">
          <div>
            <h2>Calibrar pantalla</h2>
            <p>Arrastra sobre la imagen para marcar solo el contenido que se debe analizar.</p>
          </div>
          <button type="button" class="secondary" on:click={closeRoiCalibration}>Cerrar</button>
        </div>

        <div
          class="roi-canvas"
          role="application"
          on:pointerdown={startRoiDrag}
          on:pointermove={updateRoiDrag}
          on:pointerup={stopRoiDrag}
          on:pointercancel={stopRoiDrag}
        >
          <img src={snapshotUrl(roiCamera)} alt={`Snapshot de ${roiCamera.name}`} />
          <div class="roi-box" style={roiBoxStyle()}></div>
        </div>

        <p class="hint">
          ROI actual: x {roiBox.x.toFixed(3)}, y {roiBox.y.toFixed(3)}, ancho {roiBox.width.toFixed(3)}, alto {roiBox.height.toFixed(3)}
        </p>

        <div class="roi-actions">
          <button type="button" class="secondary" on:click={() => suggestRoiFromSnapshot(roiCamera)}>Sugerir pantalla</button>
          <button type="button" class="secondary" on:click={useCenteredRoi}>Marco central</button>
          <button type="button" class="secondary" on:click={clearRoiCalibration}>Usar frame completo</button>
          <button type="button" on:click={saveRoiCalibration}>Guardar ROI</button>
        </div>
      </section>
    </div>
  {/if}
</main>
