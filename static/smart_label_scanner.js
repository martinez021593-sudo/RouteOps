/* RouteOps V0.3.1.2 — Smart Label Scanner controller */
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

  const diagEngine = document.getElementById('diagEngine');
  const diagCamera = document.getElementById('diagCamera');
  const diagEdges = document.getElementById('diagEdges');
  const diagBarcode = document.getElementById('diagBarcode');
  const diagOcr = document.getElementById('diagOcr');

  let engine = null;
  let stream = null, track = null, detector = null;
  let visionLoop = null, barcodeLoop = null;
  let busy = false, torchOn = false, cameras = [], cameraIndex = 0;
  let lastCode = '', lastCodeAt = 0;
  let currentQuad = null, smoothQuad = null, previousQuad = null;
  let sharpness = 0, confidence = 0, tooClose = false, stableFrames = 0, noLabelFrames = 0;
  let armed = true, lastAutoCapture = 0, audioCtx = null;

  const STABLE_REQUIRED = 5;
  const AUTO_COOLDOWN = 2200;
  const SHARPNESS_READY = 62;
  const MOVE_READY = 0.020;

  function diag(el, state, text) {
    if (!el) return;
    el.className = `diag-value ${state}`;
    el.textContent = text;
  }

  function carrierLabel(c){
    return c==='imile'?'iMile':(c==='ecoscooting'?'Ecoscooting':(c==='agencia'?'Agencia':'Sin identificar'));
  }
  function updateCounts(counts){
    const box=document.getElementById('carrierCounts');
    box.innerHTML='';
    (counts||[]).forEach(c=>{
      const d=document.createElement('div'); d.className='carrier-mini';
      d.innerHTML=`<strong>${c.total}</strong><small>${carrierLabel(c.carrier)}</small>`;
      box.appendChild(d);
    });
  }
  function setState(kind,title,hint){
    stateEl.className=`scan-state ${kind}`; stateEl.textContent=title;
    if(hint) hintEl.textContent=hint;
  }
  function dist(a,b){return Math.hypot(a.x-b.x,a.y-b.y);}
  function averageMove(a,b){
    if(!a||!b)return 1; let s=0;
    for(let i=0;i<4;i++)s+=dist(a[i],b[i]);
    return (s/4)/Math.hypot(processCanvas.width||1,processCanvas.height||1);
  }
  function smoothPoints(prev,next,alpha=.34){
    if(!prev)return next.map(p=>({...p}));
    return next.map((p,i)=>({x:prev[i].x*(1-alpha)+p.x*alpha,y:prev[i].y*(1-alpha)+p.y*alpha}));
  }
  function displayTransform(){
    const cw=wrap.clientWidth,ch=wrap.clientHeight,sw=processCanvas.width||360,sh=processCanvas.height||480;
    const scale=Math.min(cw/sw,ch/sh);
    return {scale,ox:(cw-sw*scale)/2,oy:(ch-sh*scale)/2};
  }
  function resizeGuide(){
    const rect=wrap.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2);
    guide.width=Math.max(1,Math.round(rect.width*dpr));guide.height=Math.max(1,Math.round(rect.height*dpr));
    guide.style.width=`${rect.width}px`;guide.style.height=`${rect.height}px`;gctx.setTransform(dpr,0,0,dpr,0,0);drawGuide();
  }
  function drawCorner(x,y,dx,dy,color){
    gctx.strokeStyle=color;gctx.lineWidth=4;gctx.beginPath();gctx.moveTo(x,y+dy*24);gctx.lineTo(x,y);gctx.lineTo(x+dx*24,y);gctx.stroke();
  }
  function drawGuide(){
    const cw=wrap.clientWidth,ch=wrap.clientHeight;gctx.clearRect(0,0,cw,ch);
    if(!smoothQuad){
      const px=Math.max(18,cw*.055),py=Math.max(28,ch*.07);
      gctx.strokeStyle='rgba(255,255,255,.45)';gctx.lineWidth=2;gctx.setLineDash([10,9]);
      gctx.strokeRect(px,py,cw-px*2,ch-py*2);gctx.setLineDash([]);return;
    }
    const t=displayTransform();const q=smoothQuad.map(p=>({x:t.ox+p.x*t.scale,y:t.oy+p.y*t.scale}));
    const ready=stableFrames>=STABLE_REQUIRED&&sharpness>=SHARPNESS_READY&&confidence>=.45;
    const color=ready?'#22c55e':'#f59e0b';
    gctx.fillStyle=ready?'rgba(34,197,94,.08)':'rgba(245,158,11,.06)';gctx.strokeStyle=color;gctx.lineWidth=3;
    gctx.beginPath();gctx.moveTo(q[0].x,q[0].y);q.slice(1).forEach(p=>gctx.lineTo(p.x,p.y));gctx.closePath();gctx.fill();gctx.stroke();
    drawCorner(q[0].x,q[0].y,1,1,color);drawCorner(q[1].x,q[1].y,-1,1,color);drawCorner(q[2].x,q[2].y,-1,-1,color);drawCorner(q[3].x,q[3].y,1,-1,color);
  }
  function setDetectionUI(found,move){
    if(!found){
      stableEl.hidden=true;qualityEl.textContent='—';diag(diagEdges,'warn','Buscando');
      if(tooClose)setState('focus','Aléjate un poco','Necesito ver los bordes completos de la etiqueta.');
      else setState('searching','Buscando etiqueta','Coloca la etiqueta completa en la imagen.');
      return;
    }
    diag(diagEdges,'ok','Detectando');stableEl.hidden=false;stableEl.textContent=`${Math.min(stableFrames,STABLE_REQUIRED)}/${STABLE_REQUIRED}`;
    const sharpText=sharpness>=SHARPNESS_READY?'Nítida':'Enfocando';qualityEl.textContent=`${sharpText} · ${Math.round(sharpness)} · ${Math.round(confidence*100)}%`;
    if(sharpness<SHARPNESS_READY)setState('focus','Enfocando','Mantén estable y evita reflejos.');
    else if(move>MOVE_READY||stableFrames<STABLE_REQUIRED)setState('stabilizing','Etiqueta detectada','Mantén estable: el marco seguirá la etiqueta.');
    else setState('ready','✓ Etiqueta lista','Autocaptura preparada.');
  }
  async function visionTick(){
    if(!stream||video.readyState<2||busy||!engine)return;
    let r;
    try{r=engine.analyze(video,processCanvas);}catch(e){console.warn('Embedded vision:',e);diag(diagEdges,'error','Error');return;}
    currentQuad=r.found?r.quad:null;sharpness=r.sharpness||0;confidence=r.confidence||0;tooClose=!!r.tooClose;
    if(currentQuad){
      noLabelFrames=0;smoothQuad=smoothPoints(smoothQuad,currentQuad);const move=averageMove(previousQuad,currentQuad);previousQuad=currentQuad.map(p=>({...p}));
      if(move<MOVE_READY&&sharpness>=SHARPNESS_READY&&confidence>=.45)stableFrames++;else stableFrames=Math.max(0,stableFrames-1);
      setDetectionUI(true,move);drawGuide();const now=Date.now();
      if(autoToggle.checked&&armed&&stableFrames>=STABLE_REQUIRED&&sharpness>=SHARPNESS_READY&&confidence>=.45&&now-lastAutoCapture>AUTO_COOLDOWN){lastAutoCapture=now;armed=false;await captureFrame(lastCode||'',true);}
    }else{
      noLabelFrames++;stableFrames=0;previousQuad=null;smoothQuad=null;setDetectionUI(false,1);drawGuide();if(noLabelFrames>=4)armed=true;
    }
  }
  function isBackLabel(label){const l=(label||'').toLowerCase();return /(back|rear|environment|trasera|posterior|arrière|rück|posteriore)/.test(l)&&!/(front|user|selfie|frontal)/.test(l);}
  async function discoverCameras(){
    const devices=await navigator.mediaDevices.enumerateDevices(),vids=devices.filter(d=>d.kind==='videoinput'),backs=vids.filter(d=>isBackLabel(d.label));
    cameras=backs.length?backs:vids.filter(d=>!/(front|user|selfie|frontal)/i.test(d.label));if(!cameras.length)cameras=vids;switchBtn.hidden=cameras.length<2;
  }
  async function tuneTrack(){
    if(!track)return;let caps={};try{caps=track.getCapabilities?track.getCapabilities():{};}catch(e){}
    const advanced=[];if(caps.zoom&&Number.isFinite(caps.zoom.min))advanced.push({zoom:caps.zoom.min});if(Array.isArray(caps.focusMode)&&caps.focusMode.includes('continuous'))advanced.push({focusMode:'continuous'});
    try{if(advanced.length)await track.applyConstraints({advanced});}catch(e){console.warn('Camera constraints:',e);}
    const settings=track.getSettings?track.getSettings():{};cameraInfo.hidden=false;cameraName.textContent=track.label||'Cámara trasera';
    focusInfo.textContent=(Array.isArray(caps.focusMode)&&caps.focusMode.includes('continuous'))?'Continuo solicitado':'Automático del dispositivo';
    if(caps.zoom){const z=settings.zoom??caps.zoom.min;zoomInfo.textContent=`${Number(z).toFixed(1)}× (mínimo ${Number(caps.zoom.min).toFixed(1)}×)`;}else zoomInfo.textContent='Sin control web de zoom';
    torchBtn.hidden=!(caps.torch||(Array.isArray(caps.torch)&&caps.torch.includes(true)));
  }
  async function stopCamera(){
    if(visionLoop){clearInterval(visionLoop);visionLoop=null;}if(barcodeLoop){clearInterval(barcodeLoop);barcodeLoop=null;}if(stream)stream.getTracks().forEach(t=>t.stop());
    stream=null;track=null;video.srcObject=null;torchOn=false;diag(diagCamera,'warn','Detenida');
  }
  async function openCamera(deviceId=null){
    await stopCamera();setState('searching','Abriendo cámara','Buscando cámara trasera…');
    const constraints={width:{ideal:1920},height:{ideal:1440},facingMode:deviceId?undefined:{ideal:'environment'},resizeMode:{ideal:'none'}};
    if(deviceId){delete constraints.facingMode;constraints.deviceId={exact:deviceId};}
    stream=await navigator.mediaDevices.getUserMedia({video:constraints,audio:false});track=stream.getVideoTracks()[0];video.srcObject=stream;await video.play();
    await tuneTrack();await discoverCameras();resizeGuide();captureBtn.disabled=false;startBtn.textContent='Cámara activa';diag(diagCamera,'ok','Activa');
    setState('searching','Buscando etiqueta','Muestra la etiqueta completa; no necesitas llenar toda la pantalla.');

    if('BarcodeDetector' in window){
      try{const supported=await BarcodeDetector.getSupportedFormats();detector=new BarcodeDetector({formats:supported.filter(x=>['qr_code','code_128','code_39','ean_13','ean_8','upc_a','upc_e','itf'].includes(x))});diag(diagBarcode,'ok','Disponible');
        barcodeLoop=setInterval(async()=>{if(busy||video.readyState<2||!detector)return;try{const codes=await detector.detect(video);if(codes.length){const c=codes[0].rawValue||'';if(c){lastCode=c;lastCodeAt=Date.now();}}else if(Date.now()-lastCodeAt>6000)lastCode='';}catch(e){}},700);
      }catch(e){diag(diagBarcode,'warn','No disponible');}
    }else diag(diagBarcode,'warn','No soportado');
    visionLoop=setInterval(visionTick,250);
  }
  function feedback(){
    try{if(navigator.vibrate)navigator.vibrate(70);audioCtx=audioCtx||new(window.AudioContext||window.webkitAudioContext)();const o=audioCtx.createOscillator(),g=audioCtx.createGain();o.frequency.value=880;g.gain.value=.04;o.connect(g);g.connect(audioCtx.destination);o.start();o.stop(audioCtx.currentTime+.08);}catch(e){}
  }
  async function buildLabelBlob(){
    if(engine&&smoothQuad){
      try{return await engine.captureLabel(video,processCanvas,fullCanvas,cropCanvas,smoothQuad);}catch(e){console.warn('Crop fallback:',e);}
    }
    fullCanvas.width=video.videoWidth;fullCanvas.height=video.videoHeight;fullCanvas.getContext('2d').drawImage(video,0,0,fullCanvas.width,fullCanvas.height);
    return new Promise(res=>fullCanvas.toBlob(res,'image/jpeg',0.88));
  }
  async function captureFrame(rawCode='',automatic=false){
    if(busy||!video.videoWidth)return;busy=true;captureBtn.disabled=true;setState('processing','Procesando etiqueta',smoothQuad?'Enderezando etiqueta y enviándola al OCR…':'Enviando captura completa al OCR…');
    try{
      const blob=await buildLabelBlob();const fd=new FormData();fd.append('image',blob,'label-crop.jpg');fd.append('raw_code',rawCode||'');fd.append('carrier',carrierHint.value||'');
      const r=await fetch(captureUrl,{method:'POST',body:fd});const data=await r.json();if(!r.ok||!data.ok)throw new Error(data.error||'No se pudo registrar');
      updateCounts(data.counts);const rt=data.route&&data.route.updated?`Ruta: ${data.route.stops} paradas · ${data.route.km} km aprox.`:'Ruta pendiente de dirección válida';
      result.innerHTML=`<strong>${data.duplicate?'Ya registrado':'✓ Paquete registrado'} · ${carrierLabel(data.carrier)}</strong><small>${data.tracking_code||''}</small><small>${data.address||'Dirección pendiente de revisión'}</small><small>Confianza ${Math.round((data.confidence||0)*100)}% · ${rt}</small>${data.intake_status==='review'?`<a class="btn tiny ghost" href="/driver/intake/${data.package_id}/review">Revisar ahora</a>`:''}`;
      feedback();setState('success','✓ Capturado','Retira este paquete y coloca el siguiente.');stableFrames=0;previousQuad=null;lastCode='';if(!automatic)armed=false;
    }catch(e){result.innerHTML=`<strong>No registrado</strong><small>${e.message}</small>`;setState('error','Reintentar','Acerca la etiqueta completa y evita reflejos.');armed=true;}
    finally{setTimeout(()=>{busy=false;captureBtn.disabled=false;},700);}
  }

  try{
    if(typeof window.RouteOpsVisionEngine==='function'){
      engine=new window.RouteOpsVisionEngine({processWidth:360});diag(diagEngine,'ok','Integrado');diag(diagEdges,'warn','Esperando cámara');
      setState('searching','Motor de visión listo','Abre la cámara para comenzar.');
    }else{
      diag(diagEngine,'error','No cargó');diag(diagEdges,'warn','Manual');setState('focus','Visión limitada','El motor local no cargó; captura manual sigue disponible.');
    }
  }catch(e){diag(diagEngine,'error','Error');setState('focus','Visión limitada','Captura manual disponible.');}

  diag(diagOcr,root.dataset.ocrReady==='1'?'ok':'warn',root.dataset.ocrReady==='1'?'Configurado':'Sin configurar');

  startBtn.addEventListener('click',async()=>{try{await openCamera();}catch(e){diag(diagCamera,'error','Error');setState('error','Cámara no disponible',e.message);}});
  captureBtn.addEventListener('click',()=>captureFrame(lastCode||'',false));
  torchBtn.addEventListener('click',async()=>{if(!track)return;torchOn=!torchOn;try{await track.applyConstraints({advanced:[{torch:torchOn}]});torchBtn.textContent=torchOn?'Apagar linterna':'Linterna';}catch(e){torchOn=false;torchBtn.textContent='Linterna no disponible';}});
  switchBtn.addEventListener('click',async()=>{if(!cameras.length)return;cameraIndex=(cameraIndex+1)%cameras.length;try{await openCamera(cameras[cameraIndex].deviceId);}catch(e){setState('error','No se pudo cambiar cámara',e.message);}});
  window.addEventListener('resize',resizeGuide);window.addEventListener('orientationchange',()=>setTimeout(resizeGuide,250));window.addEventListener('beforeunload',stopCamera);
})();
