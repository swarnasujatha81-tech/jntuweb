// Change this constant later if the backend is hosted at another address.
const BACKEND_URL = "http://localhost:8000";

const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const sendButton = document.querySelector("#send-button");

function addMessage(text, sender) {
  const message = document.createElement("div");
  message.className = `message ${sender}-message`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = sender === "user" ? "You" : "Assistant";

  const content = document.createElement("p");
  content.textContent = text;
  message.append(label, content);
  messages.appendChild(message);
  messages.scrollTop = messages.scrollHeight;
  return message;
}

function setLoading(isLoading) {
  sendButton.disabled = isLoading;
  input.disabled = isLoading;
  sendButton.textContent = isLoading ? "..." : "Send";
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
    const data = await response.json();
    loadingMessage.remove();

    if (!response.ok) {
      throw new Error(data.detail || "The backend returned an error.");
    }
    addMessage(data.reply, "assistant");
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
