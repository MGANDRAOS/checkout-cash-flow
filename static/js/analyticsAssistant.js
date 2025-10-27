/* ==========================================================================
   Analytics Assistant Widget
   Handles open/close behavior and chat-ui-lite initialization
   ========================================================================== */

const AnalyticsAssistant = (() => {
    let chatInstance = null; // Reference to chat-ui-lite object
    let isOpen = false;

    // Initialize the widget and bind all events
    const init = () => {
        const widget = document.getElementById("analyticsWidget");
        const toggleBtn = document.getElementById("assistantToggle");
        const closeBtn = document.getElementById("assistantClose");
        const chatContainer = document.getElementById("chat");

        if (!widget || !toggleBtn || !chatContainer) return;

        // Toggle open/close
        toggleBtn.addEventListener("click", () => toggleWidget(widget));
        if (closeBtn) closeBtn.addEventListener("click", () => toggleWidget(widget, false));

        /* ==========================================================================
           Analytics Assistant — Clean, full chat experience
           ========================================================================== */
        async function loadChatUILite() {
            const chatDiv = document.getElementById("chat");
            if (!chatDiv) return;

            // Reset any previous content
            chatDiv.innerHTML = `
    <div id="chat-shell" class="d-flex flex-column h-100">
      <div id="chat-messages" class="flex-grow-1 overflow-auto px-3 py-3">
        <div class="text-center text-secondary small mt-2">
          <span class="fw-semibold text-white">Checkout Analytics Assistant</span><br>
          <span>Ask me anything about sales, closings, or buffers</span>
        </div>
      </div>
      <div id="chat-input-bar"
           class="d-flex align-items-center border-top border-secondary bg-dark px-3 py-2">
        <input id="chat-input" type="text"
               class="form-control bg-dark border-0 me-2"
               placeholder="Type your question and press Enter…" />
        <button id="chat-send"
                class="btn btn-primary px-4 fw-semibold rounded-pill shadow-sm">
          Send
        </button>
      </div>
    </div>
  `;

            // style adjustments for larger, comfy layout
            chatDiv.style.display = "flex";
            chatDiv.style.flexDirection = "column";
            chatDiv.style.height = "100%";
            chatDiv.style.background = "#0d1117";
            chatDiv.style.color = "#e6edf3";
            chatDiv.style.fontFamily = "'Inter', sans-serif";
            chatDiv.style.fontSize = "0.95rem";

            const messages = document.getElementById("chat-messages");
            const input = document.getElementById("chat-input");
            const sendBtn = document.getElementById("chat-send");

            // helper to render message bubbles
            const append = (who, text) => {
                const wrapper = document.createElement("div");
                wrapper.className = `d-flex mb-2 ${who === "user" ? "justify-content-end" : "justify-content-start"
                    }`;

                const bubble = document.createElement("div");
                bubble.textContent = text.trim();
                bubble.className =
                    who === "user"
                        ? "px-3 py-2 rounded-4 bg-primary text-white"
                        : "px-3 py-2 rounded-4 bg-secondary-subtle ai-response-bubble";
                bubble.style.maxWidth = "85%";
                bubble.style.whiteSpace = "pre-wrap";

                wrapper.appendChild(bubble);
                messages.appendChild(wrapper);
                messages.scrollTop = messages.scrollHeight;
            };

            const sendMessage = async () => {
                const text = input.value.trim();
                if (!text) return;
                append("user", text);
                input.value = "";
                append("assistant", "…thinking");

                try {
                    const res = await fetch(`/stream-analytics?prompt=${encodeURIComponent(text)}`);
                    const reply = await res.text();
                    // replace last placeholder message
                    const last = messages.querySelector("div.justify-content-start:last-child div");
                    if (last && last.textContent === "…thinking") last.remove();
                    append("assistant", reply);
                } catch (err) {
                    append("assistant", "⚠️ Error fetching reply.");
                }
            };

            sendBtn.onclick = sendMessage;
            input.addEventListener("keydown", (e) => {
                if (e.key === "Enter") sendMessage();
            });
        }


        // When the widget is opened for the first time
        toggleBtn.addEventListener("click", () => {
            if (!isOpen) loadChatUILite();
        });
    };

    // Toggle visibility
    const toggleWidget = (widget, forceState = null) => {
        isOpen = forceState !== null ? forceState : !isOpen;
        widget.classList.toggle("collapsed", !isOpen);
    };

    // Stream assistant response from backend (OpenAI-like streaming)
    const streamResponse = async (userPrompt) => {
        const response = await fetch(`/stream-analytics?prompt=${encodeURIComponent(userPrompt)}`);
        if (!response.body) return;

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let partial = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            partial += chunk;
            if (chatInstance) chatInstance.appendAssistantText(chunk);
        }
    };

    return { init };
})();

/* ==========================================================================
   Bootstrap
   ========================================================================== */
document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("analyticsWidget")) {
        AnalyticsAssistant.init();
    }
});
