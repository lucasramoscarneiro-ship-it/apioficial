async function startCampaign() {
    const name = document.getElementById("campaign-name").value.trim();
    const numbersText = document.getElementById("campaign-numbers").value.trim();
    const mode = getCampaignMode();

    // 🔥 Só exige PHONE_NUMBER_ID se for TEMPLATE (Meta)
    const phoneNumberIdEl = document.getElementById("campaign-phone-number-id");
    const phoneNumberId = (phoneNumberIdEl?.value || "").trim();

    if (!name || !numbersText) {
        alert("Preencha o nome e os números.");
        return;
    }

    if (mode === "template" && !phoneNumberId) {
        alert("Preencha o PHONE_NUMBER_ID (obrigatório para Template/Meta).");
        return;
    }

    const toNumbers = numbersText
        .split("\n")
        .map(n => n.trim())
        .filter(n => n.length > 0);

    // Base do body
    let body = {
        name: name,
        to_numbers: toNumbers,
    };

    if (mode === "text") {
        const message = document.getElementById("campaign-message").value.trim();
        if (!message) {
            alert("Digite a mensagem de texto.");
            return;
        }

        // ✅ campanha via Evolution (sem phone_number_id)
        body.message_text = message;

        // garante que não vai mandar campos de template
        body.template_name = null;
        body.template_language_code = null;
        body.template_body_params = null;

        // ⚠️ se seu backend exigir phone_number_id no CampaignCreate,
        // mande vazio pra não quebrar (mas o ideal é tirar do Pydantic no backend).
        body.phone_number_id = "";

    } else {
        // ✅ campanha via Meta Template (exige phone_number_id)
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

        body.phone_number_id = phoneNumberId;
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
