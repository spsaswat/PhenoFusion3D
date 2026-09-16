(function () {
  "use strict";

  const packed = window.FUSION_VIEWER_MODELS;
  const canvas = document.getElementById("fusion-viewer-canvas");
  if (!packed || !canvas) return;

  const context = canvas.getContext("2d", { alpha: false });
  const plantButtons = Array.from(document.querySelectorAll("[data-viewer-plant]"));
  const indexSelect = document.getElementById("viewer-index");
  const pointSize = document.getElementById("viewer-point-size");
  const autoRotate = document.getElementById("viewer-auto-rotate");
  const resetButton = document.getElementById("viewer-reset");
  const zoomInButton = document.getElementById("viewer-zoom-in");
  const zoomOutButton = document.getElementById("viewer-zoom-out");
  const focusButton = document.getElementById("viewer-focus");
  const status = document.getElementById("viewer-status");
  const download = document.getElementById("viewer-download");
  const inspectorTitle = document.getElementById("inspector-title");
  const inspectorMessage = document.getElementById("inspector-message");
  const inspectorDetails = document.getElementById("inspector-details");
  const inspectorIndices = document.getElementById("inspector-indices");
  const spectrumCanvas = document.getElementById("viewer-spectrum-canvas");
  const spectrumReadout = document.getElementById("spectrum-readout");
  const spectrumContext = spectrumCanvas ? spectrumCanvas.getContext("2d") : null;

  const decodedModels = {};
  const decodedSpectra = {};
  const wavelengthBytes = decodeBase64(packed.wavelengthsF32);
  const wavelengths = new Float32Array(wavelengthBytes.buffer);
  const indexNames = packed.indices;
  const projected = { x: new Float32Array(0), y: new Float32Array(0), depth: new Float32Array(0) };

  let plantKey = "coleus";
  let indexName = "NDVI";
  let rotationX = -0.48;
  let rotationY = 0.42;
  let zoom = 0.88;
  let panX = 0;
  let panY = 0;
  let dragging = false;
  let panning = false;
  let dragged = false;
  let previousX = 0;
  let previousY = 0;
  let pointerDownX = 0;
  let pointerDownY = 0;
  let animationFrame = 0;
  let selectedPoint = null;
  let currentSpectrum = null;

  function decodeBase64(text) {
    const binary = atob(text);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function typedArray(text, Type) {
    const bytes = decodeBase64(text);
    return new Type(bytes.buffer);
  }

  function modelFor(key) {
    if (decodedModels[key]) return decodedModels[key];
    const source = packed.models[key];
    const colours = {};
    Object.keys(source.colours).forEach((name) => { colours[name] = decodeBase64(source.colours[name]); });
    decodedModels[key] = { meta: source, positions: typedArray(source.positions, Float32Array), colours };
    return decodedModels[key];
  }

  function spectraFor(key) {
    if (decodedSpectra[key]) return decodedSpectra[key];
    const source = packed.spectralPoints[key];
    decodedSpectra[key] = {
      meta: source,
      spectra: typedArray(source.spectraU16, Uint16Array),
      hsiPixels: typedArray(source.hsiPixelsU16, Uint16Array),
      rgbdPixels: typedArray(source.rgbdPixelsU16, Uint16Array),
      indices: typedArray(source.indicesF32, Float32Array),
    };
    return decodedSpectra[key];
  }

  function fitCanvas(target) {
    const rect = target.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(320, Math.round(rect.width * ratio));
    const height = Math.max(180, Math.round(rect.height * ratio));
    if (target.width !== width || target.height !== height) {
      target.width = width;
      target.height = height;
    }
    return ratio;
  }

  function ensureProjectionCapacity(points) {
    if (projected.x.length === points) return;
    projected.x = new Float32Array(points);
    projected.y = new Float32Array(points);
    projected.depth = new Float32Array(points);
  }

  function render() {
    const ratio = fitCanvas(canvas);
    const model = modelFor(plantKey);
    const positions = model.positions;
    const colours = model.colours[indexName];
    const width = canvas.width;
    const height = canvas.height;
    const scale = Math.min(width, height) * 0.42 * zoom;
    const centreX = width * (0.5 + panX);
    const centreY = height * (0.52 + panY);
    const cosX = Math.cos(rotationX);
    const sinX = Math.sin(rotationX);
    const cosY = Math.cos(rotationY);
    const sinY = Math.sin(rotationY);
    const specimenCount = model.meta.displaySpecimenVertices;
    const baseSize = Number(pointSize.value) * ratio;
    ensureProjectionCapacity(positions.length / 3);

    context.fillStyle = "#071d18";
    context.fillRect(0, 0, width, height);
    const glow = context.createRadialGradient(centreX, centreY, 0, centreX, centreY, Math.max(width, height) * 0.68);
    glow.addColorStop(0, "rgba(48,103,85,.34)");
    glow.addColorStop(1, "rgba(7,29,24,0)");
    context.fillStyle = glow;
    context.fillRect(0, 0, width, height);

    for (let point = 0, offset = 0; offset < positions.length; point += 1, offset += 3) {
      const x = positions[offset];
      const y = positions[offset + 1];
      const z = positions[offset + 2];
      const x1 = x * cosY + z * sinY;
      const z1 = -x * sinY + z * cosY;
      const y2 = y * cosX - z1 * sinX;
      const depth = y * sinX + z1 * cosX;
      const perspective = 1 / Math.max(0.55, 1.75 - depth * 0.34);
      const screenX = centreX + x1 * scale * perspective;
      const screenY = centreY - y2 * scale * perspective;
      projected.x[point] = screenX;
      projected.y[point] = screenY;
      projected.depth[point] = depth;
      if (screenX < -8 || screenX > width + 8 || screenY < -8 || screenY > height + 8) continue;
      const colourOffset = point * 3;
      context.fillStyle = `rgb(${colours[colourOffset]},${colours[colourOffset + 1]},${colours[colourOffset + 2]})`;
      const measured = point >= specimenCount;
      const size = Math.max(1, baseSize * perspective * (measured ? 1.35 : 0.92));
      context.globalAlpha = measured ? 0.98 : 0.48;
      context.fillRect(screenX - size / 2, screenY - size / 2, size, size);
    }
    context.globalAlpha = 1;

    if (selectedPoint && selectedPoint.model === plantKey) {
      const selectedX = projected.x[selectedPoint.point];
      const selectedY = projected.y[selectedPoint.point];
      if (Number.isFinite(selectedX) && Number.isFinite(selectedY)) {
        context.beginPath();
        context.arc(selectedX, selectedY, Math.max(8, baseSize * 3.4), 0, Math.PI * 2);
        context.strokeStyle = "#fff6a8";
        context.lineWidth = Math.max(2, ratio * 1.5);
        context.stroke();
        context.beginPath();
        context.arc(selectedX, selectedY, Math.max(3, baseSize), 0, Math.PI * 2);
        context.fillStyle = "#ffffff";
        context.fill();
      }
    }

    const geometryLabel = plantKey === "global_scene" ? "sampled legacy scene points" : "sampled grey specimen points";
    status.textContent = `${model.meta.label} · ${indexName} · zoom ${zoom.toFixed(1)}× · ${model.meta.measuredVertices.toLocaleString()} measured spectral points + ${model.meta.displaySpecimenVertices.toLocaleString()} ${geometryLabel}`;
    if (plantKey === "global_scene") {
      download.href = `../global_placement/global_scene_${indexName.toLowerCase()}_sampled.ply`;
      download.textContent = `Download sampled global scene + ${indexName} PLY`;
    } else {
      download.href = `${plantKey}/${plantKey}_${indexName.toLowerCase()}_on_specimen.ply`;
      download.textContent = `Download full ${model.meta.label} ${indexName} PLY`;
    }
  }

  function measuredReference(model, pointIndex) {
    const ordinal = pointIndex - model.meta.displaySpecimenVertices;
    if (ordinal < 0) return null;
    for (const segment of model.meta.measuredSegments) {
      if (ordinal >= segment.start && ordinal < segment.start + segment.count) {
        return { plant: segment.plant, localIndex: ordinal - segment.start };
      }
    }
    return null;
  }

  function displayedCoordinate(model, pointIndex) {
    const offset = pointIndex * 3;
    const radius = model.meta.normalisationRadiusMetres;
    const centre = model.meta.centreMetres;
    return [
      model.positions[offset] * radius + centre[0],
      model.positions[offset + 1] * radius + centre[1],
      model.positions[offset + 2] * radius + centre[2],
    ];
  }

  function clearInspector(message) {
    inspectorTitle.textContent = "Select a measured spectral point";
    inspectorMessage.textContent = message || "Click a coloured point in the model. Grey points are RGB-D geometry without a directly measured hyperspectral spectrum.";
    inspectorDetails.hidden = true;
    currentSpectrum = null;
    drawSpectrum(null);
  }

  function inspectPoint(pointIndex) {
    const model = modelFor(plantKey);
    selectedPoint = { model: plantKey, point: pointIndex };
    autoRotate.checked = false;
    const reference = measuredReference(model, pointIndex);
    if (!reference) {
      inspectorTitle.textContent = "Unmeasured RGB-D geometry";
      inspectorMessage.textContent = "This grey point contributes 3D shape, but the hyperspectral cameras did not directly measure this surface. No spectral curve is invented for it.";
      inspectorDetails.hidden = true;
      currentSpectrum = null;
      drawSpectrum(null);
      render();
      return;
    }

    const data = spectraFor(reference.plant);
    const coordinate = displayedCoordinate(model, pointIndex);
    const pixelOffset = reference.localIndex * 2;
    const indexOffset = reference.localIndex * indexNames.length;
    const spectrumOffset = reference.localIndex * data.meta.bands;
    const plantLabel = packed.models[reference.plant].label;
    const coordinateSystem = plantKey === "global_scene" ? "Global ICP XYZ" : "Selected camera-frame XYZ";
    inspectorTitle.textContent = `${plantLabel} · measured spectral point ${String(reference.localIndex + 1).padStart(4, "0")}`;
    inspectorMessage.textContent = "This coloured 3D point carries one complete calibrated 427-band spectrum.";
    inspectorDetails.hidden = false;
    inspectorDetails.querySelector("[data-field=coordinate]").textContent = `${coordinateSystem}: ${coordinate.map((value) => value.toFixed(4)).join(", ")} m`;
    inspectorDetails.querySelector("[data-field=hsi]").textContent = `Processed hyperspectral pixel: row ${data.hsiPixels[pixelOffset]}, column ${data.hsiPixels[pixelOffset + 1]}`;
    inspectorDetails.querySelector("[data-field=rgbd]").textContent = `RGB-D pixel: u ${data.rgbdPixels[pixelOffset]}, v ${data.rgbdPixels[pixelOffset + 1]}`;
    inspectorIndices.innerHTML = indexNames.map((name, index) => {
      const value = data.indices[indexOffset + index];
      return `<div><span>${name}</span><b>${Number.isFinite(value) ? value.toFixed(4) : "invalid"}</b></div>`;
    }).join("");
    currentSpectrum = { data, offset: spectrumOffset, plantLabel, localIndex: reference.localIndex };
    drawSpectrum(currentSpectrum);
    render();
  }

  function drawSpectrum(selection, hoverBand) {
    if (!spectrumContext || !spectrumCanvas) return;
    const ratio = fitCanvas(spectrumCanvas);
    const width = spectrumCanvas.width;
    const height = spectrumCanvas.height;
    const left = 58 * ratio;
    const right = 18 * ratio;
    const top = 20 * ratio;
    const bottom = 42 * ratio;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    spectrumContext.fillStyle = "#fbfdf9";
    spectrumContext.fillRect(0, 0, width, height);
    spectrumContext.strokeStyle = "#d7e2db";
    spectrumContext.lineWidth = ratio;
    spectrumContext.font = `${11 * ratio}px system-ui`;
    spectrumContext.fillStyle = "#52655c";
    spectrumContext.textAlign = "right";
    spectrumContext.textBaseline = "middle";
    for (let value = 0; value <= 1.001; value += 0.25) {
      const y = top + (1 - value) * plotHeight;
      spectrumContext.beginPath();
      spectrumContext.moveTo(left, y);
      spectrumContext.lineTo(width - right, y);
      spectrumContext.stroke();
      spectrumContext.fillText(value.toFixed(2), left - 8 * ratio, y);
    }
    const wavelengthMin = wavelengths[0];
    const wavelengthMax = wavelengths[wavelengths.length - 1];
    spectrumContext.textAlign = "center";
    spectrumContext.textBaseline = "top";
    [400, 700, 1000, 1300, 1600].forEach((wavelength) => {
      const x = left + ((wavelength - wavelengthMin) / (wavelengthMax - wavelengthMin)) * plotWidth;
      spectrumContext.beginPath();
      spectrumContext.moveTo(x, top);
      spectrumContext.lineTo(x, height - bottom);
      spectrumContext.stroke();
      spectrumContext.fillText(String(wavelength), x, height - bottom + 8 * ratio);
    });
    spectrumContext.fillText("Wavelength (nm)", left + plotWidth / 2, height - 17 * ratio);
    spectrumContext.save();
    spectrumContext.translate(14 * ratio, top + plotHeight / 2);
    spectrumContext.rotate(-Math.PI / 2);
    spectrumContext.fillText("Reflectance", 0, 0);
    spectrumContext.restore();
    if (!selection) {
      spectrumContext.fillStyle = "#6b7d74";
      spectrumContext.textAlign = "center";
      spectrumContext.textBaseline = "middle";
      spectrumContext.font = `600 ${14 * ratio}px system-ui`;
      spectrumContext.fillText("Select a coloured point to display its 427-band spectrum", left + plotWidth / 2, top + plotHeight / 2);
      spectrumReadout.textContent = "No spectrum selected.";
      return;
    }

    const values = selection.data.spectra;
    const scale = selection.data.meta.quantisationScale;
    const offset = selection.offset;
    spectrumContext.beginPath();
    for (let band = 0; band < wavelengths.length; band += 1) {
      const value = values[offset + band] / scale;
      const x = left + ((wavelengths[band] - wavelengthMin) / (wavelengthMax - wavelengthMin)) * plotWidth;
      const y = top + (1 - value) * plotHeight;
      if (band === 0) spectrumContext.moveTo(x, y);
      else spectrumContext.lineTo(x, y);
    }
    spectrumContext.strokeStyle = "#0a7251";
    spectrumContext.lineWidth = 2.2 * ratio;
    spectrumContext.stroke();
    if (Number.isInteger(hoverBand)) {
      const value = values[offset + hoverBand] / scale;
      const x = left + ((wavelengths[hoverBand] - wavelengthMin) / (wavelengthMax - wavelengthMin)) * plotWidth;
      const y = top + (1 - value) * plotHeight;
      spectrumContext.beginPath();
      spectrumContext.arc(x, y, 4 * ratio, 0, Math.PI * 2);
      spectrumContext.fillStyle = "#d34c28";
      spectrumContext.fill();
      spectrumReadout.textContent = `${selection.plantLabel} point ${selection.localIndex + 1} · ${wavelengths[hoverBand].toFixed(1)} nm · reflectance ${value.toFixed(4)}`;
    } else {
      spectrumReadout.textContent = `${selection.plantLabel} point ${selection.localIndex + 1} · move across the chart to inspect an individual wavelength.`;
    }
  }

  function selectNearest(event) {
    const rect = canvas.getBoundingClientRect();
    const ratioX = canvas.width / rect.width;
    const ratioY = canvas.height / rect.height;
    const targetX = (event.clientX - rect.left) * ratioX;
    const targetY = (event.clientY - rect.top) * ratioY;
    const radius = 14 * Math.max(ratioX, ratioY);
    let nearest = -1;
    let nearestDistance = radius * radius;
    for (let point = 0; point < projected.x.length; point += 1) {
      const dx = projected.x[point] - targetX;
      const dy = projected.y[point] - targetY;
      const distance = dx * dx + dy * dy;
      if (distance <= nearestDistance) { nearestDistance = distance; nearest = point; }
    }
    if (nearest >= 0) inspectPoint(nearest);
    else clearInspector("No point was close enough to the click. Zoom in, increase point size, and click a coloured point.");
  }

  function zoomAt(factor, clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const oldZoom = zoom;
    zoom = Math.max(0.18, Math.min(40, zoom * factor));
    const actualFactor = zoom / oldZoom;
    const pointerX = clientX === undefined ? canvas.width / 2 : (clientX - rect.left) * canvas.width / rect.width;
    const pointerY = clientY === undefined ? canvas.height / 2 : (clientY - rect.top) * canvas.height / rect.height;
    const centreX = canvas.width * (0.5 + panX);
    const centreY = canvas.height * (0.52 + panY);
    const newCentreX = pointerX - actualFactor * (pointerX - centreX);
    const newCentreY = pointerY - actualFactor * (pointerY - centreY);
    panX = newCentreX / canvas.width - 0.5;
    panY = newCentreY / canvas.height - 0.52;
    render();
  }

  function focusSelected() {
    if (!selectedPoint || selectedPoint.model !== plantKey) return;
    zoom = Math.max(zoom, 12);
    render();
    panX += (canvas.width / 2 - projected.x[selectedPoint.point]) / canvas.width;
    panY += (canvas.height / 2 - projected.y[selectedPoint.point]) / canvas.height;
    render();
  }

  function resetView() {
    rotationX = -0.48;
    rotationY = 0.42;
    zoom = 0.88;
    panX = 0;
    panY = 0;
    render();
  }

  function animate() {
    if (autoRotate.checked && !dragging && !selectedPoint) { rotationY += 0.0035; render(); }
    animationFrame = requestAnimationFrame(animate);
  }

  function selectPlant(nextPlant) {
    plantKey = nextPlant;
    selectedPoint = null;
    plantButtons.forEach((button) => {
      const selected = button.dataset.viewerPlant === plantKey;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    clearInspector();
    resetView();
  }

  plantButtons.forEach((button) => button.addEventListener("click", () => selectPlant(button.dataset.viewerPlant)));
  indexSelect.addEventListener("change", () => { indexName = indexSelect.value; render(); });
  pointSize.addEventListener("input", render);
  resetButton.addEventListener("click", () => { selectedPoint = null; clearInspector(); resetView(); });
  zoomInButton.addEventListener("click", () => zoomAt(1.55));
  zoomOutButton.addEventListener("click", () => zoomAt(1 / 1.55));
  focusButton.addEventListener("click", focusSelected);

  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    dragged = false;
    panning = event.shiftKey || event.button === 1 || event.button === 2;
    pointerDownX = previousX = event.clientX;
    pointerDownY = previousY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const dx = event.clientX - previousX;
    const dy = event.clientY - previousY;
    if (Math.abs(event.clientX - pointerDownX) + Math.abs(event.clientY - pointerDownY) > 4) dragged = true;
    if (panning) {
      panX += dx / canvas.clientWidth;
      panY += dy / canvas.clientHeight;
    } else {
      rotationY += dx * 0.009;
      rotationX += dy * 0.009;
      rotationX = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, rotationX));
    }
    previousX = event.clientX;
    previousY = event.clientY;
    render();
  });
  canvas.addEventListener("pointerup", (event) => {
    const wasDragged = dragged;
    dragging = false;
    canvas.releasePointerCapture(event.pointerId);
    if (!wasDragged && event.button === 0) selectNearest(event);
  });
  canvas.addEventListener("pointercancel", () => { dragging = false; });
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("wheel", (event) => { event.preventDefault(); zoomAt(event.deltaY > 0 ? 0.86 : 1.16, event.clientX, event.clientY); }, { passive: false });
  canvas.addEventListener("dblclick", (event) => { selectNearest(event); focusSelected(); });
  canvas.addEventListener("keydown", (event) => {
    const step = 0.09;
    if (event.key === "ArrowLeft" && event.shiftKey) panX -= 0.04;
    else if (event.key === "ArrowRight" && event.shiftKey) panX += 0.04;
    else if (event.key === "ArrowUp" && event.shiftKey) panY -= 0.04;
    else if (event.key === "ArrowDown" && event.shiftKey) panY += 0.04;
    else if (event.key === "ArrowLeft") rotationY -= step;
    else if (event.key === "ArrowRight") rotationY += step;
    else if (event.key === "ArrowUp") rotationX -= step;
    else if (event.key === "ArrowDown") rotationX += step;
    else if (event.key === "+" || event.key === "=") { zoomAt(1.3); event.preventDefault(); return; }
    else if (event.key === "-" || event.key === "_") { zoomAt(1 / 1.3); event.preventDefault(); return; }
    else if (event.key === "f" || event.key === "F") { focusSelected(); event.preventDefault(); return; }
    else return;
    event.preventDefault();
    render();
  });

  if (spectrumCanvas) {
    spectrumCanvas.addEventListener("pointermove", (event) => {
      if (!currentSpectrum) return;
      const rect = spectrumCanvas.getBoundingClientRect();
      const ratio = spectrumCanvas.width / rect.width;
      const left = 58 * ratio;
      const right = 18 * ratio;
      const x = (event.clientX - rect.left) * ratio;
      const fraction = Math.max(0, Math.min(1, (x - left) / (spectrumCanvas.width - left - right)));
      const targetWavelength = wavelengths[0] + fraction * (wavelengths[wavelengths.length - 1] - wavelengths[0]);
      let band = 0;
      let best = Infinity;
      for (let index = 0; index < wavelengths.length; index += 1) {
        const distance = Math.abs(wavelengths[index] - targetWavelength);
        if (distance < best) { best = distance; band = index; }
      }
      drawSpectrum(currentSpectrum, band);
    });
    spectrumCanvas.addEventListener("pointerleave", () => drawSpectrum(currentSpectrum));
  }

  window.addEventListener("resize", () => { render(); drawSpectrum(currentSpectrum); });
  selectPlant(plantKey);
  cancelAnimationFrame(animationFrame);
  animate();
})();
