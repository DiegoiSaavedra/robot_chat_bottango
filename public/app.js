const elements = {
  logo: document.querySelector("#logo"),
  statusBadge: document.querySelector("#statusBadge"),
  connectButton: document.querySelector("#connectButton"),
  disconnectButton: document.querySelector("#disconnectButton"),
  muteButton: document.querySelector("#muteButton"),
  motionStatus: document.querySelector("#motionStatus"),
  motionDetail: document.querySelector("#motionDetail"),
  motionConnectButton: document.querySelector("#motionConnectButton"),
  motionDisconnectButton: document.querySelector("#motionDisconnectButton"),
  conversation: document.querySelector("#conversation"),
  configList: document.querySelector("#configList"),
  eventLog: document.querySelector("#eventLog"),
};

const DEFAULT_MOTION_CONFIG = Object.freeze({
  enabled: true,
  transport: "server-serial",
  activationMode: "response",
  serialPort: "COM6",
  baudRate: 115200,
  speakAnimationIndex: 0,
  autoConnectAuthorizedPort: true,
  audioThreshold: 0.045,
  silenceHoldMs: 280,
  responseAudioThreshold: 0.02,
  responseSilenceHoldMs: 1200,
  contextAnimations: [],
});

const textEncoder = new TextEncoder();

const state = {
  config: null,
  motionConfig: { ...DEFAULT_MOTION_CONFIG, contextAnimations: [] },
  peerConnection: null,
  dataChannel: null,
  localStream: null,
  remoteAudio: null,
  turns: new Map(),
  assistantText: new Map(),
  latestAssistantItemId: null,
  isMuted: false,
  motion: {
    port: null,
    writer: null,
    portLabel: "Sin puerto",
    isConnected: false,
    speakingDesired: false,
    animationActive: false,
    currentAnimationIndex: null,
    audioContext: null,
    analyser: null,
    analyserSource: null,
    analyserData: null,
    audioMonitorReady: false,
    belowThresholdSince: 0,
    responseStopPending: false,
    monitorFrameId: 0,
    fallbackStopTimer: 0,
    commandQueue: Promise.resolve(),
  },
};

function setStatus(label, tone = "idle") {
  elements.statusBadge.textContent = label;
  elements.statusBadge.dataset.tone = tone;
}

function setMotionStatus(label, tone = "idle", detail = "") {
  elements.motionStatus.textContent = label;
  elements.motionStatus.dataset.tone = tone;
  elements.motionDetail.textContent = detail;
}

function usesServerSerial() {
  return state.motionConfig.transport === "server-serial";
}

function usesWebSerial() {
  return state.motionConfig.transport === "web-serial";
}

function usesResponseActivationMode() {
  return state.motionConfig.activationMode !== "audio";
}

function usesAudioActivationMode() {
  return state.motionConfig.activationMode === "audio";
}

function getMotionSilenceThreshold() {
  return usesResponseActivationMode()
    ? state.motionConfig.responseAudioThreshold
    : state.motionConfig.audioThreshold;
}

function getMotionSilenceHoldMs() {
  return usesResponseActivationMode()
    ? state.motionConfig.responseSilenceHoldMs
    : state.motionConfig.silenceHoldMs;
}

function refreshMotionStatus() {
  if (!state.motionConfig.enabled) {
    setMotionStatus(
      "Movimiento apagado",
      "idle",
      "Activa motion_control.enabled en el JSON si quieres mover el robot.",
    );
    return;
  }

  if (usesWebSerial() && !navigator.serial) {
    setMotionStatus(
      "Sin Web Serial",
      "error",
      "Usa Edge o Chrome sobre localhost para controlar el Arduino desde la interfaz.",
    );
    return;
  }

  if (state.motion.isConnected) {
    if (state.motion.animationActive && state.motion.currentAnimationIndex !== null) {
      setMotionStatus(
        `Animando #${state.motion.currentAnimationIndex}`,
        "busy",
        `${state.motion.portLabel} - siguiendo el audio del asistente.`,
      );
      return;
    }

    setMotionStatus(
      "Arduino listo",
      "ready",
      `${state.motion.portLabel} - esperando audio del asistente.`,
    );
    return;
  }

  setMotionStatus(
    "Arduino desconectado",
    "idle",
    usesServerSerial()
      ? `${state.motionConfig.serialPort} listo para conectar desde el servidor local.`
      : "Conecta el puerto serie para sincronizar la animacion de Bottango con la voz.",
  );
}

function updateMotionButtons() {
  const motionAvailable =
    state.motionConfig.enabled &&
    (usesServerSerial() || (usesWebSerial() && Boolean(navigator.serial)));
  elements.motionConnectButton.disabled = !motionAvailable || state.motion.isConnected;
  elements.motionDisconnectButton.disabled = !motionAvailable || !state.motion.isConnected;
}

function updateButtons() {
  const connected = Boolean(state.peerConnection);
  elements.connectButton.disabled = connected;
  elements.disconnectButton.disabled = !connected;
  elements.muteButton.disabled = !connected;
  elements.muteButton.textContent = state.isMuted ? "Activar micro" : "Silenciar";
  updateMotionButtons();
}

function addEvent(label, message) {
  const row = document.createElement("div");
  row.className = "event";
  const now = new Date();
  const time = now.toLocaleTimeString("es-UY", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  row.innerHTML = `
    <span class="event__time">${time}</span>
    <span class="event__label">${label}</span>
    <span class="event__message">${message}</span>
  `;

  elements.eventLog.prepend(row);

  while (elements.eventLog.children.length > 18) {
    elements.eventLog.removeChild(elements.eventLog.lastElementChild);
  }
}

function ensureTurn(id, role) {
  if (state.turns.has(id)) {
    return state.turns.get(id);
  }

  const article = document.createElement("article");
  article.className = `turn turn--${role}`;
  article.dataset.turnId = id;

  const meta = document.createElement("div");
  meta.className = "turn__meta";
  meta.innerHTML = `
    <span>${role === "assistant" ? "Asistente" : "Vos"}</span>
    <span>${new Date().toLocaleTimeString("es-UY", {
      hour: "2-digit",
      minute: "2-digit",
    })}</span>
  `;

  const text = document.createElement("p");
  text.className = "turn__text";
  text.textContent = role === "assistant" ? "Preparando respuesta..." : "Escuchando...";

  article.append(meta, text);
  elements.conversation.appendChild(article);

  const turn = { article, text, role };
  state.turns.set(id, turn);
  return turn;
}

function rememberAssistantText(id, content) {
  state.assistantText.set(id, content);
  state.latestAssistantItemId = id;
}

function setTurnText(id, role, content, pending = false) {
  const turn = ensureTurn(id, role);
  const resolvedContent = content || (role === "assistant" ? "Preparando respuesta..." : "Escuchando...");
  turn.text.textContent = resolvedContent;
  turn.article.classList.toggle("is-pending", pending);

  if (role === "assistant") {
    rememberAssistantText(id, resolvedContent);
  }
}

function appendTurnText(id, role, delta) {
  const turn = ensureTurn(id, role);
  const current = turn.text.textContent;
  const baseText =
    current === "Preparando respuesta..." || current === "Escuchando..." ? "" : current;
  const nextText = `${baseText}${delta}`;
  turn.text.textContent = nextText;
  turn.article.classList.add("is-pending");

  if (role === "assistant") {
    rememberAssistantText(id, nextText);
  }
}

function asBoolean(value, fallback) {
  if (typeof value === "boolean") {
    return value;
  }

  if (typeof value === "number") {
    return value !== 0;
  }

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["1", "true", "yes", "si", "on"].includes(normalized)) {
      return true;
    }
    if (["0", "false", "no", "off"].includes(normalized)) {
      return false;
    }
  }

  return fallback;
}

function asFiniteNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeMotionRule(rule, index) {
  if (!rule || typeof rule !== "object") {
    return null;
  }

  const parsedAnimationIndex = Math.trunc(
    asFiniteNumber(rule.animationIndex ?? rule.animation_index, -1),
  );
  const keywords = Array.isArray(rule.keywords)
    ? rule.keywords
        .map((keyword) => String(keyword).trim().toLowerCase())
        .filter(Boolean)
    : [];

  if (!keywords.length || parsedAnimationIndex < 0) {
    return null;
  }

  const name = String(rule.name ?? `rule-${index + 1}`).trim() || `rule-${index + 1}`;
  return { name, animationIndex: parsedAnimationIndex, keywords };
}

function resolveMotionConfig(rawMotionControl) {
  const raw = rawMotionControl && typeof rawMotionControl === "object" ? rawMotionControl : {};
  const contextAnimations = Array.isArray(raw.contextAnimations)
    ? raw.contextAnimations
        .map((rule, index) => normalizeMotionRule(rule, index))
        .filter(Boolean)
    : [];

  return {
    enabled: asBoolean(raw.enabled, DEFAULT_MOTION_CONFIG.enabled),
    transport: String(raw.transport ?? DEFAULT_MOTION_CONFIG.transport).trim() || DEFAULT_MOTION_CONFIG.transport,
    activationMode: String(
      raw.activationMode ?? raw.activation_mode ?? DEFAULT_MOTION_CONFIG.activationMode,
    ).trim() || DEFAULT_MOTION_CONFIG.activationMode,
    serialPort: String(raw.serialPort ?? raw.serial_port ?? DEFAULT_MOTION_CONFIG.serialPort).trim() || DEFAULT_MOTION_CONFIG.serialPort,
    baudRate: Math.max(1200, Math.trunc(asFiniteNumber(raw.baudRate, DEFAULT_MOTION_CONFIG.baudRate))),
    speakAnimationIndex: Math.max(
      0,
      Math.trunc(asFiniteNumber(raw.speakAnimationIndex, DEFAULT_MOTION_CONFIG.speakAnimationIndex)),
    ),
    autoConnectAuthorizedPort: asBoolean(
      raw.autoConnectAuthorizedPort,
      DEFAULT_MOTION_CONFIG.autoConnectAuthorizedPort,
    ),
    audioThreshold: Math.min(
      1,
      Math.max(0.001, asFiniteNumber(raw.audioThreshold, DEFAULT_MOTION_CONFIG.audioThreshold)),
    ),
    silenceHoldMs: Math.max(
      50,
      Math.trunc(asFiniteNumber(raw.silenceHoldMs, DEFAULT_MOTION_CONFIG.silenceHoldMs)),
    ),
    responseAudioThreshold: Math.min(
      1,
      Math.max(
        0.001,
        asFiniteNumber(
          raw.responseAudioThreshold,
          DEFAULT_MOTION_CONFIG.responseAudioThreshold,
        ),
      ),
    ),
    responseSilenceHoldMs: Math.max(
      100,
      Math.trunc(
        asFiniteNumber(
          raw.responseSilenceHoldMs,
          DEFAULT_MOTION_CONFIG.responseSilenceHoldMs,
        ),
      ),
    ),
    contextAnimations,
  };
}

function renderConfig(config) {
  state.motionConfig = resolveMotionConfig(config.motionControl);

  const items = [
    {
      label: "Modelo realtime",
      value: config.resolvedModel,
    },
    {
      label: "Voz",
      value: config.voice,
    },
    {
      label: "Idioma",
      value: config.language,
    },
    {
      label: "Prompt base",
      value: config.instructions,
    },
    {
      label: "Movimiento Arduino",
      value: state.motionConfig.enabled
        ? `${state.motionConfig.transport} @ ${state.motionConfig.serialPort} @ ${state.motionConfig.baudRate} baud`
        : "Desactivado",
    },
    {
      label: "Animacion habla",
      value: `Indice ${state.motionConfig.speakAnimationIndex}`,
    },
    {
      label: "Modo activacion",
      value: state.motionConfig.activationMode,
    },
    {
      label: "Reglas por contexto",
      value: `${state.motionConfig.contextAnimations.length} configuradas`,
    },
  ];

  if (config.usingFallbackModel) {
    items.unshift({
      label: "Modelo del JSON",
      value: `${config.configuredModel} -> usando ${config.resolvedModel}`,
    });
  }

  elements.configList.innerHTML = "";
  for (const item of items) {
    const wrapper = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = item.label;
    dd.textContent = item.value;
    wrapper.append(dt, dd);
    elements.configList.appendChild(wrapper);
  }

  if (config.hasLogo) {
    elements.logo.src = "/logo";
    elements.logo.hidden = false;
  }

  refreshMotionStatus();
  updateButtons();
}

function safeJsonParse(payload) {
  try {
    return JSON.parse(payload);
  } catch {
    return null;
  }
}

function describeSerialPort(port) {
  const info = port?.getInfo?.() ?? {};
  const vendorId = info.usbVendorId ? info.usbVendorId.toString(16).padStart(4, "0").toUpperCase() : null;
  const productId = info.usbProductId ? info.usbProductId.toString(16).padStart(4, "0").toUpperCase() : null;

  if (vendorId && productId) {
    return `VID ${vendorId} - PID ${productId}`;
  }

  return "Puerto serie autorizado";
}

function hashBottangoCommand(commandBody) {
  let hash = 0;
  for (const char of commandBody) {
    hash += char.charCodeAt(0);
  }
  return hash;
}

function buildBottangoCommand(...parts) {
  const commandBody = parts.join(",");
  return `${commandBody},h${hashBottangoCommand(commandBody)}\n`;
}

function applyMotionServerPayload(payload) {
  if (!payload || typeof payload !== "object") {
    return;
  }

  state.motion.isConnected = Boolean(payload.connected);
  state.motion.portLabel = String(payload.portLabel ?? payload.serialPort ?? state.motionConfig.serialPort).trim()
    || state.motionConfig.serialPort;

  if (!state.motion.isConnected) {
    state.motion.animationActive = false;
    state.motion.currentAnimationIndex = null;
  }
}

async function postMotionServerAction(path) {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    const details = await response.text();
    throw new Error(details || "El servidor no pudo controlar el puerto serial.");
  }

  const payload = await response.json();
  applyMotionServerPayload(payload);
  refreshMotionStatus();
  updateButtons();
  return payload;
}

function resolveSpeechAnimationIndex() {
  const transcript = state.latestAssistantItemId
    ? state.assistantText.get(state.latestAssistantItemId) || ""
    : "";
  const normalizedTranscript = transcript.toLowerCase();

  for (const rule of state.motionConfig.contextAnimations) {
    if (rule.keywords.some((keyword) => normalizedTranscript.includes(keyword))) {
      return rule.animationIndex;
    }
  }

  return state.motionConfig.speakAnimationIndex;
}

function queueMotionWork(work) {
  const scheduled = state.motion.commandQueue.catch(() => {}).then(work);
  state.motion.commandQueue = scheduled.catch(() => {});
  return scheduled;
}

async function writeMotionCommand(command) {
  if (!state.motion.writer) {
    throw new Error("El puerto serie no esta listo.");
  }

  await state.motion.writer.write(textEncoder.encode(command));
}

async function tearDownMotionPort({ silent = false } = {}) {
  const port = state.motion.port;
  const writer = state.motion.writer;

  state.motion.port = null;
  state.motion.writer = null;
  state.motion.portLabel = "Sin puerto";
  state.motion.isConnected = false;
  state.motion.animationActive = false;
  state.motion.currentAnimationIndex = null;
  state.motion.commandQueue = Promise.resolve();

  if (writer) {
    try {
      writer.releaseLock();
    } catch {
      // no-op
    }
  }

  if (port) {
    try {
      await port.close();
    } catch {
      // no-op
    }
  }

  if (!silent) {
    addEvent("motion", "Puerto serie desconectado");
  }

  refreshMotionStatus();
  updateButtons();
}

async function syncMotionAnimation(force = false) {
  if (!state.motionConfig.enabled || !state.motion.isConnected) {
    refreshMotionStatus();
    return;
  }

  return queueMotionWork(async () => {
    if (!state.motion.isConnected) {
      return;
    }

    try {
      if (!state.motion.speakingDesired) {
        if (state.motion.animationActive || force) {
          if (usesServerSerial()) {
            await postMotionServerAction("/motion/stop");
          } else {
            await writeMotionCommand(buildBottangoCommand("APP_ANIM", "STOP"));
          }
          if (state.motion.animationActive) {
            addEvent("motion", "Animacion detenida");
          }
        }

        state.motion.animationActive = false;
        state.motion.currentAnimationIndex = null;
        refreshMotionStatus();
        return;
      }

      const nextAnimationIndex = resolveSpeechAnimationIndex();
      if (
        !force &&
        state.motion.animationActive &&
        state.motion.currentAnimationIndex === nextAnimationIndex
      ) {
        refreshMotionStatus();
        return;
      }

      if (usesServerSerial()) {
        await postMotionServerAction(`/motion/start/${nextAnimationIndex}`);
      } else {
        await writeMotionCommand(
          buildBottangoCommand("APP_ANIM", "START", String(nextAnimationIndex)),
        );
      }
      state.motion.animationActive = true;
      state.motion.currentAnimationIndex = nextAnimationIndex;
      addEvent("motion", `Animacion ${nextAnimationIndex} en reproduccion`);
      refreshMotionStatus();
    } catch (error) {
      addEvent("motion", error.message || "No pude escribir en el puerto serie.");
      if (usesServerSerial()) {
        try {
          await postMotionServerAction("/motion/disconnect");
        } catch {
          // no-op
        }
      }
      await tearDownMotionPort({ silent: true });
    }
  });
}

async function connectMotionPort(port, reason = "manual") {
  if (usesServerSerial()) {
    const payload = await postMotionServerAction("/motion/connect");
    state.motion.animationActive = false;
    state.motion.currentAnimationIndex = null;
    addEvent(
      "motion",
      reason === "automatic"
        ? `Arduino reconectado en ${payload.portLabel || state.motionConfig.serialPort}`
        : `Arduino conectado en ${payload.portLabel || state.motionConfig.serialPort}`,
    );
    await syncMotionAnimation(true);
    return;
  }

  if (!navigator.serial || !state.motionConfig.enabled) {
    refreshMotionStatus();
    return;
  }

  if (state.motion.isConnected) {
    if (state.motion.port === port) {
      refreshMotionStatus();
      return;
    }
    await tearDownMotionPort({ silent: true });
  }

  await port.open({
    baudRate: state.motionConfig.baudRate,
    dataBits: 8,
    stopBits: 1,
    parity: "none",
    flowControl: "none",
  });

  const writer = port.writable?.getWriter();
  if (!writer) {
    await port.close();
    throw new Error("No pude obtener acceso de escritura al puerto serie.");
  }

  state.motion.port = port;
  state.motion.writer = writer;
  state.motion.portLabel = describeSerialPort(port);
  state.motion.isConnected = true;
  state.motion.animationActive = false;
  state.motion.currentAnimationIndex = null;

  addEvent(
    "motion",
    reason === "automatic"
      ? `Arduino reconectado en ${state.motion.portLabel}`
      : `Arduino conectado en ${state.motion.portLabel}`,
  );

  refreshMotionStatus();
  updateButtons();
  await syncMotionAnimation(true);
}

async function requestMotionPort() {
  if (usesServerSerial()) {
    await connectMotionPort(null);
    return;
  }

  if (!navigator.serial) {
    throw new Error("Este navegador no soporta Web Serial.");
  }

  const port = await navigator.serial.requestPort();
  await connectMotionPort(port);
}

async function disconnectMotionPort() {
  if (!state.motion.isConnected) {
    refreshMotionStatus();
    return;
  }

  if (usesServerSerial()) {
    try {
      await postMotionServerAction("/motion/disconnect");
      addEvent("motion", "Puerto COM liberado por el servidor");
    } finally {
      state.motion.animationActive = false;
      state.motion.currentAnimationIndex = null;
      refreshMotionStatus();
      updateButtons();
    }
    return;
  }

  try {
    await queueMotionWork(async () => {
      if (state.motion.animationActive) {
        await writeMotionCommand(buildBottangoCommand("APP_ANIM", "STOP"));
      }
    });
  } catch {
    // no-op
  }

  await tearDownMotionPort();
}

async function autoConnectMotionPort() {
  if (!state.motionConfig.enabled || !state.motionConfig.autoConnectAuthorizedPort) {
    refreshMotionStatus();
    updateButtons();
    return;
  }

  if (usesServerSerial()) {
    try {
      await connectMotionPort(null, "automatic");
    } catch (error) {
      addEvent("motion", error.message || `No pude abrir ${state.motionConfig.serialPort}.`);
      refreshMotionStatus();
      updateButtons();
    }
    return;
  }

  if (!navigator.serial) {
    refreshMotionStatus();
    updateButtons();
    return;
  }

  const ports = await navigator.serial.getPorts();
  if (!ports.length) {
    refreshMotionStatus();
    updateButtons();
    return;
  }

  try {
    await connectMotionPort(ports[0], "automatic");
  } catch (error) {
    addEvent("motion", error.message || "No pude reconectar el Arduino autorizado.");
    refreshMotionStatus();
    updateButtons();
  }
}

function clearFallbackStopTimer() {
  if (state.motion.fallbackStopTimer) {
    window.clearTimeout(state.motion.fallbackStopTimer);
    state.motion.fallbackStopTimer = 0;
  }
}

function setSpeakingDesired(isSpeaking) {
  clearFallbackStopTimer();

  const nextValue = Boolean(isSpeaking);
  if (!nextValue) {
    state.motion.responseStopPending = false;
  }
  if (state.motion.speakingDesired === nextValue) {
    return;
  }

  state.motion.speakingDesired = nextValue;
  void syncMotionAnimation();
}

function scheduleFallbackStop() {
  clearFallbackStopTimer();
  state.motion.fallbackStopTimer = window.setTimeout(() => {
    if (!state.motion.audioMonitorReady) {
      setSpeakingDesired(false);
    }
  }, getMotionSilenceHoldMs());
}

function maybeRefreshSpeechAnimation() {
  if (!state.motion.speakingDesired) {
    return;
  }

  const nextAnimationIndex = resolveSpeechAnimationIndex();
  if (nextAnimationIndex !== state.motion.currentAnimationIndex) {
    void syncMotionAnimation();
  }
}

async function ensureMotionAudioContext() {
  if (!state.motionConfig.enabled) {
    return;
  }

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    return;
  }

  if (!state.motion.audioContext || state.motion.audioContext.state === "closed") {
    state.motion.audioContext = new AudioContextClass();
  }

  if (state.motion.audioContext.state === "suspended") {
    try {
      await state.motion.audioContext.resume();
    } catch {
      // no-op
    }
  }
}

function stopRemoteAudioMonitor({ closeContext = false } = {}) {
  clearFallbackStopTimer();

  if (state.motion.monitorFrameId) {
    window.cancelAnimationFrame(state.motion.monitorFrameId);
    state.motion.monitorFrameId = 0;
  }

  if (state.motion.analyserSource) {
    try {
      state.motion.analyserSource.disconnect();
    } catch {
      // no-op
    }
  }

  state.motion.analyser = null;
  state.motion.analyserSource = null;
  state.motion.analyserData = null;
  state.motion.audioMonitorReady = false;
  state.motion.belowThresholdSince = 0;
  state.motion.responseStopPending = false;

  if (closeContext && state.motion.audioContext) {
    const audioContext = state.motion.audioContext;
    state.motion.audioContext = null;
    audioContext.close().catch(() => {});
  }
}

function setupRemoteAudioMonitor(stream) {
  if (!state.motionConfig.enabled) {
    stopRemoteAudioMonitor();
    return;
  }

  stopRemoteAudioMonitor();

  if (!stream || !state.motion.audioContext) {
    addEvent("motion", "Sin monitor de audio remoto, uso fallback por eventos realtime.");
    return;
  }

  try {
    const analyser = state.motion.audioContext.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.82;

    const source = state.motion.audioContext.createMediaStreamSource(stream);
    source.connect(analyser);

    state.motion.analyser = analyser;
    state.motion.analyserSource = source;
    state.motion.analyserData = new Uint8Array(analyser.fftSize);
    state.motion.audioMonitorReady = true;
    state.motion.belowThresholdSince = 0;

    const monitor = () => {
      if (!state.motion.analyser || !state.motion.analyserData) {
        return;
      }

      state.motion.analyser.getByteTimeDomainData(state.motion.analyserData);

      let sumSquares = 0;
      for (const sample of state.motion.analyserData) {
        const centered = (sample - 128) / 128;
        sumSquares += centered * centered;
      }

      const rms = Math.sqrt(sumSquares / state.motion.analyserData.length);
      const now = performance.now();

      const silenceThreshold = getMotionSilenceThreshold();
      const silenceHoldMs = getMotionSilenceHoldMs();

      if (usesAudioActivationMode()) {
        if (rms >= silenceThreshold) {
          state.motion.belowThresholdSince = 0;
          if (!state.motion.speakingDesired) {
            setSpeakingDesired(true);
          }
        } else {
          if (state.motion.belowThresholdSince === 0) {
            state.motion.belowThresholdSince = now;
          }

          if (
            state.motion.speakingDesired &&
            now - state.motion.belowThresholdSince >= silenceHoldMs
          ) {
            setSpeakingDesired(false);
          }
        }
      } else {
        if (!state.motion.responseStopPending) {
          state.motion.belowThresholdSince = 0;
        } else if (rms >= silenceThreshold) {
          state.motion.belowThresholdSince = 0;
        } else {
          if (state.motion.belowThresholdSince === 0) {
            state.motion.belowThresholdSince = now;
          }

          if (
            state.motion.speakingDesired &&
            now - state.motion.belowThresholdSince >= silenceHoldMs
          ) {
            setSpeakingDesired(false);
          }
        }
      }

      state.motion.monitorFrameId = window.requestAnimationFrame(monitor);
    };

    monitor();
  } catch (error) {
    state.motion.audioMonitorReady = false;
    addEvent("motion", error.message || "No pude iniciar el analizador del audio remoto.");
  }
}

function handleRealtimeEvent(event) {
  if (!event?.type) {
    return;
  }

  switch (event.type) {
    case "session.created":
    case "session.updated":
      setStatus("Conectado", "ready");
      addEvent("sesion", event.type);
      break;

    case "input_audio_buffer.speech_started":
      setStatus("Te escucho", "busy");
      addEvent("audio", "Detecte voz");
      if (usesResponseActivationMode() && state.motion.speakingDesired) {
        state.motion.responseStopPending = false;
        setSpeakingDesired(false);
      }
      break;

    case "input_audio_buffer.speech_stopped":
      setStatus("Procesando", "busy");
      addEvent("audio", "Termino el turno");
      break;

    case "input_audio_buffer.committed":
      if (event.item_id) {
        setTurnText(event.item_id, "user", "", true);
      }
      break;

    case "conversation.item.input_audio_transcription.delta":
      if (event.item_id && event.delta) {
        appendTurnText(event.item_id, "user", event.delta);
      }
      break;

    case "conversation.item.input_audio_transcription.completed":
      if (event.item_id) {
        setTurnText(event.item_id, "user", event.transcript || "Audio recibido", false);
      }
      break;

    case "response.created":
      clearFallbackStopTimer();
      state.motion.responseStopPending = false;
      setStatus("Respondiendo", "busy");
      addEvent("modelo", "Genero una respuesta");
      break;

    case "response.output_audio_transcript.delta":
      if (event.item_id && event.delta) {
        appendTurnText(event.item_id, "assistant", event.delta);
        maybeRefreshSpeechAnimation();
      }
      if (usesResponseActivationMode()) {
        state.motion.responseStopPending = false;
        setSpeakingDesired(true);
      } else if (!state.motion.audioMonitorReady) {
        setSpeakingDesired(true);
      }
      break;

    case "response.output_audio_transcript.done":
      if (event.item_id) {
        setTurnText(
          event.item_id,
          "assistant",
          event.transcript || "Respuesta lista",
          false,
        );
        maybeRefreshSpeechAnimation();
      }
      break;

    case "response.output_text.delta":
      if (event.item_id && event.delta && !state.turns.has(event.item_id)) {
        appendTurnText(event.item_id, "assistant", event.delta);
        maybeRefreshSpeechAnimation();
      }
      if (usesResponseActivationMode()) {
        state.motion.responseStopPending = false;
        setSpeakingDesired(true);
      }
      break;

    case "response.output_text.done": {
      if (event.item_id) {
        const existingTurn = state.turns.get(event.item_id);
        if (!existingTurn || existingTurn.text.textContent === "Preparando respuesta...") {
          setTurnText(event.item_id, "assistant", event.text || "Respuesta lista", false);
          maybeRefreshSpeechAnimation();
        }
      }
      break;
    }

    case "response.done":
      setStatus("Listo para seguir", "ready");
      addEvent("modelo", "Respuesta completa");
      if (usesResponseActivationMode()) {
        if (state.motion.audioMonitorReady) {
          state.motion.responseStopPending = true;
          state.motion.belowThresholdSince = 0;
        } else {
          scheduleFallbackStop();
        }
      } else if (!state.motion.audioMonitorReady) {
        scheduleFallbackStop();
      }
      break;

    case "error":
      setStatus("Error en sesion", "error");
      addEvent("error", event.error?.message || "Error realtime");
      setSpeakingDesired(false);
      break;

    default:
      if (
        event.type.startsWith("response.") ||
        event.type.startsWith("conversation.") ||
        event.type.startsWith("input_audio_buffer.")
      ) {
        addEvent("realtime", event.type);
      }
      break;
  }
}

async function loadConfig() {
  const response = await fetch("/config");
  if (!response.ok) {
    throw new Error("No pude leer la configuracion local.");
  }

  state.config = await response.json();
  renderConfig(state.config);
}

function attachDataChannelHandlers(channel) {
  channel.addEventListener("open", () => {
    addEvent("canal", "Canal de eventos abierto");
  });

  channel.addEventListener("close", () => {
    addEvent("canal", "Canal de eventos cerrado");
  });

  channel.addEventListener("message", (event) => {
    const payload = safeJsonParse(event.data);
    if (payload) {
      handleRealtimeEvent(payload);
    }
  });
}

function attachPeerHandlers(peerConnection) {
  peerConnection.addEventListener("connectionstatechange", () => {
    const { connectionState } = peerConnection;
    addEvent("peer", connectionState);

    if (connectionState === "connected") {
      setStatus("Conectado", "ready");
    }

    if (
      ["disconnected", "failed", "closed"].includes(connectionState) &&
      state.peerConnection === peerConnection
    ) {
      disconnect(true);
    }
  });

  peerConnection.addEventListener("track", (event) => {
    if (!state.remoteAudio) {
      state.remoteAudio = document.createElement("audio");
      state.remoteAudio.autoplay = true;
      state.remoteAudio.playsInline = true;
    }

    state.remoteAudio.srcObject = event.streams[0];
    state.remoteAudio.play().catch(() => {});
    if (state.motionConfig.enabled) {
      setupRemoteAudioMonitor(event.streams[0]);
    } else {
      stopRemoteAudioMonitor();
    }
  });
}

async function connect() {
  if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
    throw new Error("Tu navegador no soporta WebRTC o acceso al microfono.");
  }

  setStatus("Pidiendo permisos", "busy");
  elements.connectButton.disabled = true;

  await ensureMotionAudioContext();

  const tokenResponse = await fetch("/token");
  if (!tokenResponse.ok) {
    const text = await tokenResponse.text();
    throw new Error(text || "No pude obtener el token efimero.");
  }

  const tokenPayload = await tokenResponse.json();
  const ephemeralKey =
    tokenPayload.value ??
    tokenPayload.client_secret?.value ??
    tokenPayload.client_secret?.token;

  if (!ephemeralKey) {
    throw new Error("El servidor no devolvio un token efimero valido.");
  }

  const peerConnection = new RTCPeerConnection();
  const dataChannel = peerConnection.createDataChannel("oai-events");
  state.peerConnection = peerConnection;
  state.dataChannel = dataChannel;
  attachPeerHandlers(peerConnection);
  attachDataChannelHandlers(dataChannel);
  updateButtons();

  const localStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });

  state.localStream = localStream;
  for (const track of localStream.getTracks()) {
    peerConnection.addTrack(track, localStream);
  }

  const offer = await peerConnection.createOffer();
  await peerConnection.setLocalDescription(offer);

  const sdpResponse = await fetch("https://api.openai.com/v1/realtime/calls", {
    method: "POST",
    body: offer.sdp,
    headers: {
      Authorization: `Bearer ${ephemeralKey}`,
      "Content-Type": "application/sdp",
    },
  });

  if (!sdpResponse.ok) {
    const details = await sdpResponse.text();
    throw new Error(details || `OpenAI devolvio ${sdpResponse.status}.`);
  }

  const answer = {
    type: "answer",
    sdp: await sdpResponse.text(),
  };

  await peerConnection.setRemoteDescription(answer);

  state.isMuted = false;
  updateButtons();
  setStatus("Conectando", "busy");
}

function disconnect(updateUi = true) {
  const dataChannel = state.dataChannel;
  const peerConnection = state.peerConnection;
  const localStream = state.localStream;

  clearFallbackStopTimer();
  stopRemoteAudioMonitor();
  setSpeakingDesired(false);

  state.peerConnection = null;
  state.dataChannel = null;
  state.localStream = null;
  state.isMuted = false;

  if (dataChannel) {
    dataChannel.close();
  }

  if (peerConnection) {
    peerConnection.close();
  }

  if (localStream) {
    for (const track of localStream.getTracks()) {
      track.stop();
    }
  }

  if (state.remoteAudio) {
    state.remoteAudio.pause();
    state.remoteAudio.srcObject = null;
  }

  if (updateUi) {
    setStatus("Desconectado", "idle");
    addEvent("peer", "Sesion cerrada");
  }

  updateButtons();
}

function toggleMute() {
  if (!state.localStream) {
    return;
  }

  state.isMuted = !state.isMuted;
  for (const track of state.localStream.getAudioTracks()) {
    track.enabled = !state.isMuted;
  }

  setStatus(state.isMuted ? "Micro silenciado" : "Listo para hablar", "ready");
  addEvent("micro", state.isMuted ? "Silenciado" : "Activo");
  updateButtons();
}

async function bootstrap() {
  updateButtons();
  refreshMotionStatus();
  setStatus("Cargando", "busy");

  if (navigator.serial) {
    navigator.serial.addEventListener("disconnect", (event) => {
      if (event.target === state.motion.port) {
        void tearDownMotionPort({ silent: true });
        addEvent("motion", "El sistema desconecto el Arduino.");
      }
    });
  }

  try {
    await loadConfig();
    await autoConnectMotionPort();
    setStatus("Desconectado", "idle");
    addEvent("app", "Configuracion lista");
  } catch (error) {
    setStatus("Error de config", "error");
    addEvent("error", error.message);
  }
}

elements.connectButton.addEventListener("click", async () => {
  try {
    await connect();
  } catch (error) {
    disconnect(false);
    setStatus("Error al conectar", "error");
    addEvent("error", error.message);
    updateButtons();
  }
});

elements.disconnectButton.addEventListener("click", () => {
  disconnect(true);
});

elements.muteButton.addEventListener("click", () => {
  toggleMute();
});

elements.motionConnectButton.addEventListener("click", async () => {
  try {
    await requestMotionPort();
  } catch (error) {
    addEvent("motion", error.message || "No pude conectar el Arduino.");
    refreshMotionStatus();
    updateButtons();
  }
});

elements.motionDisconnectButton.addEventListener("click", () => {
  void disconnectMotionPort();
});

bootstrap();
