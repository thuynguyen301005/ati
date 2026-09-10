let STRUCTURE = null;

// Load cấu trúc từ backend khi vào /repo
async function loadStructure() {
  const repoId = window.REPO_ID;
  const res = await fetch(
    "/api/repo/" + encodeURIComponent(repoId) + "/structure"
  );
  const data = await res.json();

  const errorBox = document.getElementById("errorBox");
  if (data.error) {
    if (errorBox) {
      errorBox.textContent = data.error;
      errorBox.classList.remove("hidden");
    } else {
      alert(data.error);
    }
    return;
  }

  STRUCTURE = data;
  renderFileTree(data.files || []);
}

// Render cây file ở sidebar
function renderFileTree(files) {
  const treeEl = document.getElementById("fileTree");
  treeEl.innerHTML = "";

  if (!files || files.length === 0) {
    treeEl.innerHTML =
      '<div class="text-slate-500 text-xs">Không có file nào được phân tích.</div>';
    return;
  }

  const byDir = {};
  files.forEach((f) => {
    const parts = f.path.split("/");
    const dir = parts.slice(0, -1).join("/") || ".";
    if (!byDir[dir]) byDir[dir] = [];
    byDir[dir].push(f);
  });

  Object.keys(byDir)
    .sort()
    .forEach((dir) => {
      const group = document.createElement("div");
      group.className = "mb-2";

      const dirTitle = document.createElement("div");
      dirTitle.className = "uppercase text-[10px] text-slate-500 px-2";
      dirTitle.textContent = dir === "." ? "root" : dir;
      group.appendChild(dirTitle);

      byDir[dir]
        .sort((a, b) => a.path.localeCompare(b.path))
        .forEach((f) => {
          const item = document.createElement("div");
          item.className =
            "px-3 py-1 rounded cursor-pointer hover:bg-slate-800 flex items-center justify-between";
          item.textContent = f.path.split("/").pop();

          if (f.has_error) {
            const badge = document.createElement("span");
            badge.className =
              "ml-2 text-[10px] text-red-300 bg-red-900/50 border border-red-700 px-1 rounded";
            badge.textContent = "ERROR";
            item.appendChild(badge);
          }

          item.onclick = () => openFile(f.path);
          group.appendChild(item);
        });

      treeEl.appendChild(group);
    });
}

// 🚀 Load AI Review cho toàn repo
async function loadRepoReview() {
  const repoId = window.REPO_ID;
  const contentEl = document.getElementById("content");
  const breadcrumb = document.getElementById("breadcrumb");

  try {
    const res = await fetch(
      "/api/repo/" + encodeURIComponent(repoId) + "/review"
    );
    const data = await res.json();

    breadcrumb.textContent = "Repo overview & AI review";
    contentEl.innerHTML = "";

    const title = document.createElement("h2");
    title.className = "text-2xl font-bold mb-2";
    title.textContent = "AI Review for this repository";
    contentEl.appendChild(title);

    const summary = document.createElement("p");
    summary.className = "text-sm text-slate-300 mb-4";
    summary.textContent = data.summary || "No review summary available.";
    contentEl.appendChild(summary);

    if (data.error) {
      const err = document.createElement("p");
      err.className = "text-xs text-red-300 mb-4";
      err.textContent = "Review error: " + data.error;
      contentEl.appendChild(err);
      return;
    }

    if (!Array.isArray(data.issues) || data.issues.length === 0) {
      const ok = document.createElement("div");
      ok.className =
        "mt-2 p-3 rounded border border-emerald-500/60 bg-emerald-900/40 text-sm text-emerald-200";
      ok.textContent = "✅ Không phát hiện vấn đề đáng kể trong code.";
      contentEl.appendChild(ok);
      return;
    }

    const issuesTitle = document.createElement("h3");
    issuesTitle.className = "text-lg font-semibold mt-4 mb-2";
    issuesTitle.textContent = "Detected issues & suggestions";
    contentEl.appendChild(issuesTitle);

    data.issues.forEach((issue) => {
      const box = document.createElement("div");
      box.className =
        "mb-3 p-3 rounded border border-slate-700 bg-slate-900/60";

      const header = document.createElement("div");
      header.className = "flex items-center justify-between mb-1";

      const left = document.createElement("div");
      left.className = "text-sm font-semibold";
      left.textContent = issue.title || "Issue";

      const right = document.createElement("div");
      right.className = "text-[11px] text-slate-400";

      const sev = issue.severity || "warning";
      const line = issue.line != null ? issue.line : -1;
      right.textContent =
        (issue.file ? issue.file + " " : "") +
        (line > 0 ? `(line ${line})` : "");

      header.appendChild(left);
      header.appendChild(right);
      box.appendChild(header);

      if (issue.suggestion) {
        const sugg = document.createElement("p");
        sugg.className = "text-xs text-slate-300 mt-1";
        sugg.textContent = issue.suggestion;
        box.appendChild(sugg);
      }

      const badge = document.createElement("span");
      badge.className =
        "inline-block mt-2 text-[10px] px-2 py-0.5 rounded-full";
      if (sev === "error") {
        badge.classList.add("bg-red-600/80", "text-red-50");
        badge.textContent = "ERROR";
      } else if (sev === "style") {
        badge.classList.add("bg-sky-600/80", "text-sky-50");
        badge.textContent = "STYLE";
      } else {
        badge.classList.add("bg-amber-500/80", "text-amber-50");
        badge.textContent = "WARNING";
      }
      box.appendChild(badge);

      contentEl.appendChild(box);
    });
  } catch (err) {
    console.error("Error loading repo review:", err);
  }
}

// Mở “trang wiki” cho một file
async function openFile(path) {
  const repoId = window.REPO_ID;
  const res = await fetch(
    "/api/repo/" +
      encodeURIComponent(repoId) +
      "/file/" +
      encodeURIComponent(path)
  );
  const file = await res.json();

  const contentEl = document.getElementById("content");
  const breadcrumb = document.getElementById("breadcrumb");

  breadcrumb.textContent = path;
  contentEl.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "text-2xl font-bold mb-2";
  title.textContent = path;
  contentEl.appendChild(title);

  if (file.error) {
    const p = document.createElement("p");
    p.className = "text-red-300 text-sm";
    p.textContent = "Lỗi khi phân tích file: " + file.error;
    contentEl.appendChild(p);
    return;
  }

  // Description / overview
  if (file.description) {
    const desc = document.createElement("p");
    desc.className = "text-sm text-slate-300 mb-4";
    desc.textContent = file.description;
    contentEl.appendChild(desc);
  }

  // Imports
  if (Array.isArray(file.imports) && file.imports.length > 0) {
    const importsTitle = document.createElement("h3");
    importsTitle.className = "text-lg font-semibold mt-4 mb-1";
    importsTitle.textContent = "Imports / Dependencies";
    contentEl.appendChild(importsTitle);

    const list = document.createElement("ul");
    list.className = "list-disc list-inside text-sm text-slate-300";
    file.imports.forEach((imp) => {
      const li = document.createElement("li");
      li.textContent = imp;
      list.appendChild(li);
    });
    contentEl.appendChild(list);
  }

  // Classes
  if (Array.isArray(file.classes) && file.classes.length > 0) {
    const classesTitle = document.createElement("h3");
    classesTitle.className = "text-lg font-semibold mt-6 mb-2";
    classesTitle.textContent = "Classes";
    contentEl.appendChild(classesTitle);

    file.classes.forEach((cls) => {
      const box = document.createElement("div");
      box.className =
        "mb-3 p-3 rounded border border-slate-700 bg-slate-900/60";

      const header = document.createElement("div");
      header.className = "flex items-center justify-between mb-1";

      const name = document.createElement("div");
      name.className = "font-semibold text-sm";
      const base =
        Array.isArray(cls.base_classes) && cls.base_classes.length > 0
          ? " : " + cls.base_classes.join(", ")
          : "";
      name.textContent = cls.name + base;
      header.appendChild(name);

      box.appendChild(header);

      if (Array.isArray(cls.methods) && cls.methods.length > 0) {
        const methodsTitle = document.createElement("div");
        methodsTitle.className = "text-xs text-slate-400 mb-1";
        methodsTitle.textContent = "Methods:";
        box.appendChild(methodsTitle);

        const ul = document.createElement("ul");
        ul.className = "list-disc list-inside text-xs text-slate-300";
        cls.methods.forEach((m) => {
          const li = document.createElement("li");
          li.textContent = m;
          ul.appendChild(li);
        });
        box.appendChild(ul);
      }

      contentEl.appendChild(box);
    });
  }

  // Functions
  if (Array.isArray(file.functions) && file.functions.length > 0) {
    const funcsTitle = document.createElement("h3");
    funcsTitle.className = "text-lg font-semibold mt-6 mb-2";
    funcsTitle.textContent = "Functions";
    contentEl.appendChild(funcsTitle);

    file.functions.forEach((fn) => {
      const box = document.createElement("div");
      box.className =
        "mb-3 p-3 rounded border border-slate-700 bg-slate-900/60";

      const sig = document.createElement("div");
      sig.className = "font-semibold text-sm";
      sig.textContent = fn.name + (fn.params || "");
      box.appendChild(sig);

      if (fn.description) {
        const desc = document.createElement("p");
        desc.className = "text-xs text-slate-400 mt-1";
        desc.textContent = fn.description;
        box.appendChild(desc);
      }

      contentEl.appendChild(box);
    });
  }

  // DOT code (technical section)
  const dotTitle = document.createElement("h3");
  dotTitle.className = "text-lg font-semibold mt-6 mb-2";
  dotTitle.textContent = "Graphviz DOT";
  contentEl.appendChild(dotTitle);

  const dotBox = document.createElement("pre");
  dotBox.className =
    "bg-slate-900 border border-slate-700 rounded p-4 text-xs overflow-x-auto";
  dotBox.textContent = file.dot_code || "(không có dot_code)";
  contentEl.appendChild(dotBox);
}

// Nút xem graph tổng (SVG)
function setupGraphView() {
  const btn = document.getElementById("graphViewBtn");
  const contentEl = document.getElementById("content");
  const breadcrumb = document.getElementById("breadcrumb");

  if (!btn) {
    console.warn("graphViewBtn not found in DOM");
    return;
  }

  btn.addEventListener("click", async () => {
    const repoId = window.REPO_ID;
    const res = await fetch(
      "/api/repo/" + encodeURIComponent(repoId) + "/graph"
    );
    const data = await res.json();
    if (data.error) {
      alert(
        data.error + (data.graphviz_error ? ": " + data.graphviz_error : "")
      );
      return;
    }

    breadcrumb.textContent = "Graph tổng quan";
    contentEl.innerHTML = "";

    const title = document.createElement("h2");
    title.className = "text-2xl font-bold mb-2";
    title.textContent = "Graph tổng quan (SVG từ Graphviz)";
    contentEl.appendChild(title);

    const wrapper = document.createElement("div");
    wrapper.className =
      "bg-slate-900 border border-slate-700 rounded p-4 overflow-auto max-h-[80vh]";
    wrapper.innerHTML = data.diagram; // SVG từ backend
    contentEl.appendChild(wrapper);
  });
}

window.addEventListener("DOMContentLoaded", () => {
  loadStructure();
  loadRepoReview(); // AI review khi mới vào repo
  setupGraphView();
});
