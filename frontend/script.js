function generateSessionId() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return "session-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

const state = {
  role: "seller",
  queryCount: 0,
  sessionId: generateSessionId()
};

const app = document.getElementById("app");
const collapseBtn = document.getElementById("collapseBtn");
const expandBtn = document.getElementById("expandBtn");
const roleToggle = document.getElementById("roleToggle");
const composer = document.getElementById("composer");
const queryInput = document.getElementById("queryInput");
const askButton = document.getElementById("askButton");
const chat = document.getElementById("chat");
const chatEmpty = document.getElementById("chatEmpty");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const sellerTagSelect = document.getElementById("sellerTagSelect");
const uploadStatus = document.getElementById("uploadStatus");
const newChatBtn = document.getElementById("newChatBtn");
const newSellerInput = document.getElementById("newSellerInput");
const addSellerBtn = document.getElementById("addSellerBtn");
const addSellerStatus = document.getElementById("addSellerStatus");

let thread = null;

const META_LABELS = {
  single_seller: "Seller lookup",
  simulation: "What-if simulation",
  comparison: "Seller comparison",
  status_breakdown: "Order status breakdown",
  status_comparison: "Status comparison",
  aggregate: "Ranking",
  policy: "Policy",
  blocked: "Access blocked",
  chat: "",
  error: "Connection error"
};

// ---------- Sidebar collapse ----------

collapseBtn.addEventListener("click", () => app.classList.add("collapsed"));
expandBtn.addEventListener("click", () => app.classList.remove("collapsed"));

// ---------- Role toggle ----------

roleToggle.addEventListener("click", (e) => {
  const btn = e.target.closest(".role-pill-option");
  if (!btn) return;
  document.querySelectorAll(".role-pill-option").forEach(el => el.classList.remove("active"));
  btn.classList.add("active");
  state.role = btn.dataset.role;
});

// ---------- New conversation ----------

newChatBtn.addEventListener("click", async () => {
  try {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId })
    });
  } catch (err) {
    console.error("Could not reset session on server", err);
  }

  if (thread) {
    thread.remove();
    thread = null;
  }
  chatEmpty.style.display = "block";
  state.queryCount = 0;
});

// ---------- Load sellers for the upload tag dropdown ----------

async function loadSellers() {
  try {
    const res = await fetch("/api/sellers");
    const sellers = await res.json();
    sellerTagSelect.innerHTML = '<option value="">Applies to: General policy</option>';
    sellers.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s["Seller ID"];
      opt.textContent = `Applies to: ${s["Seller Name"]}`;
      sellerTagSelect.appendChild(opt);
    });
  } catch (err) {
    console.error("Could not load sellers", err);
  }
}
loadSellers();

// ---------- Add a new seller ----------

addSellerBtn.addEventListener("click", async () => {
  const name = newSellerInput.value.trim();
  if (!name) return;

  addSellerStatus.textContent = "Adding…";
  try {
    const res = await fetch("/api/sellers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    const data = await res.json();
    addSellerStatus.textContent = data.created
      ? `Added "${data.seller_name}" (${data.seller_id})`
      : `"${data.seller_name}" already exists (${data.seller_id})`;
    newSellerInput.value = "";
    loadSellers();
  } catch (err) {
    addSellerStatus.textContent = "Could not add seller. Check the backend server.";
  }
});

newSellerInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    addSellerBtn.click();
  }
});

// ---------- Suggestions ----------

document.querySelectorAll(".suggestion").forEach(btn => {
  btn.addEventListener("click", () => {
    queryInput.value = btn.dataset.q;
    composer.dispatchEvent(new Event("submit"));
  });
});

// ---------- Ask flow ----------

composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;

  chatEmpty.style.display = "none";
  ensureThread();
  queryInput.value = "";
  askButton.disabled = true;

  renderUserMessage(query);
  const botMsg = renderBotMessage(true);

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, role: state.role, session_id: state.sessionId })
    });
    const data = await res.json();
    updateBotMessage(botMsg, data.answer, data.intent);
  } catch (err) {
    updateBotMessage(botMsg, "Could not reach the backend. Is the FastAPI server running?", "error");
  }

  state.queryCount += 1;
  askButton.disabled = false;
});

function ensureThread() {
  if (!thread) {
    thread = document.createElement("div");
    thread.className = "thread";
    chat.appendChild(thread);
  }
}

function renderUserMessage(text) {
  const row = document.createElement("div");
  row.className = "msg msg-user";
  row.innerHTML = `<div class="bubble"></div>`;
  row.querySelector(".bubble").textContent = text;
  thread.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
}

function renderBotMessage(loading) {
  const row = document.createElement("div");
  row.className = "msg msg-bot";
  row.innerHTML = `
    <div class="bot-text ${loading ? "loading" : ""}">${loading ? "Checking records and policy…" : ""}</div>
    <div class="msg-meta"></div>
  `;
  thread.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
  return row;
}

function updateBotMessage(row, text, intent) {
  const textEl = row.querySelector(".bot-text");
  const metaEl = row.querySelector(".msg-meta");
  textEl.classList.remove("loading");
  textEl.textContent = text;

  const label = META_LABELS[intent];
  if (label) {
    metaEl.textContent = label;
    if (intent === "blocked" || intent === "error") {
      metaEl.classList.add("meta-tag-blocked");
    }
  }
  chat.scrollTop = chat.scrollHeight;
}

// ---------- File upload ----------

dropzone.addEventListener("click", () => fileInput.click());

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("drag-over");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("drag-over");
});

dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  if (e.dataTransfer.files.length) {
    handleUpload(e.dataTransfer.files[0]);
  }
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) {
    handleUpload(fileInput.files[0]);
  }
});

async function handleUpload(file) {
  const validTypes = [".pdf", ".txt"];
  const isValid = validTypes.some(ext => file.name.toLowerCase().endsWith(ext));
  if (!isValid) {
    uploadStatus.textContent = "Only PDF or .txt files are supported.";
    return;
  }

  uploadStatus.textContent = `Indexing ${file.name}…`;

  const formData = new FormData();
  formData.append("file", file);
  if (sellerTagSelect.value) {
    formData.append("seller_id", sellerTagSelect.value);
  }

  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    uploadStatus.textContent = `Indexed "${data.filename}" — ${data.chunks_indexed} chunks (${data.seller_tag})`;
  } catch (err) {
    uploadStatus.textContent = "Upload failed. Check the backend server.";
  }
}