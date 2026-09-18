// Change this constant later if the backend is hosted at another address.
const BACKEND_URL = "http://localhost:8000";
const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt"];

const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const sendButton = document.querySelector("#send-button");
const tabs = document.querySelectorAll(".view-tab");
const panels = document.querySelectorAll(".view-panel");
const fileInput = document.querySelector("#file-input");
const dropZone = document.querySelector("#drop-zone");
const uploadForm = document.querySelector("#upload-form");
const uploadButton = document.querySelector("#upload-button");
const selectedFiles = document.querySelector("#selected-files");
const documentNotice = document.querySelector("#document-notice");
const documentsList = document.querySelector("#documents-list");
const refreshDocumentsButton = document.querySelector("#refresh-documents");
let filesToUpload = [];

function addMessage(text, sender, sources = []) {
  const message = document.createElement("div");
  message.className = `message ${sender}-message`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = sender === "user" ? "You" : "Assistant";

  const content = document.createElement("p");
  content.textContent = text;
  message.append(label, content);

  if (sources.length > 0) {
    const sourceList = document.createElement("div");
    sourceList.className = "sources";
    const sourceTitle = document.createElement("strong");
    sourceTitle.textContent = "Sources";
    sourceList.appendChild(sourceTitle);

    sources.forEach((source) => {
      const sourceItem = document.createElement("span");
      const page = source.page_number ? `, page ${source.page_number}` : "";
      sourceItem.textContent = `${source.filename}${page}`;
      sourceList.appendChild(sourceItem);
    });
    message.appendChild(sourceList);
  }

  messages.appendChild(message);
  messages.scrollTop = messages.scrollHeight;
  return message;
}

function setLoading(isLoading) {
  sendButton.disabled = isLoading;
  input.disabled = isLoading;
  sendButton.textContent = isLoading ? "..." : "Send";
}

async function getErrorMessage(response, fallback) {
  try {
    const data = await response.json();
    return data.detail || fallback;
  } catch {
    return fallback;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  addMessage(message, "user");
  input.value = "";
  input.style.height = "auto";
  const loadingMessage = addMessage("Thinking...", "loading");
  setLoading(true);

  try {
    const response = await fetch(`${BACKEND_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!response.ok) {
      throw new Error(await getErrorMessage(response, "The backend returned an error."));
    }
    const data = await response.json();
    if (typeof data.reply !== "string") {
      throw new Error("The backend returned an invalid response.");
    }
    loadingMessage.remove();
    addMessage(data.reply, "assistant", data.sources || []);
  } catch (error) {
    loadingMessage.remove();
    addMessage(`Sorry, I could not get a response. ${error.message}`, "assistant");
  } finally {
    setLoading(false);
    input.focus();
  }
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
});

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((item) => item.classList.toggle("active", item === tab));
    panels.forEach((panel) => panel.classList.toggle("active-view", panel.id === tab.dataset.view));
    if (tab.dataset.view === "documents-view") {
      loadDocuments();
    }
  });
});

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "Size unavailable";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isAllowedFile(file) {
  const name = file.name.toLowerCase();
  return ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension));
}

function setSelectedFiles(files) {
  const accepted = [];
  const rejected = [];
  files.forEach((file) => {
    if (isAllowedFile(file)) accepted.push(file);
    else rejected.push(file.name);
  });
  filesToUpload = accepted;
  if (rejected.length > 0) {
    showNotice(`Unsupported file type skipped: ${rejected.join(", ")}`, "error");
  }
  selectedFiles.textContent = accepted.length
    ? accepted.map((file) => `${file.name} (${formatFileSize(file.size)})`).join("; ")
    : "No supported files selected";
}

function showNotice(message, type = "") {
  documentNotice.textContent = message;
  documentNotice.className = `document-notice ${type}`.trim();
}

fileInput.addEventListener("change", () => setSelectedFiles(Array.from(fileInput.files || [])));

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
});

dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
  setSelectedFiles(Array.from(event.dataTransfer.files || []));
});
dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") fileInput.click();
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!filesToUpload.length) {
    showNotice("Choose at least one PDF, DOCX, or TXT file.", "error");
    return;
  }

  uploadButton.disabled = true;
  const results = [];
  for (const file of filesToUpload) {
    showNotice(`Processing ${file.name}...`);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await fetch(`${BACKEND_URL}/ingest`, { method: "POST", body: formData });
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "The upload failed."));
      }
      const result = await response.json();
      results.push(`${file.name}: ${result.status === "skipped" ? "already indexed" : "Indexed"}`);
    } catch (error) {
      results.push(`${file.name}: failed - ${error.message}`);
    }
  }

  const failures = results.filter((result) => result.includes("failed"));
  showNotice(results.join(" | "), failures.length ? "error" : "success");
  filesToUpload = [];
  fileInput.value = "";
  selectedFiles.textContent = "No files selected";
  uploadButton.disabled = false;
  await loadDocuments();
});

function renderDocuments(documents) {
  documentsList.replaceChildren();
  if (!documents.length) {
    const empty = document.createElement("div");
    empty.className = "empty-documents";
    empty.textContent = "No documents indexed yet.";
    documentsList.appendChild(empty);
    return;
  }

  documents.forEach((documentItem) => {
    const card = document.createElement("article");
    card.className = "document-card";
    const info = document.createElement("div");
    info.className = "document-info";
    const name = document.createElement("span");
    name.className = "document-name";
    name.textContent = documentItem.filename || "Unnamed document";
    const meta = document.createElement("span");
    meta.className = "document-meta";
    const type = (documentItem.file_type || "file").toUpperCase();
    const size = documentItem.size_bytes ? ` • ${formatFileSize(documentItem.size_bytes)}` : "";
    meta.textContent = `${type}${size} • ${documentItem.chunk_count || 0} chunks • ${documentItem.status || "indexed"}`;
    info.append(name, meta);
    card.appendChild(info);

    if (!documentItem.is_builtin) {
      const deleteButton = document.createElement("button");
      deleteButton.className = "delete-button";
      deleteButton.type = "button";
      deleteButton.textContent = "Delete";
      deleteButton.addEventListener("click", () => deleteDocument(documentItem));
      card.appendChild(deleteButton);
    } else {
      const protectedLabel = document.createElement("span");
      protectedLabel.className = "document-meta";
      protectedLabel.textContent = "Built-in knowledge";
      card.appendChild(protectedLabel);
    }
    documentsList.appendChild(card);
  });
}

async function loadDocuments() {
  refreshDocumentsButton.disabled = true;
  try {
    const response = await fetch(`${BACKEND_URL}/documents`);
    if (!response.ok) throw new Error(await getErrorMessage(response, "Could not load documents."));
    const data = await response.json();
    if (!Array.isArray(data.documents)) throw new Error("The backend returned an invalid document list.");
    renderDocuments(data.documents);
  } catch (error) {
    documentsList.replaceChildren();
    const failure = document.createElement("div");
    failure.className = "empty-documents";
    failure.textContent = `Could not load documents. ${error.message}`;
    documentsList.appendChild(failure);
  } finally {
    refreshDocumentsButton.disabled = false;
  }
}

async function deleteDocument(document) {
  if (!document.id || document.is_builtin) return;
  if (!window.confirm(`Delete ${document.filename}?`)) return;
  showNotice(`Deleting ${document.filename}...`);
  try {
    const response = await fetch(`${BACKEND_URL}/documents/${encodeURIComponent(document.id)}`, { method: "DELETE" });
    if (!response.ok) throw new Error(await getErrorMessage(response, "The document could not be deleted."));
    showNotice(`${document.filename} deleted.`, "success");
    await loadDocuments();
  } catch (error) {
    showNotice(`Delete failed: ${error.message}`, "error");
  }
}

refreshDocumentsButton.addEventListener("click", loadDocuments);
loadDocuments();
