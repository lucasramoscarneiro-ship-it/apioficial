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

// Seleciona conversa
async function selectConversation(id, conv) {
    selectedConversationId = id;
    document.getElementById("chat-contact-name").textContent = conv.name || conv.wa_id;
    document.getElementById("chat-contact-info").textContent = conv.wa_id;

    await loadMessages(id);
}

// Carrega mensagens
async function loadMessages(conversationId) {
    const res = await fetch(`/api/conversations/${conversationId}/messages`);
    const msgs = await res.json();
    renderMessages(msgs);
}

// Renderiza mensagens
function renderMessages(msgs) {
    const container = document.getElementById("messages-container");
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

// Envia mensagem de texto no chat atual
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

    if (res.ok) {
        msgInput.value = "";
        await loadMessages(selectedConversationId);
        await loadConversations();
    } else {
        const err = await res.text();
        alert("Erro ao enviar mensagem: " + err);
    }
}

// Busca nas conversas
function setupSearch() {
    const input = document.getElementById("search-input");
    input.addEventListener("input", () => {
        const term = input.value.toLowerCase();
        const filtered = conversations.filter(c =>
            (c.name || "").toLowerCase().includes(term) ||
            (c.wa_id || "").toLowerCase().includes(term)
        );
        renderConversations(filtered);
    });
}

// Polling para chat
function setupPolling() {
    setInterval(async () => {
        await loadConversations();
        if (selectedConversationId) {
            await loadMessages(selectedConversationId);
        }
    }, 5000);
}


// =======================
// CAMPANHAS
// =======================

function getCampaignMode() {
    const radios = document.querySelectorAll("input[name='campaign-mode']");
    for (const r of radios) {
        if (r.checked) return r.value;
    }
    return "text";
}

function setupCampaignModeSwitch() {
    const radios = document.querySelectorAll("input[name='campaign-mode']");
    const textFields = document.getElementById("campaign-text-fields");
    const templateFields = document.getElementById("campaign-template-fields");

    radios.forEach(r => {
        r.addEventListener("change", () => {
            const mode = getCampaignMode();
            if (mode === "text") {
                textFields.style.display = "block";
                templateFields.style.display = "none";
            } else {
                textFields.style.display = "none";
                templateFields.style.display = "block";
            }
        });
    });
}

async function startCampaign() {
    const name = document.getElementById("campaign-name").value.trim();
    const phoneNumberId = document.getElementById("campaign-phone-number-id").value.trim();
    const numbersText = document.getElementById("campaign-numbers").value.trim();

    const mode = getCampaignMode();

    if (!name || !phoneNumberId || !numbersText) {
        alert("Preencha nome, PHONE_NUMBER_ID e os números.");
        return;
    }

    const toNumbers = numbersText
        .split("\n")
        .map(n => n.trim())
        .filter(n => n.length > 0);

    let body = {
        name: name,
        phone_number_id: phoneNumberId,
        to_numbers: toNumbers,
    };

    if (mode === "text") {
        const message = document.getElementById("campaign-message").value.trim();
        if (!message) {
            alert("Digite a mensagem de texto.");
            return;
        }

        body.message_text = message;
        body.template_name = null;
        body.template_language_code = null;
        body.template_body_params = null;
    } else {
        const tplName = document.getElementById("campaign-template-name").value.trim();
        const tplLang = document.getElementById("campaign-template-language").value.trim() || "pt_BR";
        const tplParamsText = document.getElementById("campaign-template-params").value.trim();

        if (!tplName) {
            alert("Digite o nome do template.");
            return;
        }

        let params = [];
        if (tplParamsText) {
            params = tplParamsText
                .split("\n")
                .map(p => p.trim())
                .filter(p => p.length > 0);
        }

        body.template_name = tplName;
        body.template_language_code = tplLang;
        body.template_body_params = params;
        body.message_text = null;
    }

    const res = await fetch("/api/campaigns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });

    if (!res.ok) {
        const err = await res.text();
        alert("Erro ao criar campanha: " + err);
        return;
    }

    const camp = await res.json();
    console.log("Campanha criada:", camp);
    await loadCampaigns();
}

async function loadCampaigns() {
    const res = await fetch("/api/campaigns");
    const list = await res.json();

    const container = document.getElementById("campaigns-status");
    container.innerHTML = "";

    list.forEach(c => {
        const div = document.createElement("div");
        div.style.marginBottom = "4px";
        div.textContent = `${c.name} - ${c.status} | Enviados: ${c.sent}/${c.total} | Falhas: ${c.failed}`;
        container.appendChild(div);
    });
}

function setupCampaignPolling() {
    setInterval(loadCampaigns, 5000);
}


// =======================
// INICIALIZAÇÃO
// =======================

document.addEventListener("DOMContentLoaded", async () => {
    // Chat
    document.getElementById("send-button").addEventListener("click", sendMessage);
    document.getElementById("message-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendMessage();
    });

    setupSearch();
    setupPolling();
    await loadConversations();

    // Campanhas
    const btnCamp = document.getElementById("btn-start-campaign");
    if (btnCamp) {
        btnCamp.addEventListener("click", startCampaign);
    }
    setupCampaignModeSwitch();
    setupCampaignPolling();
    await loadCampaigns();
});
