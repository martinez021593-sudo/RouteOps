/* RouteOps V0.3.1.2 — Embedded Vision Engine
 * Local, dependency-free label detector for the driver scanner.
 * It intentionally does NOT depend on OpenCV/CDNs at runtime.
 */
(() => {
  'use strict';

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

  function orderQuad(points) {
    if (!points || points.length !== 4) return null;
    const pts = points.map(p => ({x: Number(p.x), y: Number(p.y)}));
    const sums = pts.map(p => p.x + p.y);
    const diffs = pts.map(p => p.y - p.x);
    const tl = pts[sums.indexOf(Math.min(...sums))];
    const br = pts[sums.indexOf(Math.max(...sums))];
    const tr = pts[diffs.indexOf(Math.min(...diffs))];
    const bl = pts[diffs.indexOf(Math.max(...diffs))];
    const out = [tl, tr, br, bl];
    const unique = new Set(out.map(p => `${Math.round(p.x)}:${Math.round(p.y)}`));
    return unique.size === 4 ? out : null;
  }

  function quadArea(q) {
    if (!q) return 0;
    let area = 0;
    for (let i = 0; i < 4; i++) {
      const a = q[i], b = q[(i + 1) % 4];
      area += a.x * b.y - b.x * a.y;
    }
    return Math.abs(area / 2);
  }

  function percentileFromHistogram(hist, total, q) {
    const target = total * q;
    let acc = 0;
    for (let i = 0; i < hist.length; i++) {
      acc += hist[i];
      if (acc >= target) return i;
    }
    return 255;
  }

  function estimateSharpness(gray, w, h, bbox) {
    const x0 = clamp(Math.floor(bbox.x0), 2, w - 3);
    const x1 = clamp(Math.ceil(bbox.x1), 3, w - 2);
    const y0 = clamp(Math.floor(bbox.y0), 2, h - 3);
    const y1 = clamp(Math.ceil(bbox.y1), 3, h - 2);
    if (x1 - x0 < 20 || y1 - y0 < 20) return 0;
    let n = 0, sum = 0, sum2 = 0;
    for (let y = y0; y < y1; y += 3) {
      const row = y * w;
      for (let x = x0; x < x1; x += 3) {
        const i = row + x;
        const lap = 4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - w] - gray[i + w];
        sum += lap;
        sum2 += lap * lap;
        n++;
      }
    }
    if (!n) return 0;
    const mean = sum / n;
    return Math.max(0, sum2 / n - mean * mean);
  }

  function dilate(mask, gw, gh, radius = 1) {
    const out = new Uint8Array(mask.length);
    for (let y = 0; y < gh; y++) {
      for (let x = 0; x < gw; x++) {
        let on = 0;
        for (let dy = -radius; dy <= radius && !on; dy++) {
          const yy = y + dy;
          if (yy < 0 || yy >= gh) continue;
          for (let dx = -radius; dx <= radius; dx++) {
            const xx = x + dx;
            if (xx < 0 || xx >= gw) continue;
            if (mask[yy * gw + xx]) { on = 1; break; }
          }
        }
        out[y * gw + x] = on;
      }
    }
    return out;
  }

  function erode(mask, gw, gh, radius = 1) {
    const out = new Uint8Array(mask.length);
    for (let y = 0; y < gh; y++) {
      for (let x = 0; x < gw; x++) {
        let on = 1;
        for (let dy = -radius; dy <= radius && on; dy++) {
          const yy = y + dy;
          if (yy < 0 || yy >= gh) { on = 0; break; }
          for (let dx = -radius; dx <= radius; dx++) {
            const xx = x + dx;
            if (xx < 0 || xx >= gw || !mask[yy * gw + xx]) { on = 0; break; }
          }
        }
        out[y * gw + x] = on;
      }
    }
    return out;
  }

  function closeMask(mask, gw, gh) {
    // Fill text/barcode holes and join nearby bright/edge cells.
    let m = dilate(mask, gw, gh, 1);
    m = dilate(m, gw, gh, 1);
    m = erode(m, gw, gh, 1);
    return m;
  }

  function componentCandidates(mask, gw, gh, cell, frameW, frameH) {
    const seen = new Uint8Array(mask.length);
    const out = [];
    const frameArea = frameW * frameH;
    const dirs = [[1,0],[-1,0],[0,1],[0,-1],[1,1],[-1,-1],[1,-1],[-1,1]];

    for (let start = 0; start < mask.length; start++) {
      if (!mask[start] || seen[start]) continue;
      const q = [start];
      seen[start] = 1;
      let head = 0, count = 0;
      let minX = gw, maxX = 0, minY = gh, maxY = 0;
      let minSum = Infinity, maxSum = -Infinity, minDiff = Infinity, maxDiff = -Infinity;
      let pTL = null, pBR = null, pTR = null, pBL = null;

      while (head < q.length) {
        const idx = q[head++];
        const y = Math.floor(idx / gw), x = idx - y * gw;
        count++;
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
        const px = (x + 0.5) * cell, py = (y + 0.5) * cell;
        const sum = px + py, diff = py - px;
        if (sum < minSum) { minSum = sum; pTL = {x:px, y:py}; }
        if (sum > maxSum) { maxSum = sum; pBR = {x:px, y:py}; }
        if (diff < minDiff) { minDiff = diff; pTR = {x:px, y:py}; }
        if (diff > maxDiff) { maxDiff = diff; pBL = {x:px, y:py}; }

        for (const [dx,dy] of dirs) {
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || nx >= gw || ny < 0 || ny >= gh) continue;
          const ni = ny * gw + nx;
          if (mask[ni] && !seen[ni]) { seen[ni] = 1; q.push(ni); }
        }
      }

      const bx0 = minX * cell, by0 = minY * cell;
      const bx1 = Math.min(frameW, (maxX + 1) * cell), by1 = Math.min(frameH, (maxY + 1) * cell);
      const bw = bx1 - bx0, bh = by1 - by0;
      const bboxArea = bw * bh;
      const areaRatio = bboxArea / frameArea;
      const aspect = Math.max(bw, bh) / Math.max(1, Math.min(bw, bh));
      const fill = (count * cell * cell) / Math.max(1, bboxArea);
      if (areaRatio < 0.07 || areaRatio > 0.94 || aspect > 5.5 || fill < 0.13) continue;

      let quad = orderQuad([pTL,pTR,pBR,pBL]);
      if (!quad || quadArea(quad) < bboxArea * 0.28) {
        quad = [
          {x:bx0,y:by0},{x:bx1,y:by0},{x:bx1,y:by1},{x:bx0,y:by1}
        ];
      } else {
        // Expand a little so OCR does not cut label edges.
        const cx = quad.reduce((s,p)=>s+p.x,0)/4;
        const cy = quad.reduce((s,p)=>s+p.y,0)/4;
        quad = quad.map(p => ({
          x: clamp(cx + (p.x-cx)*1.08, 0, frameW-1),
          y: clamp(cy + (p.y-cy)*1.08, 0, frameH-1)
        }));
      }

      const centerX = (bx0 + bx1) / 2 / frameW;
      const centerY = (by0 + by1) / 2 / frameH;
      const centerPenalty = 1 - Math.min(0.6, Math.hypot(centerX - .5, centerY - .5) * .55);
      const rectangularity = Math.min(1, quadArea(quad) / Math.max(1, bboxArea));
      const score = bboxArea * (0.55 + fill) * centerPenalty * (0.65 + rectangularity * .35);
      const touches = bx0 < cell || by0 < cell || bx1 > frameW-cell || by1 > frameH-cell;
      out.push({quad,bbox:{x0:bx0,y0:by0,x1:bx1,y1:by1},areaRatio,fill,aspect,score,touches});
    }
    return out.sort((a,b)=>b.score-a.score);
  }

  class EmbeddedVisionEngine {
    constructor(options = {}) {
      this.processWidth = options.processWidth || 360;
      this.cell = options.cell || 5;
      this.version = 'routeops-embedded-vision-1.0';
    }

    analyze(video, canvas) {
      if (!video || !video.videoWidth || video.readyState < 2) return {found:false, reason:'video-not-ready'};
      const ratio = video.videoHeight / video.videoWidth;
      const w = this.processWidth;
      const h = Math.max(240, Math.round(w * ratio));
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext('2d', {willReadFrequently:true});
      ctx.drawImage(video, 0, 0, w, h);
      const image = ctx.getImageData(0,0,w,h);
      const rgba = image.data;
      const gray = new Uint8Array(w*h);
      const hist = new Uint32Array(256);
      let total = 0;
      for (let p=0, i=0; p<gray.length; p++, i+=4) {
        const y = Math.round(rgba[i]*0.299 + rgba[i+1]*0.587 + rgba[i+2]*0.114);
        gray[p] = y; hist[y]++; total++;
      }
      const p50 = percentileFromHistogram(hist,total,.50);
      const p75 = percentileFromHistogram(hist,total,.75);
      const p90 = percentileFromHistogram(hist,total,.90);
      const brightThreshold = clamp(Math.round(p75 + Math.max(8,(p90-p75)*.25)), 138, 232);

      const cell = this.cell;
      const gw = Math.ceil(w/cell), gh = Math.ceil(h/cell);
      const mask = new Uint8Array(gw*gh);

      let globalGrad = 0, gradSamples = 0;
      for (let y=1;y<h;y+=2) {
        const row=y*w;
        for (let x=1;x<w;x+=2) {
          const i=row+x;
          globalGrad += Math.abs(gray[i]-gray[i-1]) + Math.abs(gray[i]-gray[i-w]);
          gradSamples++;
        }
      }
      const gradBase = globalGrad / Math.max(1,gradSamples);
      const gradThreshold = clamp(gradBase*1.55, 24, 70);

      for (let gy=0;gy<gh;gy++) {
        const y0=gy*cell, y1=Math.min(h,y0+cell);
        for (let gx=0;gx<gw;gx++) {
          const x0=gx*cell, x1=Math.min(w,x0+cell);
          let lum=0,n=0,edge=0,edgeN=0;
          for (let y=y0;y<y1;y+=2) {
            const row=y*w;
            for (let x=x0;x<x1;x+=2) {
              const i=row+x; lum+=gray[i]; n++;
              if (x>0 && y>0) {
                edge += Math.abs(gray[i]-gray[i-1]) + Math.abs(gray[i]-gray[i-w]); edgeN++;
              }
            }
          }
          const avg=lum/Math.max(1,n), e=edge/Math.max(1,edgeN);
          // White/light label surface OR a dense text/barcode region.
          if (avg >= brightThreshold || (avg >= p50-4 && e >= gradThreshold)) mask[gy*gw+gx]=1;
        }
      }

      const closed = closeMask(mask,gw,gh);
      const candidates = componentCandidates(closed,gw,gh,cell,w,h);
      const best = candidates[0];
      if (!best) {
        return {found:false,tooClose:false,sharpness:0,confidence:0,frameWidth:w,frameHeight:h,diagnostics:{p50,p75,p90,brightThreshold,gradThreshold}};
      }

      const sharpness = estimateSharpness(gray,w,h,best.bbox);
      const confidence = clamp(
        0.25 + Math.min(.35,best.areaRatio*.45) + Math.min(.22,best.fill*.32) + Math.min(.18,sharpness/600),
        0, .98
      );
      const tooClose = best.touches && best.areaRatio > .70;
      return {
        found:true,quad:best.quad,sharpness,confidence,tooClose,
        areaRatio:best.areaRatio,frameWidth:w,frameHeight:h,
        diagnostics:{p50,p75,p90,brightThreshold,gradThreshold,fill:best.fill,aspect:best.aspect}
      };
    }

    mapQuadToVideo(quad, processCanvas, video) {
      if (!quad || !processCanvas.width || !video.videoWidth) return null;
      const sx = video.videoWidth/processCanvas.width;
      const sy = video.videoHeight/processCanvas.height;
      return quad.map(p=>({x:p.x*sx,y:p.y*sy}));
    }

    async captureLabel(video, processCanvas, fullCanvas, cropCanvas, quad) {
      fullCanvas.width = video.videoWidth;
      fullCanvas.height = video.videoHeight;
      const fctx = fullCanvas.getContext('2d',{willReadFrequently:true});
      fctx.drawImage(video,0,0,fullCanvas.width,fullCanvas.height);
      const mapped = this.mapQuadToVideo(quad,processCanvas,video);
      if (!mapped) return new Promise(res=>fullCanvas.toBlob(res,'image/jpeg',0.88));
      const q = orderQuad(mapped);
      if (!q) return new Promise(res=>fullCanvas.toBlob(res,'image/jpeg',0.88));

      const top=dist(q[0],q[1]), bottom=dist(q[3],q[2]), left=dist(q[0],q[3]), right=dist(q[1],q[2]);
      let outW=Math.max(360,Math.round(Math.max(top,bottom)));
      let outH=Math.max(360,Math.round(Math.max(left,right)));
      const maxDim=1400;
      const scale=Math.min(1,maxDim/Math.max(outW,outH));
      outW=Math.max(360,Math.round(outW*scale));
      outH=Math.max(360,Math.round(outH*scale));
      if (outW*outH>1450000) {
        const s=Math.sqrt(1450000/(outW*outH));
        outW=Math.round(outW*s); outH=Math.round(outH*s);
      }

      const src=fctx.getImageData(0,0,fullCanvas.width,fullCanvas.height);
      const dst=cropCanvas.getContext('2d').createImageData(outW,outH);
      const sd=src.data, dd=dst.data, sw=fullCanvas.width, sh=fullCanvas.height;
      const [tl,tr,br,bl]=q;
      for(let y=0;y<outH;y++){
        const v=outH===1?0:y/(outH-1);
        const lx=tl.x+(bl.x-tl.x)*v, ly=tl.y+(bl.y-tl.y)*v;
        const rx=tr.x+(br.x-tr.x)*v, ry=tr.y+(br.y-tr.y)*v;
        for(let x=0;x<outW;x++){
          const u=outW===1?0:x/(outW-1);
          const sx=clamp(Math.round(lx+(rx-lx)*u),0,sw-1);
          const sy=clamp(Math.round(ly+(ry-ly)*u),0,sh-1);
          const si=(sy*sw+sx)*4, di=(y*outW+x)*4;
          dd[di]=sd[si];dd[di+1]=sd[si+1];dd[di+2]=sd[si+2];dd[di+3]=255;
        }
      }
      cropCanvas.width=outW;cropCanvas.height=outH;
      cropCanvas.getContext('2d').putImageData(dst,0,0);
      return new Promise(res=>cropCanvas.toBlob(res,'image/jpeg',0.90));
    }
  }

  window.RouteOpsVisionEngine = EmbeddedVisionEngine;
})();
