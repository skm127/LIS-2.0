/**
 * LIS — Main entry point.
 *
 * Wires together the orb visualization, WebSocket communication,
 * speech recognition, and audio playback into a single experience.
 */

import { createOrb, type OrbState } from "./orb";
import { createVoiceInput, createAudioPlayer } from "./voice";
import { createSocket } from "./ws";
import { openSettings, checkFirstTimeSetup } from "./settings";
import "./style.css";

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

type State = "idle" | "listening" | "thinking" | "speaking";
let currentState: State = "idle";
let isMuted = false;

const statusEl = document.getElementById("status-text")!;
const errorEl = document.getElementById("error-text")!;

function showError(msg: string) {
  errorEl.textContent = msg;
  errorEl.style.opacity = "1";
  setTimeout(() => {
    errorEl.style.opacity = "0";
  }, 5000);
}

function updateStatus(state: State) {
  const labels: Record<State, string> = {
    idle: "",
    listening: "listening...",
    thinking: "thinking...",
    speaking: "",
  };
  statusEl.textContent = labels[state];
}

// ---------------------------------------------------------------------------
// Init components
// ---------------------------------------------------------------------------

const canvas = document.getElementById("orb-canvas") as HTMLCanvasElement;
const orb = createOrb(canvas);

const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${wsProto}//${window.location.host}/ws/voice`;
const socket = createSocket(WS_URL);

const audioPlayer = createAudioPlayer();
orb.setAnalyser(audioPlayer.getAnalyser());

function transition(newState: State) {
  if (newState === currentState) return;
  currentState = newState;
  orb.setState(newState as OrbState);
  updateStatus(newState);

  switch (newState) {
    case "idle":
      if (!isMuted) voiceInput.resume();
      break;
    case "listening":
      if (!isMuted) voiceInput.resume();
      break;
    case "thinking":
      voiceInput.pause();
      break;
    case "speaking":
      voiceInput.pause();
      break;
  }
}

// ---------------------------------------------------------------------------
// Voice input
// ---------------------------------------------------------------------------

const voiceInput = createVoiceInput(
  (text: string) => {
    // Cancel any current LIS response before sending new input
    audioPlayer.stop();
    // User spoke — send transcript
    socket.send({ type: "transcript", text, isFinal: true });
    transition("thinking");
  },
  (msg: string) => {
    showError(msg);
  },
  () => {
    // Barge-in: if LIS is speaking, stop her immediately
    if (currentState === "speaking") {
      console.log("[barge-in] User interrupted LIS");
      audioPlayer.stop();
      transition("idle");
      socket.send({ type: "abort_audio" });
    }
  }
);

// ---------------------------------------------------------------------------
// Audio playback finished
// ---------------------------------------------------------------------------

audioPlayer.onFinished(() => {
  transition("idle");
});

// ---------------------------------------------------------------------------
// WebSocket messages
// ---------------------------------------------------------------------------

let lastLisResponse = "";
const feedbackUi = document.getElementById("feedback-ui")!;
const btnFeedbackUp = document.getElementById("btn-feedback-up")!;
const btnFeedbackDown = document.getElementById("btn-feedback-down")!;

async function submitFeedback(isPositive: boolean) {
  if (!lastLisResponse) return;
  feedbackUi.style.display = "none";
  try {
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ last_response: lastLisResponse, is_positive: isPositive })
    });
  } catch (err) {
    console.error("Feedback error:", err);
  }
}

btnFeedbackUp.addEventListener("click", () => submitFeedback(true));
btnFeedbackDown.addEventListener("click", () => submitFeedback(false));

socket.onMessage((msg) => {
  const type = msg.type as string;

  if (type === "stop_audio") {
    // Server is about to send new audio — clear any stale queued audio from previous responses
    audioPlayer.stop();
    lastLisResponse = "";
    feedbackUi.style.display = "none";
  } else if (type === "audio") {
    const audioData = msg.data as string;
    console.log("[audio] received", audioData ? `${audioData.length} chars` : "EMPTY", "state:", currentState);
    if (audioData) {
      if (currentState !== "speaking") {
        transition("speaking");
      }
      audioPlayer.enqueue(audioData);
    } else {
      // TTS failed — no audio but still need to return to idle
      console.warn("[audio] no data received, returning to idle");
      transition("idle");
    }
    // Log text for debugging and accumulate for feedback
    if (msg.text) {
      console.log("[LIS]", msg.text);
      lastLisResponse += (lastLisResponse ? " " : "") + msg.text;
    }
  } else if (type === "status") {
    const state = msg.state as string;
    if (state === "thinking" && currentState !== "thinking") {
      transition("thinking");
    } else if (state === "working") {
      // Task spawned — show thinking with a different label
      transition("thinking");
      statusEl.textContent = "working...";
    } else if (state === "idle") {
      transition("idle");
      // Show feedback UI if we have a recent response
      if (lastLisResponse && lastLisResponse.length > 5 && !document.hidden) {
        feedbackUi.style.display = "flex";
        feedbackUi.style.alignItems = "center";
        
        // Auto-hide after 10 seconds
        setTimeout(() => {
          if (feedbackUi.style.display !== "none") {
            feedbackUi.style.display = "none";
          }
        }, 10000);
      }
    }
  } else if (type === "text") {
    if (msg.text) {
      lastLisResponse = msg.text as string;
    }
    // Text fallback when TTS fails
    console.log("[LIS]", msg.text);
  } else if (type === "task_spawned") {
    console.log("[task]", "spawned:", msg.task_id, msg.prompt);
  } else if (type === "task_complete") {
    console.log("[task]", "complete:", msg.task_id, msg.status, msg.summary);
  }
});

// ---------------------------------------------------------------------------
// Kick off
// ---------------------------------------------------------------------------

// Start listening after a brief delay for the orb to render
setTimeout(() => {
  voiceInput.start();
  transition("listening");
}, 1000);

// Resume AudioContext on ANY user interaction (browser autoplay policy)
function ensureAudioContext() {
  const ctx = audioPlayer.getAnalyser().context as AudioContext;
  if (ctx.state === "suspended") {
    ctx.resume().then(() => console.log("[audio] context resumed"));
  }
}
document.addEventListener("click", ensureAudioContext);
document.addEventListener("touchstart", ensureAudioContext);
document.addEventListener("keydown", ensureAudioContext, { once: true });

// Try to resume audio context on load
ensureAudioContext();

// ---------------------------------------------------------------------------
// UI Controls
// ---------------------------------------------------------------------------

const btnMute = document.getElementById("btn-mute")!;
const btnMenu = document.getElementById("btn-menu")!;
const menuDropdown = document.getElementById("menu-dropdown")!;
const btnRestart = document.getElementById("btn-restart")!;
const btnFixSelf = document.getElementById("btn-fix-self")!;

btnMute.addEventListener("click", (e) => {
  e.stopPropagation();
  isMuted = !isMuted;
  btnMute.classList.toggle("muted", isMuted);
  if (isMuted) {
    voiceInput.pause();
    transition("idle");
  } else {
    voiceInput.resume();
    transition("listening");
  }
});

btnMenu.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = menuDropdown.style.display === "none" ? "block" : "none";
});

document.addEventListener("click", () => {
  menuDropdown.style.display = "none";
});

btnRestart.addEventListener("click", async (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  statusEl.textContent = "restarting...";
  try {
    await fetch("/api/restart", { method: "POST" });
    // Wait a few seconds then reload
    setTimeout(() => window.location.reload(), 4000);
  } catch {
    statusEl.textContent = "restart failed";
  }
});

btnFixSelf.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  // Activate work mode on the WebSocket session (LIS becomes Claude Code's voice)
  socket.send({ type: "fix_self" });
  statusEl.textContent = "entering work mode...";
});

// Settings button
const btnSettings = document.getElementById("btn-settings")!;
btnSettings.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  openSettings();
});

// First-time setup detection — check after a short delay for server readiness
setTimeout(() => {
  checkFirstTimeSetup();
}, 2000);

// ---------------------------------------------------------------------------
// Text Fallback Input
// ---------------------------------------------------------------------------

const textInput = document.getElementById("text-input") as HTMLInputElement;

textInput.addEventListener("keydown", (e) => {
  // Ensure AudioContext is awakened if they never clicked the orb
  ensureAudioContext();
  
  if (e.key === "Enter") {
    const text = textInput.value.trim();
    if (text) {
      // Stop audio playback if she is currently speaking
      audioPlayer.stop();
      
      // Add to chat panel
      addChatMessage("user", text);
      
      // Send directly as a final transcript (mimicking the voice engine)
      socket.send({ type: "transcript", text, isFinal: true });
      textInput.value = "";
      
      // Visual feedback
      transition("thinking");
    }
  }
});

// ---------------------------------------------------------------------------
// Chat Panel
// ---------------------------------------------------------------------------

const chatPanel = document.getElementById("chat-panel")!;
const chatMessages = document.getElementById("chat-messages")!;
const chatMsgCount = document.getElementById("chat-msg-count")!;
const btnChatToggle = document.getElementById("btn-chat-toggle")!;
const btnChatClose = document.getElementById("btn-chat-close")!;

let chatOpen = false;
let messageCount = 0;
let typingIndicator: HTMLElement | null = null;

// Load persistent chat history on startup
async function loadChatHistory() {
  try {
    const resp = await fetch("/api/chat/history?limit=50");
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.messages && data.messages.length > 0) {
      for (const msg of data.messages) {
        const role = msg.role as "user" | "assistant";
        const msgEl = document.createElement("div");
        msgEl.className = `chat-msg ${role}`;
        const date = new Date(msg.timestamp * 1000);
        const timeStr = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        msgEl.innerHTML = `
          <div class="msg-text">${escapeHtmlSafe(msg.content)}</div>
          <span class="msg-time">${timeStr}</span>
        `;
        chatMessages.appendChild(msgEl);
        messageCount++;
      }
      chatMsgCount.textContent = `${messageCount} messages`;
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  } catch (e) {
    console.warn("[chat] Failed to load history:", e);
  }
}

function escapeHtmlSafe(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

loadChatHistory();

function toggleChat() {
  chatOpen = !chatOpen;
  chatPanel.classList.toggle("open", chatOpen);
  btnChatToggle.classList.remove("has-new");
}

btnChatToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleChat();
});

btnChatClose.addEventListener("click", (e) => {
  e.stopPropagation();
  chatOpen = false;
  chatPanel.classList.remove("open");
});

function addChatMessage(role: "user" | "assistant", text: string) {
  // Remove typing indicator if present
  removeTypingIndicator();
  
  const msgEl = document.createElement("div");
  msgEl.className = `chat-msg ${role}`;
  
  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  
  msgEl.innerHTML = `
    <div class="msg-text">${escapeHtml(text)}</div>
    <span class="msg-time">${timeStr}</span>
  `;
  
  chatMessages.appendChild(msgEl);
  messageCount++;
  chatMsgCount.textContent = `${messageCount} message${messageCount !== 1 ? "s" : ""}`;
  
  // Auto-scroll to bottom
  chatMessages.scrollTop = chatMessages.scrollHeight;
  
  // Show notification dot if panel is closed
  if (!chatOpen && role === "assistant") {
    btnChatToggle.classList.add("has-new");
  }
}

function showTypingIndicator() {
  if (typingIndicator) return;
  typingIndicator = document.createElement("div");
  typingIndicator.className = "chat-typing";
  typingIndicator.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
  chatMessages.appendChild(typingIndicator);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function removeTypingIndicator() {
  if (typingIndicator) {
    typingIndicator.remove();
    typingIndicator = null;
  }
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// --- Wire chat panel to existing voice pipeline ---

// Patch the voice input callback to also add user messages to chat
const originalVoiceCallback = (text: string) => {
  audioPlayer.stop();
  addChatMessage("user", text);
  socket.send({ type: "transcript", text, isFinal: true });
  transition("thinking");
};

// Re-create voice input with chat-aware callback
const voiceInputWithChat = createVoiceInput(
  originalVoiceCallback,
  (msg: string) => { showError(msg); },
  () => {
    if (currentState === "speaking") {
      console.log("[barge-in] User interrupted LIS");
      audioPlayer.stop();
      transition("idle");
      socket.send({ type: "abort_audio" });
    }
  }
);

// Override voiceInput methods to use the chat-aware version
// (voice input was already started, so we just need the message hook)

// Extend socket.onMessage to capture chat messages
socket.onMessage((msg) => {
  const type = msg.type as string;
  
  if (type === "status") {
    const state = msg.state as string;
    if (state === "thinking" || state === "working") {
      showTypingIndicator();
    } else {
      removeTypingIndicator();
    }
  } else if (type === "audio" && msg.text) {
    addChatMessage("assistant", msg.text as string);
  } else if (type === "text" && msg.text) {
    addChatMessage("assistant", msg.text as string);
  }
});
