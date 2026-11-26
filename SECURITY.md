# Segurança

## Como avisar uma falha

**Não abra uma issue pública** para falhas de segurança (outras pessoas poderiam explorá-la antes da correção).

- Use **Security → Report a vulnerability** neste repositório no GitHub (aviso privado), ou
- escreva para `fausto@biazzitech.com.br` com o assunto "Segurança - BiazziTech AI Studio".

Conte o que acontece, como reproduzir e a versão usada. A resposta vem em até 7 dias; depois da correção,
você recebe os créditos no histórico de versões (se quiser).

## O que o projeto já faz

- O painel começa **só no próprio PC** (`127.0.0.1`). A rede precisa ser ligada de propósito e **exige um usuário
  com senha** e o aceite dos riscos.
- Senhas guardadas com PBKDF2-SHA256 e salt; bloqueio após 5 senhas erradas; registro de logins em `acessos.log`.
- Cookie de sessão `HttpOnly` e `SameSite=Strict` (e `Secure` com HTTPS).
- Outros sites abertos no navegador não conseguem usar a API do painel (verificação de origem em todo POST e CORS
  só para a própria origem).
- HTTPS opcional para a rede local (certificado em `%USERPROFILE%\.biazzitech\cert.pem` e `key.pem`).
- As chaves de API nunca aparecem inteiras no painel nem nas respostas.

## Recomendações para quem usa

- Libere a rede só em redes de confiança e, se possível, com HTTPS.
- **Nunca** abra a porta do painel no roteador para a internet. Para acessar de fora, use uma VPN (ex.: Tailscale).
- Guarde o `~/.env` (suas chaves) com cuidado e não o compartilhe.
- Cada provedor de IA tem termos de uso próprios; você é responsável por segui-los.

## Garantia

O software é fornecido "no estado em que se encontra", **sem garantias**, conforme as seções 15 e 16 da
[licença AGPL-3.0](LICENSE).
