/* H3 镜头切帧工具 - 前端逻辑 */
"use strict";

let taskId = null;
let scenes = [];
let curIdx = null;        // 当前选中镜头 index（1-based）
let polling = false;

// 全屏放大查看器状态
let vScale = 1;
let vDragging = false;
let vStartX = 0, vStartY = 0, vScrollLeft = 0, vScrollTop = 0;

const $ = (id) => document.getElementById(id);

/* ---------------- 历史记录 ---------------- */
async function loadHistory() {
  try {
    const resp = await fetch("/api/tasks");
    const data = await resp.json();
    const list = $("historyList");
    $("historyCount").textContent = data.tasks.length ? `（${data.tasks.length} 条）` : "";
    if (!data.tasks.length) {
      list.innerHTML = `<p class="history-empty muted">暂无记录，上传视频开始第一次切帧</p>`;
      return;
    }
    list.innerHTML = "";
    for (const t of data.tasks) {
      const card = document.createElement("div");
      card.className = "history-card" + (t.status === "error" || t.status === "empty" ? " err" : "");
      const statusText = t.status === "done" ? `${t.scene_count} 个镜头`
        : (t.status === "processing" ? "处理中" : (t.status === "error" ? "出错" : "无镜头"));
      card.innerHTML = `
        <div>
          <div class="hc-name">${escapeHtml(t.video_name)}</div>
          <div class="hc-meta">${escapeHtml(t.created)}</div>
        </div>
        <span class="hc-badge">${statusText}</span>`;
      card.addEventListener("click", () => openTask(t.task_id));
      list.appendChild(card);
    }
  } catch (e) { /* 历史加载失败不阻塞主流程 */ }
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function openTask(tid) {
  try {
    const resp = await fetch(`/api/task/${tid}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error);
    taskId = tid;
    scenes = data.scenes;
    renderResult(data);
  } catch (e) {
    showError("打开历史记录失败: " + e.message);
  }
}

function showHome() {
  taskId = null; scenes = []; curIdx = null; pickedFile = null;
  videoInput.value = "";
  $("fileInfo").style.display = "none";
  $("resultPanel").style.display = "none";
  $("topActions").style.display = "none";
  $("uploadPanel").style.display = "block";
  $("btnStart").disabled = true;
  $("progressWrap").style.display = "none";
  const box = document.querySelector(".error-box");
  if (box) box.remove();
  loadHistory();
}

/* ---------------- 上传 ---------------- */
const zone = $("uploadZone");
const videoInput = $("videoInput");
let pickedFile = null;

zone.addEventListener("click", () => videoInput.click());
zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragover"); });
zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
zone.addEventListener("drop", (e) => {
  e.preventDefault();
  zone.classList.remove("dragover");
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
videoInput.addEventListener("change", () => { if (videoInput.files.length) setFile(videoInput.files[0]); });

function setFile(f) {
  pickedFile = f;
  $("fileName").textContent = f.name;
  $("fileSize").textContent = (f.size / 1024 / 1024).toFixed(1) + " MB";
  $("fileInfo").style.display = "flex";
  $("btnStart").disabled = false;
}

$("btnStart").addEventListener("click", async () => {
  if (!pickedFile) return;
  const fd = new FormData();
  fd.append("video", pickedFile);
  fd.append("threshold", $("threshold").value || 27);
  fd.append("min_scene_len", $("minSceneLen").value || 0.5);

  $("progressWrap").style.display = "block";
  $("progressText").textContent = "正在上传并分析镜头切变...";
  $("btnStart").disabled = true;

  try {
    const resp = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "上传失败");
    taskId = data.task_id;
    pollStatus();
  } catch (err) {
    showError(err.message);
    $("progressWrap").style.display = "none";
    $("btnStart").disabled = false;
  }
});

function showError(msg) {
  let box = document.querySelector(".error-box");
  if (!box) {
    box = document.createElement("div");
    box.className = "error-box";
    $("uploadPanel").appendChild(box);
  }
  box.textContent = "❌ " + msg;
}

/* ---------------- 轮询任务状态 ---------------- */
function pollStatus() {
  if (polling) return;
  polling = true;
  const timer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/task/${taskId}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error);
      if (data.status === "processing") {
        $("progressText").textContent = "正在分析镜头切变...（视频越长越慢）";
        return;
      }
      clearInterval(timer);
      polling = false;
      if (data.status === "error") { showError(data.error); hideProgress(); return; }
      if (data.status === "empty") { showError(data.error || "未检测到镜头"); hideProgress(); return; }
      scenes = data.scenes;
      renderResult(data);
    } catch (err) {
      clearInterval(timer);
      polling = false;
      showError(err.message);
      hideProgress();
    }
  }, 900);
}

function hideProgress() {
  $("progressWrap").style.display = "none";
  $("btnStart").disabled = false;
}

/* ---------------- 渲染结果 ---------------- */
function renderResult(data) {
  $("uploadPanel").style.display = "none";
  $("resultPanel").style.display = "block";
  $("topActions").style.display = "flex";
  $("resultTitle").textContent = "🎬 " + data.video_name;
  $("resultMeta").textContent = `共 ${scenes.length} 个镜头`;
  $("player").src = data.video_url;

  renderGrid();
  curIdx = scenes.length ? scenes[0].index : null;
  selectScene(curIdx);
  loadHistory(); // 刷新历史列表中的镜头数
}

function renderGrid() {
  const grid = $("sceneGrid");
  grid.innerHTML = "";
  for (const s of scenes) {
    const item = document.createElement("div");
    item.className = "scene-item" + (s.hidden ? " hidden-item" : "") + (s.index === curIdx ? " active" : "");
    item.dataset.idx = s.index;
    item.innerHTML = `
      <img src="/api/task/${taskId}/frame/${s.first_frame}" loading="lazy" alt="镜头${s.index}">
      <div class="scene-hide-mark">已忽略</div>
      <div class="scene-badge">
        <span class="idx">#${s.index}</span>
        <span>${fmtTime(s.start_time_s)} - ${fmtTime(s.end_time_s)}</span>
      </div>`;
    item.addEventListener("click", () => { curIdx = s.index; selectScene(curIdx); });
    grid.appendChild(item);
  }
}

function fmtTime(t) { return t.toFixed(2) + "s"; }

/* ---------------- 选中镜头 & 编辑 ---------------- */
function selectScene(idx) {
  const s = scenes.find((x) => x.index === idx);
  if (!s) return;
  curIdx = idx;
  $("bigFrame").src = `/api/task/${taskId}/frame/${s.first_frame}`;
  $("bigFrameTime").textContent = `#${s.index}  ${fmtTime(s.start_time_s)} - ${fmtTime(s.end_time_s)}（${s.duration_s.toFixed(2)}s）`;
  $("fTitle").value = s.title || "";
  $("fShotSize").value = s.shot_size || "";
  $("fVisual").value = s.visual || "";
  $("fSpeaker").value = s.speaker || "";
  $("fTone").value = s.tone || "";
  $("fDialogue").value = s.dialogue || "";
  $("fAudio").value = s.audio_index || idx;
  $("saveTip").textContent = "";
  $("btnHide").textContent = s.hidden ? "🙈 取消忽略" : "🙈 忽略该镜头";
  document.querySelectorAll(".scene-item").forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.idx) === idx);
  });
}

function currentScene() { return scenes.find((x) => x.index === curIdx); }

$("btnSave").addEventListener("click", async () => {
  const s = currentScene();
  if (!s) return;
  const body = {
    title: $("fTitle").value.trim(),
    shot_size: $("fShotSize").value.trim(),
    visual: $("fVisual").value.trim(),
    speaker: $("fSpeaker").value.trim(),
    tone: $("fTone").value.trim(),
    dialogue: $("fDialogue").value.trim(),
    audio_index: Number($("fAudio").value) || s.index,
  };
  try {
    const resp = await fetch(`/api/task/${taskId}/scene/${curIdx}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error);
    Object.assign(s, body);
    $("saveTip").textContent = "✅ 已保存 镜头#" + curIdx;
  } catch (err) {
    $("saveTip").textContent = "❌ " + err.message;
  }
});

$("btnHide").addEventListener("click", async () => {
  const s = currentScene();
  if (!s) return;
  const body = { hidden: !s.hidden };
  const resp = await fetch(`/api/task/${taskId}/scene/${curIdx}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (!resp.ok) { $("saveTip").textContent = "❌ " + data.error; return; }
  s.hidden = data.scene.hidden;
  renderGrid();
  $("saveTip").textContent = s.hidden ? "已忽略该镜头（导出时跳过）" : "已恢复该镜头";
});

$("btnJump").addEventListener("click", () => {
  const s = currentScene();
  if (!s) return;
  $("player").currentTime = s.start_time_s;
  $("player").play().catch(() => {});
});

$("btnPrev").addEventListener("click", () => {
  const arr = scenes.map((x) => x.index).sort((a, b) => a - b);
  const i = arr.indexOf(curIdx);
  if (i > 0) { curIdx = arr[i - 1]; selectScene(curIdx); }
});
$("btnNext").addEventListener("click", () => {
  const arr = scenes.map((x) => x.index).sort((a, b) => a - b);
  const i = arr.indexOf(curIdx);
  if (i < arr.length - 1) { curIdx = arr[i + 1]; selectScene(curIdx); }
});

/* ---------------- 全屏放大查看器 ---------------- */
function openViewer(frame, label) {
  vScale = 1;
  const img = $("viewerImg");
  img.src = `/api/task/${taskId}/frame/${frame}`;
  img.style.width = "100%";
  $("viewerTitle").textContent = label;
  $("zoomLevel").textContent = "100%";
  $("viewer").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  $("viewerBody").scrollTop = 0;
  $("viewerBody").scrollLeft = 0;
}

function closeViewer() {
  $("viewer").classList.add("hidden");
  document.body.style.overflow = "";
}

function applyZoom() {
  $("viewerImg").style.width = (vScale * 100) + "%";
  $("zoomLevel").textContent = Math.round(vScale * 100) + "%";
}

$("bigFrameBox").addEventListener("click", () => {
  const s = currentScene();
  if (s) openViewer(s.first_frame, `#${s.index} 镜头首帧 · ${s.title || ""}`.trim());
});

$("zoomIn").addEventListener("click", () => { vScale = Math.min(8, vScale * 1.3); applyZoom(); });
$("zoomOut").addEventListener("click", () => { vScale = Math.max(0.1, vScale / 1.3); applyZoom(); });
$("zoomReset").addEventListener("click", () => { vScale = 1; applyZoom(); });
$("viewerClose").addEventListener("click", closeViewer);

const vBody = $("viewerBody");
vBody.addEventListener("wheel", (e) => {
  e.preventDefault();
  vScale = Math.min(8, Math.max(0.1, vScale * (e.deltaY < 0 ? 1.15 : 0.87)));
  applyZoom();
}, { passive: false });

vBody.addEventListener("mousedown", (e) => {
  if (e.target.id !== "viewerImg") return;
  vDragging = true;
  vStartX = e.clientX; vStartY = e.clientY;
  vScrollLeft = vBody.scrollLeft; vScrollTop = vBody.scrollTop;
  $("viewerImg").classList.add("dragging");
});
window.addEventListener("mousemove", (e) => {
  if (!vDragging) return;
  vBody.scrollLeft = vScrollLeft - (e.clientX - vStartX);
  vBody.scrollTop = vScrollTop - (e.clientY - vStartY);
});
window.addEventListener("mouseup", () => {
  vDragging = false;
  $("viewerImg").classList.remove("dragging");
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("viewer").classList.contains("hidden")) closeViewer();
});

/* ---------------- 台词提取（本地语音识别） ---------------- */
$("btnAsr").addEventListener("click", startAsr);

async function startAsr() {
  const btn = $("btnAsr");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "🎙 提取中（首次约1分钟加载模型）...";
  try {
    const resp = await fetch(`/api/task/${taskId}/asr`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "🎙 提取台词";
    $("saveTip").textContent = "❌ " + e.message;
    return;
  }
  const timer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/task/${taskId}`);
      const data = await resp.json();
      if (data.asr_status === "processing") return;
      clearInterval(timer);
      btn.disabled = false;
      btn.textContent = "🎙 提取台词";
      if (data.asr_status === "error") {
        $("saveTip").textContent = "❌ 台词提取失败：" + data.asr_error;
        return;
      }
      if (data.asr_status === "empty") {
        $("saveTip").textContent = "⚠️ " + (data.asr_error || "未识别到语音");
        return;
      }
      scenes = data.scenes;
      renderGrid();
      selectScene(curIdx);
      $("saveTip").textContent = "✅ 台词已提取并归入对应镜头，可修改后保存";
    } catch (e) {
      clearInterval(timer);
      btn.disabled = false;
      btn.textContent = "🎙 提取台词";
    }
  }, 1200);
}

/* ---------------- 导出 & 新任务 ---------------- */
$("btnExportTxt").addEventListener("click", () => {
  window.open(`/api/task/${taskId}/export?format=download`, "_blank");
});
$("btnExportJson").addEventListener("click", () => {
  window.open(`/api/task/${taskId}/export?format=json`, "_blank");
});
$("btnNewTask").addEventListener("click", showHome);
$("btnBack").addEventListener("click", showHome);

// 启动时加载历史记录
loadHistory();
