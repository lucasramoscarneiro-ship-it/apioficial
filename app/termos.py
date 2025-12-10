from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/termos", response_class=HTMLResponse)
def termos_de_servico():
    return """
    <html>
        <head>
            <meta charset="utf-8" />
            <title>Termos de Serviço</title>
        </head>
        <body>
            <h1>Termos de Serviço</h1>
            <p>Bem-vindo à plataforma de mensagens <strong>novomodomensagens</strong>.
            Ao utilizar nossos serviços, você concorda com estes Termos de Serviço.</p>

            <h2>1. Uso da plataforma</h2>
            <p>A plataforma é destinada ao envio e recebimento de mensagens através da
            API Oficial do WhatsApp Business. O usuário é responsável pelo conteúdo
            das mensagens enviadas aos seus contatos.</p>

            <h2>2. Conteúdo proibido</h2>
            <p>É proibido utilizar a plataforma para enviar spam, conteúdos ilegais,
            discriminatórios, ameaçadores, enganosos ou que violem as políticas da Meta,
            da legislação aplicável ou direitos de terceiros.</p>

            <h2>3. Dados e privacidade</h2>
            <p>Os dados tratados pela plataforma seguem a nossa
            <a href="/politica">Política de Privacidade</a>. O usuário é responsável
            pela conformidade com a LGPD no uso dos dados de seus contatos.</p>

            <h2>4. Responsabilidade</h2>
            <p>Nos esforçamos para manter a plataforma disponível e segura, mas não
            garantimos funcionamento ininterrupto. Não nos responsabilizamos por danos
            decorrentes de mau uso da ferramenta ou descumprimento das políticas da Meta.</p>

            <h2>5. Alterações</h2>
            <p>Estes Termos podem ser alterados a qualquer momento. A continuação do uso
            da plataforma após alterações significa aceitação dos novos termos.</p>

            <h2>6. Contato</h2>
            <p>Em caso de dúvidas, entre em contato pelo e-mail:
            <strong>bia_cardoso99@outlook.com</strong>.</p>
        </body>
    </html>
    """
