/* Live screen: poll the current result, optionally advance the mock station.
 *
 * Threshold values, class rules and status wording are never computed here. This file
 * renders what /api/live returns and nothing else - the backend owns every decision,
 * so re-tuning a threshold in app/postprocess.py cannot leave the UI out of date.
 */
(function () {
  "use strict";

  var root = document.getElementById("live-root");
  var pollMs = root ? parseInt(root.getAttribute("data-poll-ms"), 10) || 2500 : 2500;
  var current = root ? parseInt(root.getAttribute("data-inspection-id"), 10) : null;

  var nextButton = document.getElementById("next-inspection");
  var autoToggle = document.getElementById("auto-advance");

  var cameraRoot = document.getElementById("live-camera-root");
  var cameraVideo = document.getElementById("live-camera-video");
  var cameraCanvas = document.getElementById("live-camera-canvas");
  var cameraStart = document.getElementById("live-camera-start");
  var cameraStop = document.getElementById("live-camera-stop");
  var cameraAuto = document.getElementById("live-camera-auto");
  var cameraDevice = document.getElementById("live-camera-device");
  var cameraPlaceholder = document.getElementById("live-camera-placeholder");
  var cameraStatus = document.getElementById("live-camera-status");
  var cameraError = document.getElementById("live-camera-error");
  var cameraStream = null;
  var cameraBusy = false;
  var cameraTimer = null;
  var liveSequence = 0;

  function text(id, value) {
    var el = document.getElementById(id);
    if (el) { el.textContent = value; }
  }

  function pxText(value, digits) {
    if (value === null || value === undefined) { return "\u2014"; }
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0
    }) + " px";
  }

  function renderBanner(summary) {
    var banner = document.getElementById("result-banner");
    if (!banner || !summary) { return; }
    banner.className = "banner banner--" + summary.state;
    banner.innerHTML = "";
    var headline = document.createElement("p");
    headline.className = "banner__headline";
    headline.textContent = summary.headline;
    banner.appendChild(headline);
    if (summary.detail) {
      var detail = document.createElement("p");
      detail.className = "banner__detail";
      detail.textContent = summary.detail;
      banner.appendChild(detail);
    }
    if (summary.reason) {
      var reason = document.createElement("p");
      reason.className = "banner__reason";
      reason.textContent = summary.reason;
      banner.appendChild(reason);
    }
  }

  function renderRegions(inspection) {
    var body = document.getElementById("region-rows");
    if (!body) { return; }
    body.innerHTML = "";
    inspection.regions.forEach(function (region) {
      var tr = document.createElement("tr");

      var th = document.createElement("th");
      th.setAttribute("scope", "row");
      th.textContent = region.region_index;
      tr.appendChild(th);

      [region.class_code,
       pxText(region.length_px),
       pxText(region.max_width_px),
       Number(region.area_px).toLocaleString()
      ].forEach(function (value, index) {
        var td = document.createElement("td");
        if (index > 0) { td.className = "num"; }
        td.textContent = value;
        tr.appendChild(td);
      });

      var actions = document.createElement("td");
      var link = document.createElement("a");
      link.className = "link-action";
      link.href = "/regions?inspection_id=" + inspection.inspection_id + "&region=" + region.region_index;
      link.textContent = "Open";
      actions.appendChild(link);
      tr.appendChild(actions);

      body.appendChild(tr);
    });
  }

  function render(payload) {
    if (!payload || !payload.inspection) { return; }
    var inspection = payload.inspection;

    if (inspection.inspection_id === current) { return; }
    current = inspection.inspection_id;
    if (root) { root.setAttribute("data-inspection-id", String(current)); }

    renderBanner(inspection.summary);
    renderRegions(inspection);

    var image = document.getElementById("live-overlay");
    if (image && inspection.overlay_image_url) {
      image.src = inspection.overlay_image_url + "?v=" + inspection.inspection_id;
      image.alt = "Inspection overlay for " + (inspection.product_id || "the current part")
        + " at source resolution, defect regions outlined and numbered";
    } else if (image && !inspection.overlay_image_url) {
      // A failure has no overlay: reload so the correct empty state renders server-side.
      window.location.reload();
      return;
    }

    var caption = document.getElementById("live-caption");
    if (caption) {
      caption.firstChild.nodeValue = " Product " + (inspection.product_id || "\u2014")
        + " \u00b7 " + inspection.captured_at
        + " \u00b7 " + (inspection.material || "unknown material")
        + " \u00b7 " + inspection.station + " ";
    }

    var openRegions = document.querySelector('a[href^="/regions?inspection_id"]');
    if (openRegions && inspection.regions.length) {
      openRegions.href = "/regions?inspection_id=" + inspection.inspection_id
        + "&region=" + inspection.regions[0].region_index;
    }
  }

  function refresh() {
    return fetch("/api/live", { headers: { "Accept": "application/json" } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) {
        if (!payload) { return; }
        // A failing station check changes the whole screen, not just the result.
        if (!payload.station_ok) { window.location.reload(); return; }
        render(payload);
      })
      .catch(function () { /* offline by design: keep the last good result on screen */ });
  }

  function advance() {
    if (nextButton) { nextButton.disabled = true; }
    return fetch("/api/demo/next", { method: "POST" })
      .then(function (response) {
        if (!response.ok) { window.location.reload(); return null; }
        return response.json();
      })
      .then(function (payload) { if (payload) { render(payload); } })
      .catch(function () { })
      .then(function () { if (nextButton) { nextButton.disabled = false; } });
  }

  function setCameraStatus(message) {
    if (cameraStatus) { cameraStatus.textContent = message || ""; }
  }

  function setCameraError(message) {
    if (!cameraError) { return; }
    cameraError.textContent = message || "";
    cameraError.hidden = !message;
  }

  function stopLiveCamera() {
    if (cameraTimer) { window.clearInterval(cameraTimer); cameraTimer = null; }
    if (cameraStream) {
      cameraStream.getTracks().forEach(function (track) { track.stop(); });
      cameraStream = null;
    }
    if (cameraVideo) { cameraVideo.srcObject = null; cameraVideo.hidden = true; }
    if (cameraPlaceholder) { cameraPlaceholder.hidden = false; }
    if (cameraStart) { cameraStart.disabled = false; }
    if (cameraStop) { cameraStop.disabled = true; }
    cameraBusy = false;
  }

  function cameraFailure(error) {
    var name = error && error.name ? error.name : "";
    if (name === "NotAllowedError" || name === "SecurityError") {
      return "Camera permission was refused. Allow it in the browser's site settings.";
    }
    if (name === "NotFoundError" || name === "OverconstrainedError") {
      return "No camera matched the selected device.";
    }
    if (name === "NotReadableError") { return "The camera is in use by another application."; }
    return "The live camera could not start: " + (error && error.message ? error.message : name || "unknown error");
  }

  function updateCameraDevices() {
    if (!cameraDevice || !navigator.mediaDevices.enumerateDevices) { return; }
    navigator.mediaDevices.enumerateDevices().then(function (devices) {
      var selected = cameraDevice.value;
      cameraDevice.innerHTML = '<option value="">Default camera</option>';
      devices.filter(function (device) { return device.kind === "videoinput"; })
        .forEach(function (device, index) {
          var option = document.createElement("option");
          option.value = device.deviceId;
          option.textContent = device.label || ("Camera " + (index + 1));
          cameraDevice.appendChild(option);
        });
      cameraDevice.value = selected;
    }).catch(function () { /* device labels are optional */ });
  }

  function submitLiveBlob(blob) {
    var form = new FormData();
    var prefix = (document.getElementById("live-product").value || "live").trim() || "live";
    liveSequence += 1;
    form.append("image", blob, "live-frame.png");
    form.append("source_type", "camera");
    form.append("material", document.getElementById("live-material").value);
    form.append("product_id", prefix + "/" + Date.now() + "-" + liveSequence);
    form.append("station_id", cameraRoot.getAttribute("data-station"));

    return fetch("/api/inspections", { method: "POST", body: form })
      .then(function (response) {
        return response.json().then(function (payload) {
          if (!response.ok) { throw new Error(payload.detail || payload.error || "Inspection failed"); }
          return payload;
        });
      })
      .then(function (payload) {
        if (!root) { window.location.reload(); return; }
        render(payload);
        setCameraStatus("Showing inspection " + payload.inspection_id + ". Next frame will run automatically.");
      });
  }

  function inspectLiveFrame() {
    if (!cameraStream || cameraBusy || !cameraAuto.checked || document.hidden) { return; }
    if (!cameraVideo.videoWidth || !cameraVideo.videoHeight) {
      setCameraStatus("Waiting for the first camera frame…");
      return;
    }
    cameraBusy = true;
    setCameraError(null);
    setCameraStatus("Inspecting current frame…");
    cameraCanvas.width = cameraVideo.videoWidth;
    cameraCanvas.height = cameraVideo.videoHeight;
    cameraCanvas.getContext("2d").drawImage(
      cameraVideo, 0, 0, cameraCanvas.width, cameraCanvas.height
    );
    cameraCanvas.toBlob(function (blob) {
      if (!blob) {
        cameraBusy = false;
        setCameraError("The current frame could not be encoded.");
        return;
      }
      submitLiveBlob(blob).catch(function (error) {
        setCameraError(error.message || "Automatic inspection failed.");
        setCameraStatus("Live inspection paused after an error.");
      }).then(function () { cameraBusy = false; });
    }, "image/png");
  }

  function startLiveCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraError("This browser exposes no camera API. Use localhost or HTTPS.");
      return;
    }
    if (cameraRoot.getAttribute("data-blocked") === "true") {
      setCameraError("Inspection is blocked by a failing Status check.");
      return;
    }
    setCameraError(null);
    setCameraStatus("Requesting camera permission…");
    cameraStart.disabled = true;
    var selected = cameraDevice.value;
    navigator.mediaDevices.getUserMedia({
      video: selected ? { deviceId: { exact: selected } } : {
        facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 960 }
      },
      audio: false
    }).then(function (stream) {
      cameraStream = stream;
      cameraVideo.srcObject = stream;
      cameraVideo.hidden = false;
      cameraPlaceholder.hidden = true;
      return cameraVideo.play();
    }).then(function () {
      cameraStop.disabled = false;
      setCameraStatus("Live camera running. Inspecting one frame at a time.");
      updateCameraDevices();
      inspectLiveFrame();
      cameraTimer = window.setInterval(inspectLiveFrame, pollMs);
    }).catch(function (error) {
      stopLiveCamera();
      setCameraStatus("");
      setCameraError(cameraFailure(error));
    });
  }

  if (nextButton) {
    nextButton.addEventListener("click", advance);
  }

  if (cameraStart) { cameraStart.addEventListener("click", startLiveCamera); }
  if (cameraStop) {
    cameraStop.addEventListener("click", function () {
      stopLiveCamera();
      setCameraStatus("Live inspection stopped.");
    });
  }
  if (cameraDevice) {
    cameraDevice.addEventListener("change", function () {
      if (cameraStream) { stopLiveCamera(); startLiveCamera(); }
    });
  }
  if (cameraAuto) {
    cameraAuto.addEventListener("change", function () {
      if (cameraAuto.checked) { inspectLiveFrame(); }
      else { setCameraStatus("Camera preview running; automatic inspection paused."); }
    });
  }
  window.addEventListener("pagehide", stopLiveCamera);

  window.setInterval(function () {
    if (document.hidden) { return; }
    if (autoToggle && autoToggle.checked) { advance(); } else { refresh(); }
  }, pollMs);
})();
