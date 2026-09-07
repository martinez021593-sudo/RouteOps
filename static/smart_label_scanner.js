/* RouteOps V0.3.1.4 — Smart Label Scanner + background OCR queue */
(() => {
  'use strict';
  const root = document.getElementById('smartScanner');
  if (!root) return;

  const video = document.getElementById('intakeVideo');
  const wrap = document.getElementById('videoWrap');
  const guide = document.getElementById('guideCanvas');
  const gctx = guide.getContext('2d');
  const processCanvas = document.getElementById('processCanvas');
  const cropCanvas = document.getElementById('cropCanvas');
  const fullCanvas = document.getElementById('fullCanvas');
  const startBtn = document.getElementById('startCamera');
  const captureBtn = document.getElementById('captureNow');
  const torchBtn = document.getElementById('torchBtn');
  const switchBtn = document.getElementById('switchCamera');
  const autoToggle = document.getElementById('autoCapture');
  const stateEl = document.getElementById('scanState');
  const qualityEl = document.getElementById('qualityText');
  const hintEl = document.getElementById('scanHint');
  const stableEl = document.getElementById('stableCounter');
  const result = document.getElementById('resultBox');
  const carrierHint = document.getElementById('carrierHint');
  const cameraInfo = document.getElementById('cameraInfo');
  const cameraName = document.getElementById('cameraName');
  const focusInfo = document.getElementById('focusInfo');
  const zoomInfo = document.getElementById('zoomInfo');
  const captureUrl = root.dataset.captureUrl;
  const jobsUrl = root.dataset.jobsUrl;

  const localQueueEl = document.getElementById('queueLocal');
  const serverQueueEl = document.getElementById('queueServer');
  const processingEl = document.getElementById('queueProcessing');
  const completedEl = document.getElementById('queueCompleted');
  const backgroundList = document.getElementById('backgroundJobs');

  const diagEngine = document.getElementById('diagEngine');
  const diagCamera = document.getElementById('diagCamera');
  const diagEdges = document.getElementById('diagEdges');
  const diagBarcode = document.getElementById('diagBarcode');
  const diagOcr = document.getElementById('diagOcr');
  const diagGeocode = document.getElementById('diagGeocode');

  let engine = null;
  let stream = null, track = null, detector = null;
  let visionLoop = null, barcodeLoop = null, jobsPoll = null;
  let frameBusy = false, torchOn = false, cameras = [], cameraIndex = 0;
  let lastCodes = [], lastCodesAt = 0;
  let currentQuad = null, smoothQuad = null, previousQuad = null;
  let sharpness = 0, confidence = 0, tooClose = false, stableFrames = 0, noLabelFrames = 0;
  let armed = true, lastAutoCapture = 0, audioCtx = null;
  let localUploads = [], activeUploads = 0, localCaptureSeq = 0;
  let seenServerJobs = new Set(), completedCount = 0;

  const STABLE_REQUIRED = 5;
  const AUTO_COOLDOWN = 1700;
  const SHARPNESS_READY = 62;
  const MOVE_READY = 0.020;
  const MAX_PARALLEL_UPLOADS = 2;
  const MAX_LOCAL_QUEUE = 12;

  function diag(el, state, text) {
    if (!el) return;
    el.className = `diag-value ${state}`;
    el.textContent = text;
  }
  function carrierLabel(c) {
    return c === 'imile' ? 'iMile' : (c === 'ecoscooting' ? 'Ecoscooting' : ((c === 'tipsa' || c === 'agencia') ? 'TIPSA / agencia' : 'Sin identificar'));
  }
  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function updateCounts(counts) {
    const box = document.getElementById('carrierCounts');
    if (!box) return;
    box.innerHTML = '';
    (counts || []).forEach(c => {
      const d = document.createElement('div');
      d.className = 'carrier-mini';
      d.innerHTML = `<strong>${c.total}</strong><small>${carrierLabel(c.carrier)}</small>`;
      box.appendChild(d);
    });
  }
  function setState(kind, title, hint) {
    stateEl.className = `scan-state ${kind}`;
    stateEl.textContent = title;
    if (hint) hintEl.textContent = hint;
  }
  function updateLocalQueueUI() {
    if (localQueueEl) localQueueEl.textContent = String(localUploads.length + activeUploads);
  }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
  function averageMove(a, b) {
    if (!a || !b) return 1;
    let s = 0;
    for (let i = 0; i < 4; i++) s += dist(a[i], b[i]);
    return (s / 4) / Math.hypot(processCanvas.width || 1, processCanvas.height || 1);
  }
  function smoothPoints(prev, next, alpha = .34) {
    if (!prev) return next.map(p => ({...p}));
    return next.map((p, i) => ({x: prev[i].x * (1 - alpha) + p.x * alpha, y: prev[i].y * (1 - alpha) + p.y * alpha}));
  }
  function displayTransform() {
    const cw = wrap.clientWidth, ch = wrap.clientHeight, sw = processCanvas.width || 360, sh = processCanvas.height || 480;
    const scale = Math.min(cw / sw, ch / sh);
    return {scale, ox: (cw - sw * scale) / 2, oy: (ch - sh * scale) / 2};
  }
  function resizeGuide() {
    const rect = wrap.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
    guide.width = Math.max(1, Math.round(rect.width * dpr));
    guide.height = Math.max(1, Math.round(rect.height * dpr));
    guide.style.width = `${rect.width}px`; guide.style.height = `${rect.height}px`;
    gctx.setTransform(dpr, 0, 0, dpr, 0, 0); drawGuide();
  }
  function drawCorner(x, y, dx, dy, color) {
    gctx.strokeStyle = color; gctx.lineWidth = 4; gctx.beginPath();
    gctx.moveTo(x, y + dy * 24); gctx.lineTo(x, y); gctx.lineTo(x + dx * 24, y); gctx.stroke();
  }
  function drawGuide() {
    const cw = wrap.clientWidth, ch = wrap.clientHeight; gctx.clearRect(0, 0, cw, ch);
    if (!smoothQuad) {
      const px = Math.max(18, cw * .055), py = Math.max(28, ch * .07);
      gctx.strokeStyle = 'rgba(255,255,255,.45)'; gctx.lineWidth = 2; gctx.setLineDash([10, 9]);
      gctx.strokeRect(px, py, cw - px * 2, ch - py * 2); gctx.setLineDash([]); return;
    }
    const t = displayTransform();
    const q = smoothQuad.map(p => ({x: t.ox + p.x * t.scale, y: t.oy + p.y * t.scale}));
    const ready = stableFrames >= STABLE_REQUIRED && sharpness >= SHARPNESS_READY && confidence >= .45;
    const color = ready ? '#22c55e' : '#f59e0b';
    gctx.fillStyle = ready ? 'rgba(34,197,94,.08)' : 'rgba(245,158,11,.06)'; gctx.strokeStyle = color; gctx.lineWidth = 3;
    gctx.beginPath(); gctx.moveTo(q[0].x, q[0].y); q.slice(1).forEach(p => gctx.lineTo(p.x, p.y)); gctx.closePath(); gctx.fill(); gctx.stroke();
    drawCorner(q[0].x, q[0].y, 1, 1, color); drawCorner(q[1].x, q[1].y, -1, 1, color); drawCorner(q[2].x, q[2].y, -1, -1, color); drawCorner(q[3].x, q[3].y, 1, -1, color);
  }
  function setDetectionUI(found, move) {
    if (!found) {
      stableEl.hidden = true; qualityEl.textContent = '—'; diag(diagEdges, 'warn', 'Buscando');
      if (tooClose) setState('focus', 'Aléjate un poco', 'Necesito ver los bordes completos de la etiqueta.');
      else setState('searching', 'Buscando etiqueta', 'Coloca la etiqueta completa en la imagen.');
      return;
    }
    diag(diagEdges, 'ok', 'Detectando'); stableEl.hidden = false;
    stableEl.textContent = `${Math.min(stableFrames, STABLE_REQUIRED)}/${STABLE_REQUIRED}`;
    const sharpText = sharpness >= SHARPNESS_READY ? 'Nítida' : 'Enfocando';
    qualityEl.textContent = `${sharpText} · ${Math.round(sharpness)} · ${Math.round(confidence * 100)}%`;
    if (sharpness < SHARPNESS_READY) setState('focus', 'Enfocando', 'Mantén estable y evita reflejos.');
    else if (move > MOVE_READY || stableFrames < STABLE_REQUIRED) setState('stabilizing', 'Etiqueta detectada', 'Mantén estable: el marco seguirá la etiqueta.');
    else setState('ready', '✓ Etiqueta lista', 'Autocaptura preparada. OCR se hará en segundo plano.');
  }
  async function visionTick() {
    if (!stream || video.readyState < 2 || frameBusy || !engine) return;
    let r;
    try { r = engine.analyze(video, processCanvas); }
    catch (e) { console.warn('Embedded vision:', e); diag(diagEdges, 'error', 'Error'); return; }
    currentQuad = r.found ? r.quad : null; sharpness = r.sharpness || 0; confidence = r.confidence || 0; tooClose = !!r.tooClose;
    if (currentQuad) {
      noLabelFrames = 0; smoothQuad = smoothPoints(smoothQuad, currentQuad);
      const move = averageMove(previousQuad, currentQuad); previousQuad = currentQuad.map(p => ({...p}));
      if (move < MOVE_READY && sharpness >= SHARPNESS_READY && confidence >= .45) stableFrames++; else stableFrames = Math.max(0, stableFrames - 1);
      setDetectionUI(true, move); drawGuide();
      const now = Date.now();
      const queueDepth = localUploads.length + activeUploads;
      if (queueDepth >= MAX_LOCAL_QUEUE) {
        setState('processing', 'Cola local llena', 'Espera un momento mientras se suben las capturas pendientes.');
        return;
      }
      if (autoToggle.checked && armed && stableFrames >= STABLE_REQUIRED && sharpness >= SHARPNESS_READY && confidence >= .45 && now - lastAutoCapture > AUTO_COOLDOWN) {
        lastAutoCapture = now; armed = false; captureFrame(true);
      }
    } else {
      noLabelFrames++; stableFrames = 0; previousQuad = null; smoothQuad = null; setDetectionUI(false, 1); drawGuide();
      if (noLabelFrames >= 4) armed = true;
    }
  }

  function isBackLabel(label) {
    const l = (label || '').toLowerCase();
    return /(back|rear|environment|trasera|posterior|arrière|rück|posteriore)/.test(l) && !/(front|user|selfie|frontal)/.test(l);
  }
  async function discoverCameras() {
    const devices = await navigator.mediaDevices.enumerateDevices(), vids = devices.filter(d => d.kind === 'videoinput'), backs = vids.filter(d => isBackLabel(d.label));
    cameras = backs.length ? backs : vids.filter(d => !/(front|user|selfie|frontal)/i.test(d.label));
    if (!cameras.length) cameras = vids; switchBtn.hidden = cameras.length < 2;
  }
  async function tuneTrack() {
    if (!track) return;
    let caps = {}; try { caps = track.getCapabilities ? track.getCapabilities() : {}; } catch (e) {}
    const advanced = [];
    if (caps.zoom && Number.isFinite(caps.zoom.min)) advanced.push({zoom: caps.zoom.min});
    if (Array.isArray(caps.focusMode) && caps.focusMode.includes('continuous')) advanced.push({focusMode: 'continuous'});
    try { if (advanced.length) await track.applyConstraints({advanced}); } catch (e) { console.warn('Camera constraints:', e); }
    const settings = track.getSettings ? track.getSettings() : {};
    cameraInfo.hidden = false; cameraName.textContent = track.label || 'Cámara trasera';
    focusInfo.textContent = (Array.isArray(caps.focusMode) && caps.focusMode.includes('continuous')) ? 'Continuo solicitado' : 'Automático del dispositivo';
    if (caps.zoom) {
      const z = settings.zoom ?? caps.zoom.min; zoomInfo.textContent = `${Number(z).toFixed(1)}× (mínimo ${Number(caps.zoom.min).toFixed(1)}×)`;
    } else zoomInfo.textContent = 'Sin control web de zoom';
    torchBtn.hidden = !(caps.torch || (Array.isArray(caps.torch) && caps.torch.includes(true)));
  }
  async function stopCamera() {
    if (visionLoop) { clearInterval(visionLoop); visionLoop = null; }
    if (barcodeLoop) { clearInterval(barcodeLoop); barcodeLoop = null; }
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null; track = null; video.srcObject = null; torchOn = false; diag(diagCamera, 'warn', 'Detenida');
  }
  async function openCamera(deviceId = null) {
    await stopCamera(); setState('searching', 'Abriendo cámara', 'Buscando cámara trasera…');
    const constraints = {width:{ideal:1920}, height:{ideal:1440}, facingMode:deviceId ? undefined : {ideal:'environment'}, resizeMode:{ideal:'none'}};
    if (deviceId) { delete constraints.facingMode; constraints.deviceId = {exact: deviceId}; }
    stream = await navigator.mediaDevices.getUserMedia({video: constraints, audio: false});
    track = stream.getVideoTracks()[0]; video.srcObject = stream; await video.play();
    await tuneTrack(); await discoverCameras(); resizeGuide(); captureBtn.disabled = false; startBtn.textContent = 'Cámara activa'; diag(diagCamera, 'ok', 'Activa');
    setState('searching', 'Buscando etiqueta', 'Muestra la etiqueta completa; OCR se procesa en segundo plano.');

    if ('BarcodeDetector' in window) {
      try {
        const supported = await BarcodeDetector.getSupportedFormats();
        detector = new BarcodeDetector({formats: supported.filter(x => ['qr_code','code_128','code_39','ean_13','ean_8','upc_a','upc_e','itf'].includes(x))});
        diag(diagBarcode, 'ok', 'Disponible');
        barcodeLoop = setInterval(async () => {
          if (frameBusy || video.readyState < 2 || !detector) return;
          try {
            const codes = await detector.detect(video);
            if (codes.length) {
              const values = [];
              codes.forEach(c => {
                const value = (c.rawValue || '').trim();
                if (value && !values.includes(value)) values.push(value);
              });
              if (values.length) { lastCodes = values.slice(0, 12); lastCodesAt = Date.now(); }
            } else if (Date.now() - lastCodesAt > 5000) lastCodes = [];
          } catch (e) {}
        }, 550);
      } catch (e) { diag(diagBarcode, 'warn', 'No disponible'); }
    } else diag(diagBarcode, 'warn', 'No soportado');
    visionLoop = setInterval(visionTick, 230);
  }

  function feedback() {
    try {
      if (navigator.vibrate) navigator.vibrate(70);
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const o = audioCtx.createOscillator(), g = audioCtx.createGain(); o.frequency.value = 880; g.gain.value = .04;
      o.connect(g); g.connect(audioCtx.destination); o.start(); o.stop(audioCtx.currentTime + .08);
    } catch (e) {}
  }
  async function buildLabelBlob() {
    if (engine && smoothQuad) {
      try { return await engine.captureLabel(video, processCanvas, fullCanvas, cropCanvas, smoothQuad); }
      catch (e) { console.warn('Crop fallback:', e); }
    }
    fullCanvas.width = video.videoWidth; fullCanvas.height = video.videoHeight;
    fullCanvas.getContext('2d').drawImage(video, 0, 0, fullCanvas.width, fullCanvas.height);
    return new Promise(res => fullCanvas.toBlob(res, 'image/jpeg', .90));
  }

  async function captureFrame(automatic = false) {
    if (frameBusy || !video.videoWidth) return;
    if (localUploads.length + activeUploads >= MAX_LOCAL_QUEUE) {
      setState('processing', 'Cola local llena', 'Espera a que algunas capturas terminen de subir.');
      return;
    }
    frameBusy = true; captureBtn.disabled = true;
    setState('processing', 'Capturando', 'La foto entra a la cola; puedes preparar el siguiente paquete.');
    try {
      const blob = await buildLabelBlob();
      const item = {
        localId: ++localCaptureSeq,
        blob,
        rawCodes: [...lastCodes],
        carrier: carrierHint.value || '',
        capturedAt: Date.now()
      };
      localUploads.push(item); updateLocalQueueUI(); pumpUploads();
      feedback();
      result.innerHTML = `<strong>✓ Captura #${item.localId} guardada</strong><small>OCR en segundo plano. Retira este paquete y coloca el siguiente.</small>`;
      setState('success', '✓ Foto capturada', 'Retira el paquete. RouteOps seguirá leyendo mientras escaneas el siguiente.');
      stableFrames = 0; previousQuad = null; lastCodes = [];
      if (!automatic) armed = false;
    } catch (e) {
      result.innerHTML = `<strong>No se pudo capturar</strong><small>${esc(e.message)}</small>`;
      setState('error', 'Reintentar', 'Acerca la etiqueta completa y evita reflejos.'); armed = true;
    } finally {
      setTimeout(() => { frameBusy = false; captureBtn.disabled = false; }, 220);
    }
  }

  async function uploadOne(item) {
    const fd = new FormData();
    fd.append('image', item.blob, `label-${item.localId}.jpg`);
    fd.append('raw_codes', JSON.stringify(item.rawCodes || []));
    fd.append('raw_code', (item.rawCodes && item.rawCodes[0]) || '');
    fd.append('carrier', item.carrier || '');
    const response = await fetch(captureUrl, {method:'POST', body:fd});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo encolar OCR');
    return data;
  }
  function pumpUploads() {
    updateLocalQueueUI();
    while (activeUploads < MAX_PARALLEL_UPLOADS && localUploads.length) {
      const item = localUploads.shift(); activeUploads++; updateLocalQueueUI();
      uploadOne(item)
        .then(data => {
          addBackgroundRow({id:data.job_id, status:'queued', label:`Captura #${item.localId}`});
          pollJobs();
        })
        .catch(err => {
          addBackgroundRow({id:`local-${item.localId}`, status:'error', error:err.message, label:`Captura #${item.localId}`});
        })
        .finally(() => { activeUploads--; updateLocalQueueUI(); pumpUploads(); });
    }
  }

  function addBackgroundRow(job) {
    if (!backgroundList) return;
    const key = String(job.id);
    let row = Array.from(backgroundList.children).find(el => el.dataset.jobId === key) || null;
    if (!row) {
      row = document.createElement('div'); row.className = 'bg-job-row'; row.dataset.jobId = key; backgroundList.prepend(row);
    }
    const status = job.status || 'queued';
    let title = job.label || `OCR #${key}`;
    let detail = status === 'queued' ? 'En cola' : (status === 'processing' ? 'Leyendo etiqueta…' : status);
    if (job.result) {
      const r = job.result;
      title = `${carrierLabel(r.carrier)} · ${r.tracking_code || r.barcode || 'sin tracking'}`;
      detail = `${r.recipient_name || 'nombre pendiente'} · ${r.address || 'dirección pendiente'}`;
    }
    if (job.error) detail = job.error;
    row.innerHTML = `<span class="job-dot ${esc(status)}"></span><div><strong>${esc(title)}</strong><small>${esc(detail)}</small></div><span class="job-status ${esc(status)}">${esc(status)}</span>`;
    while (backgroundList.children.length > 12) backgroundList.removeChild(backgroundList.lastChild);
  }

  function showCompletedJob(job) {
    const data = job.result || {};
    if (!data || !job.package_id) return;
    const missing = (data.missing_required || []).join(', ');
    const geo = data.geocode_status === 'ok' ? 'Geocodificada' : (data.geocode_status === 'not_configured' ? 'Geocodificación no configurada' : (data.geocode_status === 'failed' ? 'Geocodificación falló' : 'Sin geocodificar'));
    const debug = job.ocr_debug ? `<details class="ocr-debug"><summary>Ver lectura OCR / parser</summary><small>Perfil: ${esc(data.profile || '')} · ${esc(data.ocr_passes || 1)} pase(s)</small><pre>${esc(job.ocr_debug)}</pre></details>` : '';
    const source = data.tracking_source ? ` · fuente: ${esc(data.tracking_source)}` : '';
    result.innerHTML = `<strong>${data.duplicate ? 'Ya registrado' : '✓ OCR completado'} · ${esc(carrierLabel(data.carrier))}</strong><small>Tracking: ${esc(data.tracking_code || '—')}${source}</small><small>Nombre: ${esc(data.recipient_name || 'pendiente')}</small><small>Dirección: ${esc(data.address || 'pendiente')}</small><small>Perfil: ${esc(data.profile || '—')} · extracción ${Math.round((data.confidence || 0) * 100)}% · OCR ${data.ocr_confidence == null ? '—' : Math.round(data.ocr_confidence * 100) + '%'}</small><small>${esc(geo)} · ${esc(data.ocr_passes || 1)} pase(s) OCR</small>${data.intake_status === 'review' ? `<small>Falta para READY: ${esc(missing || 'revisión manual')}</small><a class="btn tiny ghost" href="/driver/intake/${data.package_id}/review">Revisar ahora</a>` : '<small>Estado: READY ✓</small>'}${debug}`;
  }

  async function pollJobs() {
    if (!jobsUrl) return;
    try {
      const response = await fetch(jobsUrl, {cache:'no-store'});
      const data = await response.json();
      if (!response.ok || !data.ok) return;
      updateCounts(data.counts);
      const q = data.queue || {};
      if (serverQueueEl) serverQueueEl.textContent = String(q.queued || 0);
      if (processingEl) processingEl.textContent = String(q.processing || 0);
      const jobs = data.jobs || [];
      completedCount = jobs.filter(j => ['done','duplicate'].includes(j.status)).length;
      if (completedEl) completedEl.textContent = String(completedCount);
      jobs.slice().reverse().forEach(job => {
        addBackgroundRow(job);
        if (['done','duplicate','error'].includes(job.status) && !seenServerJobs.has(job.id)) {
          seenServerJobs.add(job.id);
          if (job.status === 'error') {
            result.innerHTML = `<strong>OCR con error</strong><small>${esc(job.error || 'No se pudo procesar una etiqueta.')}</small>`;
          } else {
            showCompletedJob(job);
          }
        }
      });
    } catch (e) {}
  }

  try {
    if (typeof window.RouteOpsVisionEngine === 'function') {
      engine = new window.RouteOpsVisionEngine({processWidth:360}); diag(diagEngine, 'ok', 'Integrado'); diag(diagEdges, 'warn', 'Esperando cámara');
      setState('searching', 'Motor de visión listo', 'Abre la cámara para comenzar.');
    } else {
      diag(diagEngine, 'error', 'No cargó'); diag(diagEdges, 'warn', 'Manual'); setState('focus', 'Visión limitada', 'El motor local no cargó; captura manual sigue disponible.');
    }
  } catch (e) { diag(diagEngine, 'error', 'Error'); setState('focus', 'Visión limitada', 'Captura manual disponible.'); }

  diag(diagOcr, root.dataset.ocrReady === '1' ? 'ok' : 'warn', root.dataset.ocrReady === '1' ? 'Document OCR' : 'Sin configurar');
  diag(diagGeocode, root.dataset.geocodeReady === '1' ? 'ok' : 'warn', root.dataset.geocodeReady === '1' ? 'Configurada' : 'Sin configurar');

  startBtn.addEventListener('click', async () => { try { await openCamera(); } catch (e) { diag(diagCamera, 'error', 'Error'); setState('error', 'Cámara no disponible', e.message); } });
  captureBtn.addEventListener('click', () => captureFrame(false));
  torchBtn.addEventListener('click', async () => {
    if (!track) return; torchOn = !torchOn;
    try { await track.applyConstraints({advanced:[{torch:torchOn}]}); torchBtn.textContent = torchOn ? 'Apagar linterna' : 'Linterna'; }
    catch (e) { torchOn = false; torchBtn.textContent = 'Linterna no disponible'; }
  });
  switchBtn.addEventListener('click', async () => {
    if (!cameras.length) return; cameraIndex = (cameraIndex + 1) % cameras.length;
    try { await openCamera(cameras[cameraIndex].deviceId); } catch (e) { setState('error', 'No se pudo cambiar cámara', e.message); }
  });
  window.addEventListener('resize', resizeGuide);
  window.addEventListener('orientationchange', () => setTimeout(resizeGuide, 250));
  window.addEventListener('beforeunload', stopCamera);

  updateLocalQueueUI();
  pollJobs();
  jobsPoll = setInterval(pollJobs, 800);
})();
