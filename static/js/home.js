// ===================== LocalStorage helpers =====================

const RECENT_KEY = "code_wiki_recent_repos";

function getRecentRepos() {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveRecentRepos(list) {
  localStorage.setItem(RECENT_KEY, JSON.stringify(list));
}

function saveRecentRepo(repo) {
  const list = getRecentRepos();
  const filtered = list.filter((r) => r.id !== repo.id);
  filtered.unshift(repo);
  saveRecentRepos(filtered.slice(0, 9));
}

// Xóa 1 repo theo id khỏi localStorage + gọi backend xóa
function deleteRepoById(id) {
  const list = getRecentRepos();
  const filtered = list.filter((r) => r.id !== id);
  saveRecentRepos(filtered);

  fetch("/api/repo/" + encodeURIComponent(id), {
    method: "DELETE",
  }).catch((err) => console.error("Error deleting repo on server:", err));

  renderRepoGrid();
}

// ===================== UI: repo grid =====================

function getSourceLabel(repo) {
  if (repo.source === "git") return "Git";
  return "Local"; // mặc định
}

function renderRepoGrid() {
  const grid = document.getElementById("repoGrid");
  const addCard = document.getElementById("addRepoCard");
  const repos = getRecentRepos();

  if (!grid || !addCard) return;

  grid.innerHTML = "";
  grid.appendChild(addCard);

  repos.forEach((repo) => {
    const card = document.createElement("div");
    card.className = "repo-card relative cursor-pointer";

    card.innerHTML = `
  <div>
    <div class="card-icon">📁</div>
    <h2 class="card-title">${repo.name}</h2>
    <p class="card-desc">${repo.path}</p>
    <p class="text-[11px] text-slate-500 mt-2">
      Processed: ${repo.summary?.processed ?? 0},
      Failed: ${repo.summary?.failed ?? 0}
    </p>
  </div>
  <div class="card-footer">
    <span class="badge">${getSourceLabel(repo)}</span>
    <div class="card-arrow">➜</div>
  </div>
`;

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.innerHTML = "✕";
    deleteBtn.title = "Xóa repo này khỏi danh sách";
    deleteBtn.className =
      "absolute top-2 right-2 text-xs text-slate-400 hover:text-red-400 bg-slate-900/80 rounded-full px-1";

    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (confirm(`Bạn có chắc muốn xóa repo "${repo.name}" khỏi danh sách?`)) {
        deleteRepoById(repo.id);
      }
    });

    card.appendChild(deleteBtn);

    card.addEventListener("click", () => {
      window.location.href = "/repo/" + encodeURIComponent(repo.id);
    });

    grid.appendChild(card);
  });
}

// ===================== Loading state (overlay) =====================

function setAddRepoLoading(isLoading) {
  const addCard = document.getElementById("addRepoCard");
  const modal = document.getElementById("addRepoModal");
  const body = document.body;

  if (isLoading) {
    if (addCard) {
      addCard.classList.add("opacity-60", "pointer-events-none");
    }
    if (modal) {
      const localBtn = document.getElementById("modalLocalBtn");
      const gitBtn = document.getElementById("modalGitBtn");
      const gitInput = document.getElementById("modalGitUrl");
      [localBtn, gitBtn, gitInput].forEach((el) => {
        if (el) el.disabled = true;
      });
    }

    let overlay = document.getElementById("globalLoadingOverlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "globalLoadingOverlay";
      overlay.className =
        "fixed inset-0 bg-black/40 flex items-center justify-center z-40";
      overlay.innerHTML = `
        <div class="flex items-center gap-3 px-4 py-2 rounded-lg bg-slate-900 border border-slate-700 text-sm text-slate-100 shadow-lg">
          <svg class="animate-spin h-4 w-4 text-sky-400" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10"
                    stroke="currentColor" stroke-width="4" fill="none"></circle>
            <path class="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8v4l3.5-3.5L12 0v4a8 8 0 00-8 8h4z"></path>
          </svg>
          <span>Analyzing repository...</span>
        </div>
      `;
      body.appendChild(overlay);
    }
  } else {
    if (addCard) {
      addCard.classList.remove("opacity-60", "pointer-events-none");
    }
    if (modal) {
      const localBtn = document.getElementById("modalLocalBtn");
      const gitBtn = document.getElementById("modalGitBtn");
      const gitInput = document.getElementById("modalGitUrl");
      [localBtn, gitBtn, gitInput].forEach((el) => {
        if (el) el.disabled = false;
      });
    }
    const overlay = document.getElementById("globalLoadingOverlay");
    if (overlay) overlay.remove();
  }
}

// ===================== Modal Add repo =====================

function openAddRepoModal() {
  const modal = document.getElementById("addRepoModal");
  if (!modal) return;
  modal.classList.remove("hidden");
}

function closeAddRepoModal() {
  const modal = document.getElementById("addRepoModal");
  if (!modal) return;
  modal.classList.add("hidden");
}

// ===================== Add từ LOCAL FOLDER =====================

async function handleAddLocalFolder() {
  const folderInput = document.getElementById("hiddenFolderInput");
  if (!folderInput) return;

  closeAddRepoModal();
  folderInput.click();

  folderInput.onchange = async () => {
    if (!folderInput.files || folderInput.files.length === 0) return;

    setAddRepoLoading(true);

    const first = folderInput.files[0];
    const fullPath = first.webkitRelativePath || first.name;
    const parts = fullPath.split("/");
    const rootFolderName = parts.length > 1 ? parts[0] : fullPath;

    const repoName = rootFolderName;
    const repoPath = rootFolderName;

    const files = {};
    for (const file of folderInput.files) {
      const text = await file.text();
      const relPath = file.webkitRelativePath || file.name;
      files[relPath] = text;
    }

    try {
      const res = await fetch("/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          files,
          repo_name: repoName,
          repo_path: repoPath,
        }),
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        alert(data.error || "Error while analyzing repo");
        return;
      }

      const repo = {
        id: data.repo_id,
        name: data.repo_name || repoName,
        path: data.repo_path || repoPath,
        summary: data.summary,
        source: data.source || "local",
      };
      saveRecentRepo(repo);

      window.location.href = "/repo/" + encodeURIComponent(data.repo_id);
    } catch (err) {
      console.error(err);
      alert("Network error while analyzing repo");
    } finally {
      folderInput.value = "";
      setAddRepoLoading(false);
    }
  };
}

// ===================== Add từ GIT URL (trong modal) =====================

async function handleAddGitFromModal() {
  const input = document.getElementById("modalGitUrl");
  if (!input) return;

  const gitUrl = input.value.trim();
  if (!gitUrl) {
    alert("Vui lòng nhập Git URL (ví dụ: https://github.com/user/repo.git)");
    return;
  }

  closeAddRepoModal();
  setAddRepoLoading(true);

  try {
    const res = await fetch("/add_git_repo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ git_url: gitUrl }),
    });

    const data = await res.json();

    if (!res.ok || data.error) {
      alert(data.error || "Error while analyzing git repo");
      return;
    }

    const repo = {
      id: data.repo_id,
      name: data.repo_name || gitUrl.split("/").pop(),
      path: data.repo_path || gitUrl,
      summary: data.summary,
      source: data.source || "git",
    };
    saveRecentRepo(repo);

    window.location.href = "/repo/" + encodeURIComponent(data.repo_id);
  } catch (err) {
    console.error(err);
    alert("Network error while analyzing git repo");
  } finally {
    setAddRepoLoading(false);
  }
}

// ===================== Search & Share =====================

function setupSearch() {
  const input = document.getElementById("searchInput");
  if (!input) return;

  input.addEventListener("input", () => {
    const q = input.value.toLowerCase();
    const repos = getRecentRepos();
    const filtered = repos.filter(
      (r) =>
        r.name.toLowerCase().includes(q) || r.path.toLowerCase().includes(q)
    );

    const grid = document.getElementById("repoGrid");
    const addCard = document.getElementById("addRepoCard");

    if (!grid || !addCard) return;

    grid.innerHTML = "";
    grid.appendChild(addCard);

    filtered.forEach((repo) => {
      const card = document.createElement("div");
      card.className = "repo-card relative cursor-pointer";

      card.innerHTML = `
        <div>
          <div class="card-icon">📁</div>
          <h2 class="card-title">${repo.name}</h2>
          <p class="card-desc">${repo.path}</p>
          <p class="text-[11px] text-slate-500 mt-2">
            Processed: ${repo.summary?.processed ?? 0},
            Failed: ${repo.summary?.failed ?? 0}
          </p>
        </div>
        <div class="card-footer">
          <span class="badge">${getSourceLabel(repo)}</span>
          <div class="card-arrow">➜</div>
        </div>
      `;

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.innerHTML = "✕";
      deleteBtn.title = "Xóa repo này khỏi danh sách";
      deleteBtn.className =
        "absolute top-2 right-2 text-xs text-slate-400 hover:text-red-400 bg-slate-900/80 rounded-full px-1";

      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (
          confirm(`Bạn có chắc muốn xóa repo "${repo.name}" khỏi danh sách?`)
        ) {
          deleteRepoById(repo.id);
          input.dispatchEvent(new Event("input"));
        }
      });

      card.appendChild(deleteBtn);

      card.addEventListener("click", () => {
        window.location.href = "/repo/" + encodeURIComponent(repo.id);
      });

      grid.appendChild(card);
    });
  });
}

function setupShareButton() {
  const btn = document.getElementById("shareBtn");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    const shareUrl = window.location.origin;
    const shareTitle = "DeepWiki – Explore your code as a wiki";
    const shareText =
      "Check out DeepWiki – a tool to explore your codebase like a wiki with AI.";

    if (navigator.share) {
      try {
        await navigator.share({
          title: shareTitle,
          text: shareText,
          url: shareUrl,
        });
        return;
      } catch (err) {
        console.error("Share cancelled or failed:", err);
      }
    }

    fallbackCopyLink(shareUrl);
  });
}

function fallbackCopyLink(url) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard
      .writeText(url)
      .then(() => {
        alert("Đã copy link DeepWiki vào clipboard:\n" + url);
      })
      .catch((err) => {
        console.error("Clipboard error:", err);
        prompt("Copy link DeepWiki:", url);
      });
  } else {
    prompt("Copy link DeepWiki:", url);
  }
}

// ===================== INIT =====================

window.addEventListener("DOMContentLoaded", () => {
  renderRepoGrid();
  setupSearch();
  setupShareButton();

  const addCard = document.getElementById("addRepoCard");
  if (addCard) {
    addCard.addEventListener("click", openAddRepoModal);
  }

  const localBtn = document.getElementById("modalLocalBtn");
  if (localBtn) {
    localBtn.addEventListener("click", handleAddLocalFolder);
  }

  const gitBtn = document.getElementById("modalGitBtn");
  if (gitBtn) {
    gitBtn.addEventListener("click", handleAddGitFromModal);
  }

  const closeBtn = document.getElementById("modalCloseBtn");
  if (closeBtn) {
    closeBtn.addEventListener("click", closeAddRepoModal);
  }

  const modal = document.getElementById("addRepoModal");
  if (modal) {
    // Click ra ngoài panel thì đóng modal
    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        closeAddRepoModal();
      }
    });
  }
});
