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
  charCount.textContent = `${requirement.value.length} / 12000`;
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    requirement.value = button.dataset.prompt;
    requirement.dispatchEvent(new Event("input"));
    requirement.focus();
  });
});

function setLoading(loading) {
  generateBtn.disabled = loading;
  generateBtn.querySelector("span").textContent = loading ? "Agent is building..." : "Generate software plan";
  pipelineItems.forEach((item) => item.classList.toggle("working", loading));
}

function text(value) {
  return value == null ? "" : String(value);
}

function renderArtifact(key) {
  const artifact = project.artifacts[key];
  activeKey = key;
  document.querySelectorAll("#artifactTabs button").forEach((button) => button.classList.toggle("active", button.dataset.key === key));
  artifactContent.innerHTML = `<h3>${text(artifact.title)}</h3><p class="artifact-summary">${text(artifact.summary)}</p>`;
  const content = artifact.content || {};

  if (key === "stories") {
    (content.stories || []).forEach((story) => {
      artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-card"><b>${text(story.id || "Story")}: ${text(story.title)}</b><p>${text(story.as_a || story.description)}</p><p><strong>Acceptance:</strong> ${text((story.acceptance_criteria || []).join(" | "))}</p></div>`);
    });
    if (content.assumptions?.length) artifactContent.insertAdjacentHTML("beforeend", `<div class="artifact-note"><strong>Assumptions</strong><p>${text(content.assumptions.join(" | "))}</p></div>`);
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

function renderResults() {
  results.classList.remove("hidden");
  document.getElementById("resultTitle").textContent = project.artifacts.stories?.title || "Generated software plan";
  artifactTabs.innerHTML = Object.entries(project.artifacts).map(([key, artifact]) => `<button type="button" data-key="${key}">${text(artifact.title)}</button>`).join("");
  artifactTabs.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => renderArtifact(button.dataset.key)));
  pipelineItems.forEach((item) => item.classList.add("done"));
  renderArtifact(activeKey);
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.textContent = "";
  setLoading(true);
  try {
    const response = await fetch("/api/spec/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ requirement: requirement.value.trim() }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Generation failed");
    project = data.project;
    renderResults();
  } catch (error) {
    errorBox.textContent = error.message;
  } finally {
    setLoading(false);
  }
});

document.getElementById("newSpecBtn").addEventListener("click", () => {
  results.classList.add("hidden");
  requirement.focus();
});

document.getElementById("exportBtn").addEventListener("click", () => {
  if (project?.id) window.location.href = `/api/spec/${encodeURIComponent(project.id)}/export`;
});

document.getElementById("runTestsBtn").addEventListener("click", async () => {
  if (!project?.id) return;
  const button = document.getElementById("runTestsBtn");
  button.disabled = true;
  button.textContent = "Running...";
  try {
    const response = await fetch(`/api/spec/${encodeURIComponent(project.id)}/run-tests`, { method: "POST" });
    const data = await response.json();
    alert(`${data.status.toUpperCase()}\n${data.output || data.message || ""}`);
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Run tests";
  }
});
