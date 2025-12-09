let conversations = [];
let selectedConversationId = null;

// =======================
// CHAT
// =======================

// Carrega conversas
async function loadConversations() {
    const res = await fetch("/api/conversations");
    conversations = await res.json();
    renderConversations(conversations);
}

// Renderiza lista de conversas
function renderConversations(list) {
    const container = document.getElementById("conversations-list");
    if (!container) return;

    container.innerHTML = "";

    list.forEach(conv => {
        const item = document.createElement("div");
        item.className = "conversation-item";
        item.dataset.id = conv.id;

        const title = document.createElement("div");
        title.className = "conversation-title";
        title.textContent = conv.name || conv.wa_id;

        const lastMsg = document.createElement("div");
        lastMsg.className = "conversation-last-message";
        lastMsg.textContent = conv.last_message_text || "";

        item.appendChild(title);
        item.appendChild(lastMsg);

        item.addEventListener("click", () => {
            selectConversation(conv.id, conv);
        });

        container.appendChild(item);
    });
}

// Selecionar conversa
async function selectConversation(id, conv) {
    selectedConversationId = id;
    const nameEl = document.getElementById("chat-contact-name");
    const infoEl = document.getElementById("chat-contact-info");

    if (nameEl) nameEl.textContent = conv.name || conv.wa_id;
    if (infoEl) infoEl.textContent = conv.wa_id;

    await loadMessages(id);
}

// Carrega mensagens da conversa
async function loadMessages(conversationId) {
    const res = await fetch(`/api/conversations/${conversationId}/messages`);
    const msgs = await res.json();
    renderMessages(msgs);
}

// Renderiza mensagens
function renderMessages(msgs) {
    const container = document.getElementById("messages-container");
    if (!container) return;

    container.innerHTML = "";

    msgs.forEach(m => {
        const row = document.createElement("div");
        row.className = "message-row " + m.direction;

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.textContent = m.text || "";

        const time = document.createElement("div");
        time.className = "message-time";
        const dt = new Date(m.timestamp);
        time.textContent = dt.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

        bubble.appendChild(time);
        row.appendChild(bubble);
        container.appendChild(row);
    });

    container.scrollTop = container.scrollHeight;
}

// Envia mensagem
async function sendMessage() {
    if (!selectedConversationId) {
        alert("Selecione uma conversa primeiro.");
        return;
    }

    const msgInput = document.getElementById("message-input");
    const phoneNumberIdInput = document.getElementById("phone-number-id-input");

    const text = msgInput.value.trim();
    const phoneNumberId = phoneNumberIdInput.value.trim();

    if (!text || !phoneNumberId) {
        alert("Digite a mensagem e o PHONE_NUMBER_ID.");
        return;
    }

    const conv = conversations.find(c => c.id === selectedConversationId);
    if (!conv) return;

    const body = {
        phone_number_id: phoneNumberId,
        to: conv.wa_id,
        message: text
    };

    const res = await fetch("/api/messages/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });

    if (!res.ok) {
        const err = await res.text();
        alert("Erro ao enviar mensagem: " + err);
        return;
    }

    msgInput.value = "";
    await loadMessages(selectedConversationId);
    await loadConversations();
}

// Busca conversas
function setupSearch() {
    const input = document.getElementById("search-input");
    if (!input) return;

    input.addEventListener("input", () => {
        const term = input.value.toLowerCase();
        const filtered = conversations.filter(c =>
            (c.name || "").toLowerCase().includes(term) ||
            (c.wa_id || "").toLowerCase().includes(term)
        );
        renderConversations(filtered);
    });
}

// Polling para atualizar conversas/mensagens
function setupPolling() {
    setInterval(async () => {
        await loadConversations();
        if (selectedConversationId) {
            await loadMessages(selectedConversationId);
        }
    }, 5000);
}

// Inicialização
document.addEventListener("DOMContentLoaded", async () => {
    const sendBtn = document.getElementById("send-button");
    if (sendBtn) {
        sendBtn.addEventListener("click", sendMessage);
    }

    const msgInput = document.getElementById("message-input");
    if (msgInput) {
        msgInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") sendMessage();
        });
    }

    setupSearch();
    setupPolling();
    await loadConversations();
});
