"""Configura os segredos do publicador (rodar uma vez, no seu computador).

Pede o App ID, a chave secreta do app e um token de usuário de curta duração
(do Graph API Explorer), troca por um token de página que não expira, confere
as permissões e grava três segredos no repositório qlozy-midia-publica com o
`gh secret set`:

    META_PAGE_TOKEN, META_PAGE_ID, META_IG_ID

Os tokens são digitados sem aparecer na tela e nunca são impressos.
Passo a passo completo em publicador/LEIAME.md.

    python publicador/configurar_meta.py
"""

from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publicar import GRAPH, ErroMeta, http  # noqa: E402

REPO = "qlozyapp/qlozy-midia-publica"
PERMISSOES = {
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
}


def gravar_segredo(nome: str, valor: str) -> None:
    subprocess.run(["gh", "secret", "set", nome, "-R", REPO], input=valor.encode(), check=True)


def main() -> int:
    print("Configuração do publicador do @qlozyapp (Instagram + Facebook)\n")
    app_id = input("App ID (Configurações do app > Básico): ").strip()
    app_secret = getpass.getpass("Chave secreta do app (não aparece ao digitar): ").strip()
    token_curto = getpass.getpass("Token de usuário do Graph API Explorer (não aparece ao digitar): ").strip()
    if not (app_id and app_secret and token_curto):
        print("✗ Faltou algum dado.")
        return 1

    try:
        longo = http("GET", f"{GRAPH}/oauth/access_token", {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": token_curto,
        })["access_token"]

        app_token = f"{app_id}|{app_secret}"
        info = http("GET", f"{GRAPH}/debug_token", {"input_token": longo, "access_token": app_token})["data"]
        faltam = PERMISSOES - set(info.get("scopes", []))
        if faltam:
            print(f"✗ O token não tem estas permissões: {', '.join(sorted(faltam))}.")
            print("  Gere de novo no Graph API Explorer marcando todas (veja o LEIAME).")
            return 1

        paginas = http("GET", f"{GRAPH}/me/accounts", {
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "access_token": longo,
        }).get("data", [])
        paginas = [p for p in paginas if p.get("instagram_business_account")]
        if not paginas:
            print("✗ Nenhuma página com conta do Instagram ligada apareceu para este token.")
            print("  Ao gerar o token, autorize a página do Qlozy e a conta @qlozyapp.")
            return 1
        if len(paginas) == 1:
            pagina = paginas[0]
        else:
            for i, p in enumerate(paginas, 1):
                print(f"  {i}. {p['name']} (@{p['instagram_business_account'].get('username')})")
            pagina = paginas[int(input("Qual página? ")) - 1]

        ig = pagina["instagram_business_account"]
        info_pagina = http("GET", f"{GRAPH}/debug_token", {
            "input_token": pagina["access_token"], "access_token": app_token,
        })["data"]
        expira = info_pagina.get("expires_at", 0)
        print(f"\nPágina: {pagina['name']} ({pagina['id']})")
        print(f"Instagram: @{ig.get('username')} ({ig['id']})")
        print("Token da página: " + ("não expira ✓" if expira == 0 else f"expira em {expira} (timestamp) — refaça daqui a 60 dias"))
    except (ErroMeta, KeyError) as e:
        print(f"✗ {e}")
        return 1

    if input(f"\nGravar os segredos em {REPO}? [s/N] ").strip().lower() != "s":
        print("Nada gravado.")
        return 0
    gravar_segredo("META_PAGE_TOKEN", pagina["access_token"])
    gravar_segredo("META_PAGE_ID", pagina["id"])
    gravar_segredo("META_IG_ID", ig["id"])
    print("✓ Segredos gravados. Teste em GitHub > qlozy-midia-publica > Actions > Publicar > Run workflow > verificar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
