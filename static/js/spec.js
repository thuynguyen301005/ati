const form = document.getElementById("specForm");
const requirement = document.getElementById("requirement");
const charCount = document.getElementById("charCount");
const generateBtn = document.getElementById("generateBtn");
const errorBox = document.getElementById("errorBox");
const results = document.getElementById("results");
const artifactTabs = document.getElementById("artifactTabs");
const artifactContent = document.getElementById("artifactContent");
const pipelineItems = [...document.querySelectorAll("#pipelineList li")];
let project = null;
let activeKey = "stories";

requirement.addEventListener("input", () => {
  charCount.textContent = `${requirement.value.length} / 30000`;
});

const uploadZone = document.getElementById("uploadZone");
const specFile = document.getElementById("specFile");
const uploadStatus = document.getElementById("uploadStatus");

async function uploadSpec(file) {
  if (!file) return;
  errorBox.textContent = "";
  uploadZone.classList.add("loading");
  uploadStatus.textContent = `Reading ${file.name}...`;
  try {
    const body = new FormData();
    body.append("file", file);
    const data = await api("/api/spec/upload", { method: "POST", body });
    // Giữ lại phần người dùng đã gõ, nối nội dung file vào sau.
    const existing = requirement.value.trim();
    const combined = existing ? `${existing}\n\n--- ${data.filename} ---\n${data.text}` : data.text;
    requirement.value = combined.slice(0, 30000);
    requirement.dispatchEvent(new Event("input"));
    const cut = combined.length > 30000 ? " Text was cut to 30,000 characters." : "";
    uploadStatus.textContent = `Loaded ${data.filename} (${data.chars.toLocaleString()} characters).${cut}`;
  } catch (error) {
    uploadStatus.textContent = "Drop or click to choose .txt, .md, .pdf, or .docx (max 10 MB).";
    errorBox.textContent = error.message;
  } finally {
    uploadZone.classList.remove("loading");
    specFile.value = "";
  }
}

specFile.addEventListener("change", () => uploadSpec(specFile.files[0]));
uploadZone.addEventListener("dragover", (event) => { event.preventDefault(); uploadZone.classList.add("dragging"); });
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragging"));
uploadZone.addEventListener("drop", (event) => {
  event.preventDefault();
  uploadZone.classList.remove("dragging");
  uploadSpec(event.dataTransfer.files[0]);
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    requirement.value = button.dataset.prompt;
    requirement.dispatchEvent(new Event("input"));
    requirement.focus();
  });
});

function selectedStages() {
  return pipelineItems.filter((item) => item.querySelector("input").checked).map((item) => item.dataset.stage);
}

function syncStageState() {
  pipelineItems.forEach((item) => {
    item.classList.toggle("skipped", !item.querySelector("input").checked);
    item.classList.remove("done");
  });
  document.getElementById("stageCount").textContent = `${selectedStages().length} of ${pipelineItems.length} stages selected`;
}

pipelineItems.forEach((item) => item.querySelector("input").addEventListener("change", syncStageState));

document.querySelectorAll("[data-select]").forEach((button) => {
  button.addEventListener("click", () => {
    pipelineItems.forEach((item) => { item.querySelector("input").checked = button.dataset.select === "all"; });
    syncStageState();
  });
});

function setLoading(loading) {
  generateBtn.disabled = loading;
  generateBtn.querySelector("span").textContent = loading ? "Agent is building..." : "Generate software plan";
  pipelineItems.forEach((item) => {
    item.classList.toggle("working", loading && item.querySelector("input").checked);
    item.querySelector("input").disabled = loading;
  });
}

// Escape mọi nội dung AI/người dùng trước khi chèn vào HTML.
function text(value) {
  return value == null ? "" : String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new Error("Please sign in again.");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function jsonOptions(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function renderUmlDiagram(heading, svg, error, block) {
  const details = block || {};
  artifactContent.insertAdjacentHTML("beforeend", `<h4 class="diagram-heading">${text(heading)}</h4>`);
  if (svg) {
    artifactContent.insertAdjacentHTML("beforeend", `<div class="architecture-preview">${svg}</div>`);
  } else {
    artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-note">Diagram could not be rendered. ${text(error || "No DOT source returned.")}</div>`);
  }

  (details.actors || []).forEach((actor) => artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-card"><b>Actor: ${text(actor.name)}</b><p>${text(actor.description)}</p></div>`));
  (details.use_cases || []).forEach((useCase) => artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-card"><b>${text(useCase.id)}: ${text(useCase.name)}</b><p>${text(useCase.description)}</p><small>Actors: ${text((useCase.actors || []).join(", ") || "-")}</small></div>`));
  if (details.scenario) artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-note"><strong>Scenario</strong><p>${text(details.scenario)}</p></div>`);
  (details.steps || []).forEach((step) => artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-card task-card"><span>${text(step.id)}</span><div><b>${text(step.name)}</b><small>${text(step.type)} &rarr; ${text((step.next || []).join(", ") || "end")}</small></div></div>`));
  if (details.dot_code) artifactContent.insertAdjacentHTML("beforeend", `<details class="code-details"><summary>${text(heading)} DOT source</summary><pre>${text(details.dot_code)}</pre></details>`);
}

function renderArtifact(key) {
  const artifact = project.artifacts[key];
  activeKey = key;
  document.querySelectorAll("#artifactTabs button").forEach((button) => button.classList.toggle("active", button.dataset.key === key));
  artifactContent.innerHTML = `<div class="artifact-head"><h3>${text(artifact.title)}</h3><button id="editArtifactBtn" class="secondary-action" type="button">Edit</button></div><p class="artifact-summary">${text(artifact.summary)}</p>`;
  document.getElementById("editArtifactBtn").addEventListener("click", () => renderEditor(key));
  const content = artifact.content || {};

  if (key === "stories") {
    (content.stories || []).forEach((story) => {
      artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-card"><b>${text(story.id || "Story")}: ${text(story.title)}</b><p>${text(story.as_a || story.description)}</p><p><strong>Acceptance:</strong> ${text((story.acceptance_criteria || []).join(" | "))}</p></div>`);
    });
    if (content.assumptions?.length) artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-note"><strong>Assumptions</strong><p>${text(content.assumptions.join(" | "))}</p></div>`);
  } else if (key === "diagrams") {
    renderUmlDiagram("Use case diagram", project.diagram_svgs?.use_case, project.diagram_errors?.use_case, content.use_case);
    renderUmlDiagram("Activity diagram", project.diagram_svgs?.activity, project.diagram_errors?.activity, content.activity);
  } else if (key === "architecture") {
    if (project.architecture_svg) artifactContent.insertAdjacentHTML("beforeend", `<div class="architecture-preview">${project.architecture_svg}</div>`);
    (content.components || []).forEach((component) => artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-card"><b>${text(component.name)}</b><p>${text(component.responsibility || component.description)}</p><small>${text(component.technology || "")}</small></div>`));
    if (content.dot_code) artifactContent.insertAdjacentHTML("beforeend", `<details class="code-details"><summary>Graphviz architecture source</summary><pre>${text(content.dot_code)}</pre></details>`);
  } else if (key === "tasks") {
    (content.tasks || []).forEach((task) => artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-card task-card"><span>${text(task.id)}</span><div><b>${text(task.title)}</b><p>${text(task.description)}</p><small>Depends on: ${text((task.depends_on || []).join(", ") || "None")}</small></div></div>`));
  } else {
    (content.files || []).forEach((file) => artifactContent.insertAdjacentHTML("beforeend", `<details class="code-details" open><summary>${text(file.path)} <small>${text(file.language)}</small></summary><pre>${text(file.code)}</pre></details>`));
  }
}

// Artifact có danh sách file thì sửa từng file; còn lại sửa content dạng JSON.
function renderEditor(key) {
  const artifact = project.artifacts[key];
  const content = artifact.content || {};
  const files = Array.isArray(content.files) ? content.files : null;
  const body = files
    ? files.map((file, index) => `<div class="editor-file" data-index="${index}"><input class="editor-input" data-field="path" value="${text(file.path)}" /><textarea class="editor-code" data-field="code" spellcheck="false">${text(file.code)}</textarea></div>`).join("")
    : `<label>Content (JSON)</label><textarea id="editContent" class="editor-code editor-json" spellcheck="false">${text(JSON.stringify(content, null, 2))}</textarea>`;

  artifactContent.innerHTML = `
    <form id="artifactEditor" class="artifact-editor">
      <label>Title</label><input id="editTitle" class="editor-input" value="${text(artifact.title)}" required />
      <label>Summary</label><textarea id="editSummary" class="editor-summary">${text(artifact.summary)}</textarea>
      ${body}
      <div class="editor-actions"><button class="primary-action" type="submit"><span>Save changes</span><strong>✓</strong></button><button id="cancelEditBtn" class="secondary-action" type="button">Cancel</button></div>
      <div id="editError" class="spec-error" role="alert"></div>
    </form>`;

  document.getElementById("cancelEditBtn").addEventListener("click", () => renderArtifact(key));
  document.getElementById("artifactEditor").addEventListener("submit", async (event) => {
    event.preventDefault();
    const editError = document.getElementById("editError");
    let newContent;
    if (files) {
      newContent = { ...content, files: [...artifactContent.querySelectorAll(".editor-file")].map((row) => ({
        ...files[row.dataset.index],
        path: row.querySelector('[data-field="path"]').value.trim(),
        code: row.querySelector('[data-field="code"]').value,
      })) };
    } else {
      try {
        newContent = JSON.parse(document.getElementById("editContent").value);
      } catch (error) {
        editError.textContent = `Invalid JSON: ${error.message}`;
        return;
      }
    }
    try {
      const data = await api(`/api/spec/${encodeURIComponent(project.id)}/artifacts/${key}`, jsonOptions("PUT", {
        title: document.getElementById("editTitle").value,
        summary: document.getElementById("editSummary").value,
        content: newContent,
      }));
      project = data.project;
      renderResults(false);
      loadHistory();
    } catch (error) {
      editError.textContent = error.message;
    }
  });
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "";
}

// ========= CHAT =========

const workspace = document.querySelector(".spec-workspace");
const chatPanel = document.getElementById("chatPanel");
const chatThread = document.getElementById("chatThread");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatSendBtn = document.getElementById("chatSendBtn");
const STAGE_LABELS = Object.fromEntries(pipelineItems.map((item) => [item.dataset.stage, item.querySelector("b").textContent]));

function chatBubble(message) {
  const chips = (message.updated || [])
    .filter((key) => key in (project?.artifacts || {}))
    .map((key) => `<button type="button" data-key="${text(key)}">${text(STAGE_LABELS[key] || key)}</button>`)
    .join("");
  const updated = chips ? `<div class="chat-updated"><span>Updated</span>${chips}</div>` : "";
  return `<div class="chat-msg ${message.role === "user" ? "user" : "assistant"}${message.error ? " error" : ""}"><div class="chat-body">${text(message.content)}</div>${updated}</div>`;
}

function renderChat() {
  const messages = project.messages?.length ? project.messages : [{ role: "user", content: project.requirement }];
  chatThread.innerHTML = messages.map(chatBubble).join("");
  chatThread.querySelectorAll(".chat-updated button").forEach((button) => button.addEventListener("click", () => {
    renderArtifact(button.dataset.key);
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

// Gợi ý trong ô chat bám theo các stage project đang có.
const CHAT_SUGGESTIONS = {
  stories: "Add a user story for password reset",
  diagrams: "Add an Admin actor to the use case diagram",
  architecture: "Switch the database to PostgreSQL",
  tasks: "Split the biggest task into smaller steps",
  code: "Add input validation to the signup form",
  tests: "Add tests for the login flow",
  docs: "Add a Docker Compose file",
};

function updateChatPlaceholder() {
  const keys = Object.keys(project?.artifacts || {}).filter((key) => key in CHAT_SUGGESTIONS);
  // Lấy stage đầu và cuối để hai ví dụ khác nhau.
  const picks = [...new Set([keys[0], keys[keys.length - 1]])].filter(Boolean);
  chatInput.placeholder = picks.length
    ? `Ask for a change, e.g. ${picks.map((key) => `“${CHAT_SUGGESTIONS[key]}”`).join(" or ")}`
    : "Ask for a change or a question about this project";
}

function autosizeChat() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 200)}px`;
}

chatInput.addEventListener("input", autosizeChat);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message || !project?.id || chatSendBtn.disabled) return;
  chatInput.value = "";
  autosizeChat();
  chatSendBtn.disabled = true;
  chatThread.insertAdjacentHTML("beforeend", chatBubble({ role: "user", content: message }));
  chatThread.insertAdjacentHTML("beforeend", `<div class="chat-msg assistant typing"><div class="chat-body"><span></span><span></span><span></span></div></div>`);
  chatThread.lastElementChild.scrollIntoView({ behavior: "smooth", block: "end" });
  try {
    const data = await api(`/api/spec/${encodeURIComponent(project.id)}/chat`, jsonOptions("POST", { message }));
    project = data.project;
    if (data.updated?.length) activeKey = data.updated[0];
    renderResults(false);
    loadHistory();
  } catch (error) {
    chatThread.querySelector(".typing")?.remove();
    chatThread.insertAdjacentHTML("beforeend", chatBubble({ role: "assistant", content: error.message, error: true }));
    chatInput.value = message;
    autosizeChat();
  } finally {
    chatSendBtn.disabled = false;
    chatThread.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
    chatInput.focus();
  }
});

function renderResults(scroll = true) {
  results.classList.remove("hidden");
  workspace.classList.add("hidden");
  chatPanel.classList.remove("hidden");
  chatForm.classList.remove("hidden");
  renderChat();
  updateChatPlaceholder();
  document.getElementById("resultTitle").textContent = project.title || project.artifacts.stories?.title || "Generated software plan";
  document.getElementById("savedAt").textContent = project.updated_at ? `· ${formatDate(project.updated_at)}` : "";
  artifactTabs.innerHTML = Object.entries(project.artifacts).map(([key, artifact]) => `<button type="button" data-key="${key}">${text(artifact.title)}</button>`).join("");
  artifactTabs.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => renderArtifact(button.dataset.key)));
  pipelineItems.forEach((item) => item.classList.toggle("done", item.dataset.stage in project.artifacts));
  if (!(activeKey in project.artifacts)) activeKey = Object.keys(project.artifacts)[0];
  const hasTests = "code" in project.artifacts || "tests" in project.artifacts;
  document.getElementById("runTestsBtn").classList.toggle("hidden", !hasTests);
  renderArtifact(activeKey);
  if (scroll) results.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ========= HISTORY =========

const historyList = document.getElementById("historyList");

async function loadHistory() {
  try {
    const { projects } = await api("/api/spec/projects");
    if (!projects.length) {
      historyList.innerHTML = `<li class="history-empty">No saved documents yet.</li>`;
      return;
    }
    historyList.innerHTML = projects.map((item) => `<li><button type="button" data-id="${text(item.id)}" class="${item.id === project?.id ? "active" : ""}"><b>${text(item.title)}</b><small>${text(formatDate(item.updated_at))}</small></button></li>`).join("");
    historyList.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => openProject(button.dataset.id)));
  } catch (error) {
    historyList.innerHTML = `<li class="history-empty">${text(error.message)}</li>`;
  }
}

async function openProject(id, push = true) {
  errorBox.textContent = "";
  try {
    const data = await api(`/api/spec/${encodeURIComponent(id)}`);
    project = data.project;
    requirement.value = project.requirement || "";
    requirement.dispatchEvent(new Event("input"));
    const stages = project.stages || Object.keys(project.artifacts);
    pipelineItems.forEach((item) => { item.querySelector("input").checked = stages.includes(item.dataset.stage); });
    syncStageState();
    if (push) history.pushState({ id }, "", `/spec/${encodeURIComponent(id)}`);
    renderResults();
    loadHistory();
  } catch (error) {
    errorBox.textContent = error.message;
  }
}

function startNewProject(push = true) {
  project = null;
  results.classList.add("hidden");
  chatPanel.classList.add("hidden");
  chatForm.classList.add("hidden");
  workspace.classList.remove("hidden");
  requirement.value = "";
  requirement.dispatchEvent(new Event("input"));
  pipelineItems.forEach((item) => { item.querySelector("input").checked = true; });
  syncStageState();
  if (push) history.pushState({}, "", "/");
  loadHistory();
  requirement.focus();
}

document.getElementById("newProjectBtn").addEventListener("click", () => startNewProject());

window.addEventListener("popstate", () => {
  const match = window.location.pathname.match(/^\/spec\/(.+)$/);
  if (match) openProject(decodeURIComponent(match[1]), false);
  else startNewProject(false);
});

document.getElementById("renameBtn").addEventListener("click", async () => {
  if (!project?.id) return;
  const title = window.prompt("Project name", project.title || "");
  if (!title || !title.trim()) return;
  try {
    project = (await api(`/api/spec/${encodeURIComponent(project.id)}`, jsonOptions("PATCH", { title }))).project;
    renderResults(false);
    loadHistory();
  } catch (error) {
    alert(error.message);
  }
});

document.getElementById("deleteBtn").addEventListener("click", async () => {
  if (!project?.id || !window.confirm(`Delete "${project.title}"? This cannot be undone.`)) return;
  try {
    await api(`/api/spec/${encodeURIComponent(project.id)}`, { method: "DELETE" });
    startNewProject();
  } catch (error) {
    alert(error.message);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.textContent = "";
  const stages = selectedStages();
  if (!stages.length) {
    errorBox.textContent = "Select at least one pipeline stage.";
    return;
  }
  setLoading(true);
  try {
    const data = await api("/api/spec/generate", jsonOptions("POST", { requirement: requirement.value.trim(), stages }));
    project = data.project;
    history.pushState({ id: project.id }, "", `/spec/${encodeURIComponent(project.id)}`);
    renderResults();
    loadHistory();
  } catch (error) {
    errorBox.textContent = error.message;
  } finally {
    setLoading(false);
  }
});

document.getElementById("newSpecBtn").addEventListener("click", () => startNewProject());

// Mở /spec/<id> trực tiếp thì nạp luôn project đó.
if (document.body.dataset.projectId) openProject(document.body.dataset.projectId, false);
else loadHistory();

document.getElementById("exportBtn").addEventListener("click", () => {
  if (project?.id) window.location.href = `/api/spec/${encodeURIComponent(project.id)}/export`;
});

document.getElementById("runTestsBtn").addEventListener("click", async () => {
  if (!project?.id) return;
  const button = document.getElementById("runTestsBtn");
  button.disabled = true;
  button.textContent = "Running...";
  try {
    const data = await api(`/api/spec/${encodeURIComponent(project.id)}/run-tests`, { method: "POST" });
    alert(`${data.status.toUpperCase()}\n${data.output || data.message || ""}`);
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Run tests";
  }
});
