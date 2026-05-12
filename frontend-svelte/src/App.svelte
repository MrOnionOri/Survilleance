<script>
  import { onDestroy, tick } from "svelte";

  const API_URL = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`;
  const defaultEventTypes = ["normal", "freeze", "black_screen", "buffering", "ad", "repeated_ad", "scene_change"];

  let token = localStorage.getItem("streamwatch_token") || "";
  let user = null;
  let cameras = [];
  let categories = [];
  let users = [];
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
  let cameraFps = 5;
  let cameraRotation = 0;
  let cameraFlipHorizontal = false;
  let cameraFlipVertical = false;
  let cameraBrightness = 0;
  let cameraContrast = 1;
  let cameraGamma = 1;
  let cameraRoiX = "";
  let cameraRoiY = "";
  let cameraRoiWidth = "";
  let cameraRoiHeight = "";
  let editingCameraId = null;
  let editCameraName = "";
  let editCameraSource = "";
  let editCameraEnabled = true;
  let editCameraFps = 5;
  let editCameraRotation = 0;
  let editCameraFlipHorizontal = false;
  let editCameraFlipVertical = false;
  let editCameraBrightness = 0;
  let editCameraContrast = 1;
  let editCameraGamma = 1;
  let editCameraRoiX = "";
  let editCameraRoiY = "";
  let editCameraRoiWidth = "";
  let editCameraRoiHeight = "";
  let categoryKey = "";
  let categoryName = "";
  let categoryDescription = "";
  let categoryCritical = false;
  let categoryActive = true;
  let editingCategoryId = null;
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
  let datasetEventCache = [];
  let aiDatasetEvents = [];
  let aiPreviewEvent = null;
  let selectedDatasetEventDetails = [];
  let fieldCameraId = "";
  let fieldPurpose = "event_classifier";
  let fieldEvents = [];
  let fieldCamera = null;
  let fieldCameraIds = [];
  let fieldPolling = null;
  let newUserEmail = "";
  let newUserPassword = "";
  let newUserRole = "viewer";
  let newUserActive = true;
  let newUserMustChangePassword = true;
  let editingUserId = null;
  let editUserRole = "viewer";
  let editUserActive = true;
  let editUserMustChangePassword = false;
  let resetPasswordUserId = null;
  let resetPasswordValue = "";
  let resetPasswordMustChange = true;
  let currentPassword = "";
  let nextPassword = "";
  let confirmNextPassword = "";
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
  let liveStreams = {};
  let liveVideoElements = {};
  let liveVideoUrls = {};
  let liveFallbackUrls = {};
  let liveRestartAttempts = {};
  let liveSessionIds = {};
  let roiCamera = null;
  let tuningCamera = null;
  let tuningSaveTimer = null;
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
  $: eventTypes = categories.length ? categories.filter((category) => category.active !== false).map((category) => category.key) : defaultEventTypes;
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
    datasetEventCache;
    selectedDatasetEventDetails;
    const availableEvents = dedupeEvents([...aiDatasetEvents, ...datasetEventCache, ...selectedDatasetEventDetails]);
    const previewId = normalizeId(selectedAiEventId);
    aiPreviewEvent = availableEvents.find((event) => event.id === previewId) || selectedDatasetEventDetails[0] || availableEvents[0] || null;
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

  function normalizeId(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalizeEventIds(eventIds = []) {
    return Array.from(
      new Set(
        eventIds
          .map((value) => normalizeId(value))
          .filter((value) => value !== null),
      ),
    );
  }

  function dedupeEvents(list = []) {
    return Array.from(new Map(list.filter(Boolean).map((event) => [normalizeId(event.id), event])).values());
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
    if (user.must_change_password) {
      cameras = [];
      categories = [];
      events = [];
      recordingStatuses = [];
      tests = [];
      datasets = [];
      models = [];
      users = [];
      return;
    }
    cameras = await api(`/cameras${user?.role === "admin" ? "?include_disabled=true" : ""}`);
    categories = await api("/categories?include_disabled=true");
    events = await api(`/events${eventFilter ? `?type=${eventFilter}` : ""}`);
    recordingStatuses = await api("/recordings/status");
    tests = await api("/tests");
    if (user?.role === "admin") {
      users = await api("/users");
    }
    if (["admin", "supervisor", "analyst"].includes(user?.role)) {
      datasetStats = await api("/dataset/stats");
      datasets = await api("/datasets");
      models = await api("/models");
      fieldCameraIds = (await api("/field-tests/cameras")).camera_ids || [];
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

  function visualSettingsPayload(prefix = "") {
    if (prefix === "edit") {
      return {
        rotation_degrees: Number(editCameraRotation),
        flip_horizontal: Boolean(editCameraFlipHorizontal),
        flip_vertical: Boolean(editCameraFlipVertical),
        digital_brightness: Number(editCameraBrightness),
        digital_contrast: Number(editCameraContrast),
        digital_gamma: Number(editCameraGamma),
      };
    }
    if (prefix === "tuning" && tuningCamera) {
      return {
        rotation_degrees: Number(tuningCamera.rotation_degrees || 0),
        flip_horizontal: Boolean(tuningCamera.flip_horizontal),
        flip_vertical: Boolean(tuningCamera.flip_vertical),
        digital_brightness: Number(tuningCamera.digital_brightness || 0),
        digital_contrast: Number(tuningCamera.digital_contrast || 1),
        digital_gamma: Number(tuningCamera.digital_gamma || 1),
      };
    }
    return {
      rotation_degrees: Number(cameraRotation),
      flip_horizontal: Boolean(cameraFlipHorizontal),
      flip_vertical: Boolean(cameraFlipVertical),
      digital_brightness: Number(cameraBrightness),
      digital_contrast: Number(cameraContrast),
      digital_gamma: Number(cameraGamma),
    };
  }

  function normalizeCameraSettings(camera) {
    return {
      ...camera,
      rotation_degrees: camera.rotation_degrees ?? 0,
      flip_horizontal: Boolean(camera.flip_horizontal),
      flip_vertical: Boolean(camera.flip_vertical),
      digital_brightness: camera.digital_brightness ?? 0,
      digital_contrast: camera.digital_contrast ?? 1,
      digital_gamma: camera.digital_gamma ?? 1,
    };
  }

  function visualSettingsSummary(camera) {
    const rotation = camera.rotation_degrees ?? 0;
    const flips = [
      camera.flip_horizontal ? "H" : "",
      camera.flip_vertical ? "V" : "",
    ].filter(Boolean).join("/");
    const brightness = camera.digital_brightness ?? 0;
    const contrast = camera.digital_contrast ?? 1;
    const gamma = camera.digital_gamma ?? 1;
    return `Rot ${rotation} grados${flips ? ` - Flip ${flips}` : ""} - Brillo ${brightness} - Contraste ${contrast} - Gamma ${gamma}`;
  }

  function liveVisibleOutsideTuning(cameraId) {
    return liveVideoUrls[cameraId] && tuningCamera?.id !== cameraId;
  }

  function nextLiveSession(cameraId) {
    const nextSessionId = (liveSessionIds[cameraId] || 0) + 1;
    liveSessionIds = { ...liveSessionIds, [cameraId]: nextSessionId };
    return nextSessionId;
  }

  function isCurrentLiveSession(cameraId, sessionId) {
    return liveSessionIds[cameraId] === sessionId && liveStreams[cameraId]?.sessionId === sessionId;
  }

  function changeView(viewId) {
    activeView = viewId;
    if (!["cameras", "field_test"].includes(viewId)) {
      stopAllLive();
    }
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
        body: JSON.stringify({ name: cameraName, source: cameraSource, enabled: true, capture_fps: Number(cameraFps), ...visualSettingsPayload(), ...roiPayload() }),
      });
      cameraName = "";
      cameraSource = "";
      cameraFps = 5;
      cameraRotation = 0;
      cameraFlipHorizontal = false;
      cameraFlipVertical = false;
      cameraBrightness = 0;
      cameraContrast = 1;
      cameraGamma = 1;
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
    editCameraFps = camera.capture_fps ?? 5;
    editCameraRotation = camera.rotation_degrees ?? 0;
    editCameraFlipHorizontal = Boolean(camera.flip_horizontal);
    editCameraFlipVertical = Boolean(camera.flip_vertical);
    editCameraBrightness = camera.digital_brightness ?? 0;
    editCameraContrast = camera.digital_contrast ?? 1;
    editCameraGamma = camera.digital_gamma ?? 1;
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
    editCameraFps = 5;
    editCameraRotation = 0;
    editCameraFlipHorizontal = false;
    editCameraFlipVertical = false;
    editCameraBrightness = 0;
    editCameraContrast = 1;
    editCameraGamma = 1;
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
          capture_fps: Number(editCameraFps),
          ...visualSettingsPayload("edit"),
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
        body: JSON.stringify({
          email: newUserEmail,
          password: newUserPassword,
          role: newUserRole,
          active: newUserActive,
          must_change_password: newUserMustChangePassword,
        }),
      });
      newUserEmail = "";
      newUserPassword = "";
      newUserRole = "viewer";
      newUserActive = true;
      newUserMustChangePassword = true;
      await hydrate();
      notify("Usuario creado");
    } catch (error) {
      notify(error.message);
    }
  }

  function editUser(targetUser) {
    editingUserId = targetUser.id;
    editUserRole = targetUser.role;
    editUserActive = Boolean(targetUser.active);
    editUserMustChangePassword = Boolean(targetUser.must_change_password);
  }

  function cancelUserEdit() {
    editingUserId = null;
    editUserRole = "viewer";
    editUserActive = true;
    editUserMustChangePassword = false;
  }

  async function updateUser(targetUser) {
    if (!canConfigure) return;
    try {
      await api(`/users/${targetUser.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          role: editUserRole,
          active: editUserActive,
          must_change_password: editUserMustChangePassword,
        }),
      });
      cancelUserEdit();
      await hydrate();
      notify("Usuario actualizado");
    } catch (error) {
      notify(error.message);
    }
  }

  function openPasswordReset(targetUser) {
    resetPasswordUserId = targetUser.id;
    resetPasswordValue = "";
    resetPasswordMustChange = true;
  }

  async function resetUserPassword() {
    if (!canConfigure || !resetPasswordUserId) return;
    try {
      await api(`/users/${resetPasswordUserId}/password`, {
        method: "POST",
        body: JSON.stringify({
          password: resetPasswordValue,
          must_change_password: resetPasswordMustChange,
        }),
      });
      resetPasswordUserId = null;
      resetPasswordValue = "";
      resetPasswordMustChange = true;
      await hydrate();
      notify("Password temporal asignado");
    } catch (error) {
      notify(error.message);
    }
  }

  async function changeOwnPassword() {
    if (nextPassword !== confirmNextPassword) {
      notify("La confirmacion no coincide");
      return;
    }
    try {
      user = await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: nextPassword,
        }),
      });
      currentPassword = "";
      nextPassword = "";
      confirmNextPassword = "";
      await hydrate();
      notify("Password actualizado");
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

  function resetCategoryForm() {
    editingCategoryId = null;
    categoryKey = "";
    categoryName = "";
    categoryDescription = "";
    categoryCritical = false;
    categoryActive = true;
  }

  function editCategory(category) {
    editingCategoryId = category.id;
    categoryKey = category.key;
    categoryName = category.name;
    categoryDescription = category.description || "";
    categoryCritical = Boolean(category.critical);
    categoryActive = category.active !== false;
  }

  async function saveCategory() {
    if (!canConfigure) return;
    try {
      const payload = {
        name: categoryName.trim(),
        description: categoryDescription || null,
        critical: categoryCritical,
        active: categoryActive,
      };
      if (editingCategoryId) {
        await api(`/categories/${editingCategoryId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await api("/categories", {
          method: "POST",
          body: JSON.stringify({
            key: categoryKey.trim(),
            ...payload,
          }),
        });
      }
      const wasEditing = Boolean(editingCategoryId);
      resetCategoryForm();
      await hydrate();
      notify(wasEditing ? "Categoria actualizada" : "Categoria creada");
    } catch (error) {
      notify(error.message);
    }
  }

  async function disableCategory(category) {
    if (!canConfigure) return;
    try {
      await api(`/categories/${category.id}`, { method: "DELETE" });
      if (editingCategoryId === category.id) resetCategoryForm();
      await hydrate();
      notify("Categoria dada de baja");
    } catch (error) {
      notify(error.message);
    }
  }

  async function reactivateCategory(category) {
    if (!canConfigure) return;
    try {
      await api(`/categories/${category.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active: true }),
      });
      await hydrate();
      notify("Categoria reactivada");
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

  async function startFieldCamera(camera, previousCameraId = Number(fieldCameraId)) {
    if (previousCameraId && previousCameraId !== camera.id) {
      stopLive(previousCameraId);
    }
    fieldCameraId = String(camera.id);
    await api(`/field-tests/cameras/${camera.id}`, { method: "POST" });
    fieldCameraIds = Array.from(new Set([...fieldCameraIds, camera.id]));
    startLive(camera);
    startFieldPolling();
    refreshFieldEvents();
    notify(`IA activa para ${camera.name}`);
  }

  async function startCameraFromViewer(camera) {
    if (canLabel) {
      await startFieldCamera(camera);
      return;
    }
    startLive(camera);
  }

  async function openLiveTuning(camera) {
    if (!canConfigure) return;
    stopLive(camera.id);
    tuningCamera = normalizeCameraSettings(camera);
    await tick();
    if (!isFieldCameraActive(camera.id)) {
      await startCameraFromViewer(camera);
    } else if (!liveSockets[camera.id]) {
      startLive(camera);
    }
  }

  async function closeLiveTuning(resumeLive = true) {
    const camera = tuningCamera;
    const wasLive = camera ? Boolean(liveSockets[camera.id]) : false;
    if (tuningSaveTimer) clearTimeout(tuningSaveTimer);
    tuningSaveTimer = null;
    if (camera) {
      stopLive(camera.id);
    }
    tuningCamera = null;
    if (resumeLive && camera && wasLive && activeView === "cameras") {
      await tick();
      startLive(camera);
    }
  }

  function scheduleLiveTuningSave() {
    if (!tuningCamera) return;
    if (tuningSaveTimer) clearTimeout(tuningSaveTimer);
    tuningSaveTimer = setTimeout(() => {
      saveLiveTuning().catch((error) => notify(error.message));
    }, 250);
  }

  async function saveLiveTuning() {
    if (!tuningCamera || !canConfigure) return;
    const updated = await api(`/cameras/${tuningCamera.id}`, {
      method: "PATCH",
      body: JSON.stringify(visualSettingsPayload("tuning")),
    });
    tuningCamera = normalizeCameraSettings({ ...tuningCamera, ...updated });
    cameras = cameras.map((camera) => (
      camera.id === updated.id
        ? { ...camera, ...updated, locked_by_test_id: camera.locked_by_test_id, locked_by_test_name: camera.locked_by_test_name }
        : camera
    ));
  }

  async function stopFieldCamera(cameraId = fieldCameraId) {
    if (cameraId) {
      const numericCameraId = Number(cameraId);
      await api(`/field-tests/cameras/${numericCameraId}`, { method: "DELETE" }).catch(() => null);
      fieldCameraIds = fieldCameraIds.filter((id) => id !== numericCameraId);
      stopLive(numericCameraId);
      notify("IA detenida para esta camara");
    }
    if (!fieldCameraIds.length || Number(cameraId) === Number(fieldCameraId)) {
      stopFieldPolling();
    }
  }

  function isFieldCameraActive(cameraId) {
    return fieldCameraIds.includes(Number(cameraId));
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
    const previousCameraId = Number(fieldCameraId);
    activeView = "field_test";
    startFieldCamera(camera, previousCameraId).catch((error) => notify(error.message));
  }

  function changeFieldCamera(event) {
    const previousCameraId = Number(fieldCameraId);
    const cameraId = Number(event.currentTarget.value);
    const camera = cameras.find((item) => item.id === cameraId);
    if (camera) startFieldCamera(camera, previousCameraId).catch((error) => notify(error.message));
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
    const normalizedEventId = normalizeId(eventId);
    if (normalizedEventId === null) return;
    selectedDatasetEvents = selectedDatasetEvents.includes(normalizedEventId)
      ? selectedDatasetEvents.filter((id) => id !== normalizedEventId)
      : [...selectedDatasetEvents, normalizedEventId];
    rebuildSelectedDatasetDetails(selectedDatasetEvents);
    selectedAiEventId = normalizedEventId;
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
    selectedDatasetEvents = normalizeEventIds(aiDatasetEvents.map((event) => event.id));
    rebuildSelectedDatasetDetails(selectedDatasetEvents);
  }

  function clearDatasetSelection() {
    selectedDatasetEvents = [];
    selectedDatasetEventDetails = [];
  }

  function rebuildSelectedDatasetDetails(eventIds = selectedDatasetEvents) {
    const normalizedIds = normalizeEventIds(eventIds);
    const availableEvents = dedupeEvents([...events, ...aiDatasetEvents, ...datasetEventCache, ...selectedDatasetEventDetails]);
    selectedDatasetEventDetails = normalizedIds
      .map((eventId) => availableEvents.find((event) => normalizeId(event.id) === eventId))
      .filter(Boolean);
  }

  async function ensureDatasetEvents(eventIds) {
    const normalizedIds = normalizeEventIds(eventIds);
    const knownIds = new Set(dedupeEvents([...events, ...aiDatasetEvents, ...datasetEventCache, ...selectedDatasetEventDetails]).map((event) => normalizeId(event.id)));
    const missingIds = normalizedIds.filter((eventId) => !knownIds.has(eventId));
    if (!missingIds.length) return;
    const loaded = await api(`/events?ids=${missingIds.join(",")}&limit=500`);
    datasetEventCache = dedupeEvents([...datasetEventCache, ...loaded]);
  }

  async function loadDatasetIntoBuilder(dataset) {
    const eventIds = normalizeEventIds(dataset.event_ids);
    await ensureDatasetEvents(eventIds);
    selectedDatasetEvents = eventIds;
    parentDatasetId = dataset.id;
    datasetName = `${dataset.name} derivado`;
    datasetDescription = `Derivado de ${dataset.version}${dataset.description ? ` - ${dataset.description}` : ""}`;
    rebuildSelectedDatasetDetails(eventIds);
    selectedAiEventId = eventIds[0] || null;
    notify(`Dataset cargado al constructor: ${dataset.name}`);
  }

  async function mergeDatasetIntoBuilder(dataset) {
    const eventIds = normalizeEventIds(dataset.event_ids);
    await ensureDatasetEvents(eventIds);
    selectedDatasetEvents = normalizeEventIds([...selectedDatasetEvents, ...eventIds]);
    parentDatasetId = parentDatasetId || dataset.id;
    rebuildSelectedDatasetDetails(selectedDatasetEvents);
    selectedAiEventId = selectedAiEventId || eventIds[0] || null;
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
      selectedDatasetEventDetails = [];
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
      await ensureDatasetEvents(selectedDatasetEvents);
      rebuildSelectedDatasetDetails();
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
      await ensureDatasetEvents(selectedDatasetEvents);
      rebuildSelectedDatasetDetails();
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

  function mjpegUrl(cameraId) {
    return `${API_URL}/cameras/${cameraId}/mjpeg?token=${encodeURIComponent(token)}&ts=${Date.now()}`;
  }

  function liveMimeType() {
    const candidates = [
      'video/mp4; codecs="avc1.42C01F"',
      'video/mp4; codecs="avc1.42C01E"',
      'video/mp4; codecs="avc1.42E01F"',
      'video/mp4; codecs="avc1.42E01E"',
      'video/mp4; codecs="avc1.42001F"',
    ];
    return candidates.find((candidate) => window.MediaSource?.isTypeSupported(candidate)) || "";
  }

  function isMp4InitSegment(bytes) {
    if (bytes.length < 8) return false;
    const marker = String.fromCharCode(bytes[4], bytes[5], bytes[6], bytes[7]);
    return marker === "ftyp";
  }

  function registerLiveVideo(node, cameraId) {
    liveVideoElements[cameraId] = node;
    const stream = liveStreams[cameraId];
    if (stream?.objectUrl) {
      node.src = stream.objectUrl;
      syncLivePlayback(node);
    }
    const markPlaying = () => {
      const activeStream = liveStreams[cameraId];
      if (activeStream) {
        activeStream.videoPlaying = true;
        if (activeStream.playbackWatchdog) clearTimeout(activeStream.playbackWatchdog);
        activeStream.playbackWatchdog = null;
      }
      const nextFallbacks = { ...liveFallbackUrls };
      delete nextFallbacks[cameraId];
      liveFallbackUrls = nextFallbacks;
    };
    node.addEventListener("loadeddata", markPlaying);
    node.addEventListener("playing", markPlaying);
    return {
      destroy() {
        node.removeEventListener("loadeddata", markPlaying);
        node.removeEventListener("playing", markPlaying);
        if (liveVideoElements[cameraId] === node) delete liveVideoElements[cameraId];
      },
    };
  }

  function attachLiveMediaSource(cameraId, stream) {
    const objectUrl = URL.createObjectURL(stream.mediaSource);
    stream.objectUrl = objectUrl;
    liveVideoUrls = { ...liveVideoUrls, [cameraId]: objectUrl };

    const video = liveVideoElements[cameraId];
    if (video) {
      video.src = objectUrl;
      syncLivePlayback(video);
    }

    stream.mediaSource.addEventListener("sourceopen", () => {
      try {
        stream.sourceBuffer = stream.mediaSource.addSourceBuffer(stream.mimeType);
        stream.sourceBuffer.mode = "segments";
        stream.sourceBuffer.addEventListener("updateend", () => flushLiveQueue(cameraId));
        flushLiveQueue(cameraId);
      } catch (error) {
        notify(error.message || "No se pudo iniciar el video en vivo");
      }
    });
  }

  function resetLiveMediaSource(cameraId, initSegment) {
    const stream = liveStreams[cameraId];
    if (!stream) return;
    const previousUrl = stream.objectUrl;
    const video = liveVideoElements[cameraId];
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
    if (stream.mediaSource?.readyState === "open") {
      try {
        stream.mediaSource.endOfStream();
      } catch {
        // The previous media source may already be closing.
      }
    }
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    stream.mediaSource = new MediaSource();
    stream.sourceBuffer = null;
    stream.queue = [initSegment];
    stream.receivedInit = true;
    attachLiveMediaSource(cameraId, stream);
  }

  function syncLivePlayback(video) {
    const playAtLiveEdge = () => {
      try {
        if (video.buffered.length) {
          const end = video.buffered.end(video.buffered.length - 1);
          const start = video.buffered.start(video.buffered.length - 1);
          if (end - video.currentTime > 2 || video.currentTime < start) {
            video.currentTime = Math.max(start, end - 0.25);
          }
        }
        video.play().catch(() => null);
      } catch {
        video.play().catch(() => null);
      }
    };
    video.addEventListener("loadedmetadata", playAtLiveEdge, { once: true });
    video.addEventListener("canplay", playAtLiveEdge, { once: true });
    setTimeout(playAtLiveEdge, 0);
  }

  function startLive(camera, resetAttempts = true) {
    stopLive(camera.id);
    const sessionId = nextLiveSession(camera.id);
    if (resetAttempts) {
      liveRestartAttempts = { ...liveRestartAttempts, [camera.id]: 0 };
    }
    const mimeType = liveMimeType();
    if (!mimeType) {
      notify("Este navegador no soporta video MP4 en vivo por MediaSource");
      return;
    }

    const mediaSource = new MediaSource();
    const stream = {
      sessionId,
      mediaSource,
      sourceBuffer: null,
      queue: [],
      objectUrl: "",
      mimeType,
      receivedInit: false,
      firstMediaReceived: false,
      videoPlaying: false,
      watchdog: null,
      playbackWatchdog: null,
    };
    liveStreams = { ...liveStreams, [camera.id]: stream };
    attachLiveMediaSource(camera.id, stream);
    stream.watchdog = setTimeout(() => {
      const activeStream = liveStreams[camera.id];
      if (isCurrentLiveSession(camera.id, sessionId) && activeStream && !activeStream.firstMediaReceived) {
        restartLive(camera.id, "El vivo no recibio fragmentos de video", sessionId);
      }
    }, 4500);
    stream.playbackWatchdog = setTimeout(() => {
      const activeStream = liveStreams[camera.id];
      if (isCurrentLiveSession(camera.id, sessionId) && activeStream && activeStream.firstMediaReceived && !activeStream.videoPlaying) {
        activateLiveFallback(camera.id);
      }
    }, 6500);

    const socket = new WebSocket(streamUrl(camera.id));
    socket.binaryType = "arraybuffer";
    socket.onmessage = (event) => {
      if (isCurrentLiveSession(camera.id, sessionId)) {
        enqueueLiveChunk(camera.id, event.data);
      }
    };
    socket.onopen = () => {
      if (isCurrentLiveSession(camera.id, sessionId)) notify("Video en vivo conectado");
    };
    socket.onerror = () => {
      if (isCurrentLiveSession(camera.id, sessionId)) notify("No se pudo conectar el stream del worker");
    };
    socket.onclose = () => {
      if (liveSockets[camera.id] === socket) {
        const nextSockets = { ...liveSockets };
        delete nextSockets[camera.id];
        liveSockets = nextSockets;
      }
    };
    liveSockets = { ...liveSockets, [camera.id]: socket };
  }

  function enqueueLiveChunk(cameraId, data) {
    const stream = liveStreams[cameraId];
    if (!stream) return;
    const bytes = new Uint8Array(data);
    if (isMp4InitSegment(bytes)) {
      if (stream.receivedInit) {
        resetLiveMediaSource(cameraId, bytes);
        return;
      }
      stream.receivedInit = true;
    } else {
      stream.firstMediaReceived = true;
      if (stream.watchdog) clearTimeout(stream.watchdog);
      stream.watchdog = null;
    }
    stream.queue.push(bytes);
    if (stream.queue.length > 120) stream.queue.splice(0, stream.queue.length - 120);
    flushLiveQueue(cameraId);
  }

  function flushLiveQueue(cameraId) {
    const stream = liveStreams[cameraId];
    if (!stream?.sourceBuffer || stream.sourceBuffer.updating || stream.mediaSource.readyState !== "open") return;
    const chunk = stream.queue.shift();
    if (!chunk) return;
    try {
      stream.sourceBuffer.appendBuffer(chunk);
    } catch (error) {
      stream.queue = [];
      restartLive(cameraId, error.message || "No se pudo decodificar el vivo");
    }
  }

  function restartLive(cameraId, reason, sessionId = liveStreams[cameraId]?.sessionId) {
    const camera = cameras.find((item) => item.id === Number(cameraId));
    const attempts = liveRestartAttempts[cameraId] || 0;
    if (!camera || !isCurrentLiveSession(cameraId, sessionId) || attempts >= 2) {
      if (reason) notify(reason);
      return;
    }
    liveRestartAttempts = { ...liveRestartAttempts, [cameraId]: attempts + 1 };
    setTimeout(() => {
      if (isCurrentLiveSession(cameraId, sessionId)) {
        startLive(camera, false);
      }
    }, 500);
  }

  function activateLiveFallback(cameraId) {
    liveFallbackUrls = { ...liveFallbackUrls, [cameraId]: mjpegUrl(cameraId) };
  }

  function stopLive(cameraId) {
    const socket = liveSockets[cameraId];
    if (socket) {
      socket.close();
      const nextSockets = { ...liveSockets };
      delete nextSockets[cameraId];
      liveSockets = nextSockets;
    }
    const stream = liveStreams[cameraId];
    if (stream) {
      if (stream.watchdog) clearTimeout(stream.watchdog);
      if (stream.playbackWatchdog) clearTimeout(stream.playbackWatchdog);
      const video = liveVideoElements[cameraId];
      if (video) {
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
      if (stream.mediaSource.readyState === "open") {
        try {
          stream.mediaSource.endOfStream();
        } catch {
          // The stream may already be closing.
        }
      }
      URL.revokeObjectURL(stream.objectUrl);
      const nextStreams = { ...liveStreams };
      delete nextStreams[cameraId];
      liveStreams = nextStreams;
      const nextUrls = { ...liveVideoUrls };
      delete nextUrls[cameraId];
      liveVideoUrls = nextUrls;
      const nextFallbacks = { ...liveFallbackUrls };
      delete nextFallbacks[cameraId];
      liveFallbackUrls = nextFallbacks;
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

  function roleLabel(value) {
    return (
      {
        viewer: "Viewer",
        analyst: "Analista",
        supervisor: "Supervisor",
        admin: "Admin",
      }[value] || value
    );
  }

  function formatDateTime(value) {
    return value ? new Date(value).toLocaleString() : "Nunca";
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
    closeLiveTuning(false);
    stopFieldPolling();
    if (fieldCameraId) api(`/field-tests/cameras/${fieldCameraId}`, { method: "DELETE" }).catch(() => null);
    stopAllLive();
    token = "";
    user = null;
    users = [];
    localStorage.removeItem("streamwatch_token");
  }

  onDestroy(() => {
    closeLiveTuning(false);
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
  {:else if user.must_change_password}
    <section class="panel auth-panel">
      <div>
        <h2>Cambia tu password</h2>
        <p>Tu cuenta tiene un password temporal. Actualizalo para continuar.</p>
      </div>
      <form class="form-row" on:submit|preventDefault={changeOwnPassword}>
        <input bind:value={currentPassword} type="password" placeholder="Password actual" aria-label="Password actual" />
        <input bind:value={nextPassword} type="password" placeholder="Nuevo password" aria-label="Nuevo password" />
        <input bind:value={confirmNextPassword} type="password" placeholder="Confirmar nuevo password" aria-label="Confirmar nuevo password" />
        <button type="submit">Actualizar password</button>
      </form>
    </section>
  {:else}
    <section class="workspace">
      <nav class="tabs" aria-label="Secciones">
        {#each visibleViews as view}
          <button type="button" class:active={activeView === view.id} on:click={() => changeView(view.id)}>{view.label}</button>
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
                    {#if liveFallbackUrls[camera.id] && tuningCamera?.id !== camera.id}
                      <img src={liveFallbackUrls[camera.id]} alt={`${camera.name} en vivo`} />
                    {:else if liveVisibleOutsideTuning(camera.id)}
                      <video use:registerLiveVideo={camera.id} muted playsinline autoplay></video>
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
                        <button type="button" on:click={() => startCameraFromViewer(camera).catch((error) => notify(error.message))}>
                          {canLabel && !isFieldCameraActive(camera.id) ? "Activar vivo" : "Ver en vivo"}
                        </button>
                      {/if}
                      {#if canLabel}
                        {#if isFieldCameraActive(camera.id)}
                          <button type="button" class="secondary" on:click={() => stopFieldCamera(camera.id)}>Detener IA</button>
                        {:else}
                          <button type="button" class="secondary" on:click={() => startFieldCamera(camera).catch((error) => notify(error.message))}>Activar IA</button>
                        {/if}
                        <button type="button" on:click={() => openEditor(camera.id)}>Editar video</button>
                      {/if}
                      {#if canConfigure}
                        <button type="button" class="secondary" on:click={() => openLiveTuning(camera).catch((error) => notify(error.message))}>Ajustar vivo</button>
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
                <select value={fieldCameraId} on:change={changeFieldCamera}>
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
                {#if liveFallbackUrls[fieldCamera.id] && tuningCamera?.id !== fieldCamera.id}
                  <img src={liveFallbackUrls[fieldCamera.id]} alt={`${fieldCamera.name} en vivo`} />
                {:else if liveVisibleOutsideTuning(fieldCamera.id)}
                  <video use:registerLiveVideo={fieldCamera.id} muted playsinline autoplay></video>
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
                  {#each selectedDatasetEventDetails as selectedEvent}
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
                      <button type="button" on:click={() => loadDatasetIntoBuilder(dataset).catch((error) => notify(error.message))}>Cargar al constructor</button>
                      <button type="button" class="secondary" on:click={() => mergeDatasetIntoBuilder(dataset).catch((error) => notify(error.message))}>Combinar</button>
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
              <input bind:value={cameraFps} type="number" min="1" max="60" step="1" placeholder="FPS 5" aria-label="FPS de captura" />
              <select bind:value={cameraRotation} aria-label="Rotacion de imagen">
                <option value={0}>Rotacion 0 grados</option>
                <option value={90}>Rotacion 90 grados</option>
                <option value={180}>Rotacion 180 grados</option>
                <option value={270}>Rotacion 270 grados</option>
              </select>
              <label class="check-row">
                <input bind:checked={cameraFlipHorizontal} type="checkbox" />
                Espejo horizontal
              </label>
              <label class="check-row">
                <input bind:checked={cameraFlipVertical} type="checkbox" />
                Espejo vertical
              </label>
              <input bind:value={cameraBrightness} type="number" min="-100" max="100" step="1" placeholder="Brillo 0" aria-label="Brillo digital" />
              <input bind:value={cameraContrast} type="number" min="0.1" max="3" step="0.05" placeholder="Contraste 1" aria-label="Contraste digital" />
              <input bind:value={cameraGamma} type="number" min="0.2" max="3" step="0.05" placeholder="Gamma 1" aria-label="Gamma digital" />
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
                      <input bind:value={editCameraFps} type="number" min="1" max="60" step="1" placeholder="FPS" aria-label="FPS de captura" />
                      <select bind:value={editCameraRotation} aria-label="Rotacion de imagen">
                        <option value={0}>Rotacion 0 grados</option>
                        <option value={90}>Rotacion 90 grados</option>
                        <option value={180}>Rotacion 180 grados</option>
                        <option value={270}>Rotacion 270 grados</option>
                      </select>
                      <label class="check-row">
                        <input bind:checked={editCameraFlipHorizontal} type="checkbox" />
                        Espejo horizontal
                      </label>
                      <label class="check-row">
                        <input bind:checked={editCameraFlipVertical} type="checkbox" />
                        Espejo vertical
                      </label>
                      <input bind:value={editCameraBrightness} type="number" min="-100" max="100" step="1" placeholder="Brillo" aria-label="Brillo digital" />
                      <input bind:value={editCameraContrast} type="number" min="0.1" max="3" step="0.05" placeholder="Contraste" aria-label="Contraste digital" />
                      <input bind:value={editCameraGamma} type="number" min="0.2" max="3" step="0.05" placeholder="Gamma" aria-label="Gamma digital" />
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
                        <p>Captura: {camera.capture_fps || 5} FPS</p>
                        <p>{visualSettingsSummary(camera)}</p>
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
                          <button type="button" class="secondary" on:click={() => openLiveTuning(camera).catch((error) => notify(error.message))}>Ajustar vivo</button>
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
            <p>Crea accesos, revisa sesiones y administra permisos sin borrar usuarios.</p>
            <form class="user-form" on:submit|preventDefault={createUser}>
              <input bind:value={newUserEmail} type="email" placeholder="usuario@empresa.com" aria-label="Email de usuario" />
              <input bind:value={newUserPassword} type="password" placeholder="password temporal" aria-label="Password de usuario" />
              <select bind:value={newUserRole} aria-label="Rol de usuario">
                <option value="viewer">Viewer</option>
                <option value="analyst">Analista</option>
                <option value="supervisor">Supervisor</option>
                <option value="admin">Admin</option>
              </select>
              <label class="check-row">
                <input bind:checked={newUserActive} type="checkbox" />
                Activo
              </label>
              <label class="check-row">
                <input bind:checked={newUserMustChangePassword} type="checkbox" />
                Forzar cambio al iniciar
              </label>
              <button type="submit">Crear usuario</button>
            </form>
          </div>

          <div class="panel wide">
            <h2>Usuarios registrados</h2>
            <p>La baja desactiva el acceso, pero conserva etiquetas, auditoria y eventos asociados.</p>
            <div class="list">
              {#each users as managedUser}
                <article class="item model-item">
                  <div>
                    <strong>{managedUser.email}</strong>
                    <p>
                      {roleLabel(managedUser.role)} - {managedUser.session_count || 0} sesiones - Ultima sesion: {formatDateTime(managedUser.last_login_at)}
                    </p>
                    <p>
                      Creado: {formatDateTime(managedUser.created_at)} - Password: {formatDateTime(managedUser.password_changed_at)}
                    </p>
                  </div>
                  <div class="row-actions">
                    <span class:warn={!managedUser.active} class="badge">{managedUser.active ? "Activo" : "Baja"}</span>
                    <span class:critical={managedUser.must_change_password} class="badge">
                      {managedUser.must_change_password ? "Cambio requerido" : "Password vigente"}
                    </span>
                    {#if editingUserId === managedUser.id}
                      <select bind:value={editUserRole} aria-label="Rol de usuario">
                        <option value="viewer">Viewer</option>
                        <option value="analyst">Analista</option>
                        <option value="supervisor">Supervisor</option>
                        <option value="admin">Admin</option>
                      </select>
                      <label class="check-row">
                        <input bind:checked={editUserActive} type="checkbox" />
                        Activo
                      </label>
                      <label class="check-row">
                        <input bind:checked={editUserMustChangePassword} type="checkbox" />
                        Forzar cambio
                      </label>
                      <button type="button" on:click={() => updateUser(managedUser)}>Guardar</button>
                      <button type="button" class="secondary" on:click={cancelUserEdit}>Cancelar</button>
                    {:else}
                      <button type="button" class="secondary" on:click={() => editUser(managedUser)}>Editar</button>
                      <button type="button" class="secondary" on:click={() => openPasswordReset(managedUser)}>Cambiar password</button>
                    {/if}
                  </div>
                </article>
              {:else}
                <article class="item"><strong>Sin usuarios</strong><p>Aun no hay usuarios registrados.</p></article>
              {/each}
            </div>
          </div>

          {#if resetPasswordUserId}
            <div class="panel">
              <h2>Cambiar password</h2>
              <p>Asigna un password temporal. Por seguridad, puedes forzar cambio al siguiente inicio.</p>
              <form class="user-form" on:submit|preventDefault={resetUserPassword}>
                <input bind:value={resetPasswordValue} type="password" placeholder="nuevo password temporal" aria-label="Nuevo password temporal" />
                <label class="check-row">
                  <input bind:checked={resetPasswordMustChange} type="checkbox" />
                  Forzar cambio al iniciar
                </label>
                <button type="submit">Guardar password</button>
                <button type="button" class="secondary" on:click={() => (resetPasswordUserId = null)}>Cancelar</button>
              </form>
            </div>
          {/if}
        </section>
      {/if}

      {#if activeView === "system" && (canConfigure || canTrain)}
        <section class="admin-layout">
          {#if canConfigure}
            <div class="panel">
              <h2>Categorias IA</h2>
              <p>Crea, edita o da de baja sucesos para entrenamiento sin borrar el historial.</p>
              <form class="user-form" on:submit|preventDefault={saveCategory}>
                <input bind:value={categoryKey} disabled={Boolean(editingCategoryId)} placeholder="audio_desync" aria-label="Clave de categoria" />
                <input bind:value={categoryName} placeholder="Audio desincronizado" aria-label="Nombre de categoria" />
                <input bind:value={categoryDescription} placeholder="Descripcion" aria-label="Descripcion de categoria" />
                <label class="check-row">
                  <input bind:checked={categoryCritical} type="checkbox" />
                  Critica
                </label>
                <label class="check-row">
                  <input bind:checked={categoryActive} type="checkbox" />
                  Activa
                </label>
                <button type="submit">{editingCategoryId ? "Guardar categoria" : "Crear categoria"}</button>
                {#if editingCategoryId}
                  <button type="button" class="secondary" on:click={resetCategoryForm}>Cancelar edicion</button>
                {/if}
              </form>
              <div class="list">
                {#each categories as category}
                  <article class="item model-item">
                    <div>
                      <strong>{category.name}</strong>
                      <p>{category.key}</p>
                      <p>{category.description || "Sin descripcion"}</p>
                    </div>
                    <div class="row-actions">
                      <span class:critical={category.critical} class="badge">{category.critical ? "Critica" : "Informativa"}</span>
                      <span class:warn={category.active === false} class="badge">{category.active === false ? "Baja" : "Activa"}</span>
                      <button type="button" class="secondary" on:click={() => editCategory(category)}>Editar</button>
                      {#if category.active === false}
                        <button type="button" on:click={() => reactivateCategory(category)}>Reactivar</button>
                      {:else}
                        <button type="button" class="secondary" on:click={() => disableCategory(category)}>Dar de baja</button>
                      {/if}
                    </div>
                  </article>
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

  {#if tuningCamera}
    <div class="modal-backdrop">
      <section class="roi-modal live-tuning-modal">
        <div class="panel-head">
          <div>
            <h2>Ajustar vivo</h2>
            <p>{tuningCamera.name} - los cambios se guardan mientras ves la imagen.</p>
          </div>
          <button type="button" class="secondary" on:click={() => closeLiveTuning()}>Cerrar</button>
        </div>

        <div class="field-stage">
          {#if liveFallbackUrls[tuningCamera.id]}
            <img src={liveFallbackUrls[tuningCamera.id]} alt={`${tuningCamera.name} en vivo`} />
          {:else if liveVideoUrls[tuningCamera.id]}
            <video use:registerLiveVideo={tuningCamera.id} muted playsinline autoplay></video>
          {:else}
            <img src={snapshotUrl(tuningCamera)} alt={tuningCamera.name} />
          {/if}
        </div>

        <div class="camera-tuning-grid">
          <label>
            Rotacion
            <select bind:value={tuningCamera.rotation_degrees} on:change={scheduleLiveTuningSave}>
              <option value={0}>0 grados</option>
              <option value={90}>90 grados</option>
              <option value={180}>180 grados</option>
              <option value={270}>270 grados</option>
            </select>
          </label>
          <label class="check-row">
            <input bind:checked={tuningCamera.flip_horizontal} type="checkbox" on:change={scheduleLiveTuningSave} />
            Espejo horizontal
          </label>
          <label class="check-row">
            <input bind:checked={tuningCamera.flip_vertical} type="checkbox" on:change={scheduleLiveTuningSave} />
            Espejo vertical
          </label>
          <label>
            Brillo
            <input bind:value={tuningCamera.digital_brightness} type="number" min="-100" max="100" step="1" on:input={scheduleLiveTuningSave} />
          </label>
          <label>
            Contraste
            <input bind:value={tuningCamera.digital_contrast} type="number" min="0.1" max="3" step="0.05" on:input={scheduleLiveTuningSave} />
          </label>
          <label>
            Gamma
            <input bind:value={tuningCamera.digital_gamma} type="number" min="0.2" max="3" step="0.05" on:input={scheduleLiveTuningSave} />
          </label>
        </div>

        <p class="hint">El worker refresca estos ajustes cada segundo y los aplica antes de enviar vivo, detectar ROI y grabar chunks.</p>
      </section>
    </div>
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
