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

    await loadCampaigns();
}

async function loadCampaigns() {
    const res = await fetch("/api/campaigns");
    const list = await res.json();

    const container = document.getElementById("campaigns-status");
    if (!container) return;

    container.innerHTML = "";

    list.forEach(c => {
        const div = document.createElement("div");
        div.className = "campaign-status-item";

        const created = c.created_at ? new Date(c.created_at).toLocaleString("pt-BR") : "";

        div.textContent = `${c.name} - ${c.status} | Enviados: ${c.sent}/${c.total} | Falhas: ${c.failed} | Criada em: ${created}`;
        container.appendChild(div);
    });
}

function setupCampaignPolling() {
    setInterval(loadCampaigns, 5000);
}

document.addEventListener("DOMContentLoaded", async () => {
    const btnCamp = document.getElementById("btn-start-campaign");
    if (btnCamp) {
        btnCamp.addEventListener("click", startCampaign);
    }

    setupCampaignModeSwitch();
    setupCampaignPolling();
    await loadCampaigns();
});
