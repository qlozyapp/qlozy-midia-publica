# Publicador do @qlozyapp (Instagram + Facebook)

Publica sozinho no Instagram e na página do Facebook pela API oficial da Meta. É gratuito e não tem limite de posts por mês. A própria Meta limita a 100 posts pela API a cada 24 horas.

Ele substitui o agendamento do Metricool, cujo plano grátis dá só 20 posts por mês, e cada rede conta como um post.

O GitHub Actions roda o publicador a cada 10 minutos. Como este repositório é público, as execuções não custam nada. A chave da Meta fica guardada como segredo do repositório e não aparece no código nem nos logs.

## O que ele faz e o que não faz

| | Instagram | Facebook |
|---|---|---|
| Imagem | ✅ (só JPG) | ✅ |
| Carrossel (2 a 10 imagens) | ✅ (só JPG) | ✅ (post com várias fotos) |
| Reel | ✅ (com capa opcional) | ✅ |
| Story sem sticker | ✅ (JPG ou MP4) | ✅ (só JPG) |
| Story com enquete, caixinha ou quiz | ❌ a API não põe sticker: continua no celular | ❌ |
| Música do Instagram em foto ou carrossel | ❌ a API não põe música: vai sem, ou continua no celular | ❌ |

O TikTok e o YouTube ficam de fora e continuam manuais.

## Configuração (uma vez, uns 20 minutos no computador)

### 1. Confira as contas
- O @qlozyapp precisa ser conta **profissional** (empresa ou criador) e estar **ligado à página do Facebook** do Qlozy. Como o Metricool já publica nas duas, isso deve estar certo.
- Para conferir, no Instagram, abra Configurações > Central de Contas.

### 2. Crie o app na Meta
1. Entre em <https://developers.facebook.com> com o seu Facebook. Se for a primeira vez, aceite os termos de desenvolvedor.
2. Abra **Meus apps > Criar app**.
3. Dê um nome, por exemplo "Qlozy Publicador".
4. Escolha o caso de uso de **gerenciar conteúdo de página e Instagram**. Se aparecer a pergunta do tipo de app, escolha **Empresa** (Business).
5. Se pedir um portfólio empresarial, escolha o do Qlozy, se existir.

O app pode ficar em modo **Desenvolvimento**. Como você é o administrador, ele publica nas suas próprias contas sem passar pela revisão da Meta.

### 3. Gere o token no Graph API Explorer
1. Abra <https://developers.facebook.com/tools/explorer>.
2. Em "Aplicativo do Meta", escolha o app que você criou.
3. Em "Usuário ou página", escolha **Obter token de acesso do usuário**.
4. Marque estas permissões:
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `instagram_basic`
   - `instagram_content_publish`
   - `business_management`
5. Clique em **Generate Access Token**.
6. Na janela da Meta, selecione a **página do Qlozy** e a conta **@qlozyapp**, e confirme.
7. Deixe a aba aberta. O token é o texto longo do campo "Token de acesso".

### 4. Pegue a chave secreta do app
No painel do app, abra **Configurações do app > Básico**. Anote o **ID do aplicativo** e clique em **Mostrar** na **Chave secreta do aplicativo**.

### 5. Rode o configurador
No terminal, dentro deste repositório:

```bash
python publicador/configurar_meta.py
```

- Ele pede o ID do app, a chave secreta e o token do passo 3. O que você cola não aparece na tela.
- Ele troca o token por um **token da página que não expira** e confere as permissões.
- Depois mostra a página e o Instagram encontrados e pergunta se pode gravar os segredos no GitHub. Ele usa o `gh`, que já está logado no seu computador.

**Não cole o token nem a chave secreta no chat do Claude.**

### 6. Teste
No GitHub, abra **qlozy-midia-publica > Actions > Publicar > Run workflow** e escolha `verificar`. O log deve mostrar a página, o @qlozyapp "ligado à página" e quantos posts pela API foram usados nas últimas 24 horas.

## Como agendar um post

Para cada post, crie um arquivo em `agenda/`. A rotina `qlozy-publicar` faz isso. O nome é `AAAA-MM-DD-HHMM-<slug>.json`:

```json
{
  "issue": 3,
  "quando": "2026-12-01T10:00:00-03:00",
  "postagens": [
    {
      "rede": "instagram",
      "tipo": "carrossel",
      "midias": ["posts/2026-12-01-exemplo/01.jpg", "posts/2026-12-01-exemplo/02.jpg"],
      "legenda": "texto exato de legenda.txt"
    },
    {
      "rede": "facebook",
      "tipo": "carrossel",
      "midias": ["posts/2026-12-01-exemplo/01.jpg", "posts/2026-12-01-exemplo/02.jpg"],
      "legenda": "texto exato de legenda-facebook.txt"
    }
  ]
}
```

- **`rede`:** `instagram` ou `facebook`.
- **`tipo`:** `imagem`, `carrossel`, `reel` ou `story`.
- **`midias`:** caminhos dentro deste repositório. No Instagram, imagem é sempre `.jpg`. Reel leva `"capa"` opcional, também `.jpg`.
- **Story:** não tem `legenda`.
- **`quando` sem fuso:** vale o horário de São Paulo.

Depois de publicar, o próprio publicador grava no arquivo um bloco `"resultado"` por rede:

| Status | O que significa |
|---|---|
| `publicado` | Saiu. O bloco traz o `id` e o `link` do post. |
| `erro` | Deu erro. Ele tenta de novo nas próximas execuções, até 3 vezes. |
| `desistiu` | Falhou nas 3 tentativas. Publique pelo celular. |
| `vencido` | Passaram mais de 3 horas do horário sem conseguir publicar, por exemplo com o GitHub fora do ar. Ele não publica atrasado: publique pelo celular. |

Ele não publica duas vezes: antes de postar, procura nas últimas publicações um post com a mesma legenda.

Para conferir os arquivos sem publicar nada:

```bash
python publicador/publicar.py validar
```

```bash
python publicador/publicar.py --simular
```

O GitHub manda e-mail quando uma execução falha.

## Testes

```bash
python -m unittest discover -s publicador -v
```

Os testes usam a API simulada e não publicam nada de verdade. Rodam sozinhos em todo PR.
