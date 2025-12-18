// =======================
// TABS (ABAS)
// =======================

function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button");
    const tabChat = document.getElementById("tab-chat");
    const tabCampaigns = document.getElementById("tab-campaigns");

    buttons.forEach(btn => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;

            // Atualiza estado visual dos botões
            buttons.forEach(b => b.classList.remove("tab-active"));
            btn.classList.add("tab-active");

            // Mostra / esconde conteúdo
            if (tab === "chat") {
                tabChat.classList.remove("tab-hidden");
                tabChat.classList.add("tab-visible");
                tabCampaigns.classList.remove("tab-visible");
                tabCampaigns.classList.add("tab-hidden");
            } else {
                tabCampaigns.classList.remove("tab-hidden");
                tabCampaigns.classList.add("tab-visible");
                tabChat.classList.remove("tab-visible");
                tabChat.classList.add("tab-hidden");
            }
        });
    });
}


// =======================
// AUTH HELPERS
// =======================

// index.html criou window.apiFetch (com Bearer automático).
// Se por algum motivo não existir, cai no fetch normal (mas sem auth).
async function api(url, options = {}) {
    if (window.apiFetch) {
        return await window.apiFetch(url, options);
    }
    // fallback
    return await fetch(url, options);
}


// =======================
// CHAT
// =======================

let conversations = [];
let selectedConversationId = null;

// Carrega conversas
async function loadConversations() {
    try {
        const res = await api("/api/conversations");
        conversations = await res.json();
        renderConversations(conversations);
    } catch (e) {
        // se estiver deslogado, apiFetch já mostrou login
        // evita estourar erro no console/polling
        // console.warn("loadConversations:", e);
    }
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
    try {
        const res = await api(`/api/conversations/${conversationId}/messages`);
        const msgs = await res.json();
        renderMessages(msgs);
    } catch (e) {
        // console.warn("loadMessages:", e);
    }
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

    const text = (msgInput?.value || "").trim();
    const phoneNumberId = (phoneNumberIdInput?.value || "").trim();

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

    try {
        const res = await api("/api/messages/text", {
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

    } catch (e) {
        // apiFetch já pode ter mostrado login em caso de 401
        // console.warn("sendMessage:", e);
    }
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
function setupChatPolling() {
    setInterval(async () => {
        // se não tiver token, não adianta ficar chamando
        // (index.html controla o login)
        try {
            await loadConversations();
            if (selectedConversationId) {
                await loadMessages(selectedConversationId);
            }
        } catch (e) {
            // ignora
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

    try {
        const res = await api("/api/campaigns", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });

        if (!res.ok) {
            const err = await res.text();
            alert("Erro ao criar campanha: " + err);
            return;
        }

        await loadCampaigns();
    } catch (e) {
        // console.warn("startCampaign:", e);
    }
}

async function loadCampaigns() {
    const container = document.getElementById("campaigns-status");
    if (!container) return;

    try {
        const res = await api("/api/campaigns");
        const list = await res.json();

        container.innerHTML = "";

        list.forEach(c => {
            const div = document.createElement("div");
            div.className = "campaign-status-item";

            const created = c.created_at ? new Date(c.created_at).toLocaleString("pt-BR") : "";

            div.textContent = `${c.name} - ${c.status} | Enviados: ${c.sent}/${c.total} | Falhas: ${c.failed} | Criada em: ${created}`;
            container.appendChild(div);
        });
    } catch (e) {
        // console.warn("loadCampaigns:", e);
    }
}

function setupCampaignPolling() {
    setInterval(loadCampaigns, 5000);
}


// =======================
// INICIALIZAÇÃO GERAL
// =======================

document.addEventListener("DOMContentLoaded", async () => {
    // Tabs
    setupTabs();

    // Chat
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
    setupChatPolling();

    // Só tenta carregar se estiver logado (token existe)
    // Quem controla isso é o index.html.
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
