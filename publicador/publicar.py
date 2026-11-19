"""Publicador do @qlozyapp no Instagram e no Facebook pela API oficial da Meta.

Lê os arquivos de agenda em `agenda/*.json`, publica o que já passou do horário
e grava o resultado (id e link do post) no próprio arquivo, para nunca publicar
duas vezes. Roda no GitHub Actions a cada 10 minutos (.github/workflows/publicar.yml).

Comandos:
    python publicador/publicar.py publicar [--agora 2026-12-01T10:00:00-03:00] [--simular]
    python publicador/publicar.py validar      # confere todos os arquivos de agenda
    python publicador/publicar.py verificar    # confere token, página e conta do Instagram

Variáveis de ambiente (segredos do repositório):
    META_PAGE_TOKEN  token da página do Facebook (não expira; gerado por configurar_meta.py)
    META_PAGE_ID     id da página do Facebook
    META_IG_ID       id da conta profissional do Instagram ligada à página
    GRAPH_VERSION    versão da Graph API (padrão abaixo)
    MIDIA_BASE_URL   base dos links públicos das mídias (padrão: raw deste repositório)

Só usa a biblioteca padrão do Python.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _saida in (sys.stdout, sys.stderr):  # terminal do Windows (cp1252) não imprime ✓ nem acentos
    try:
        _saida.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

RAIZ = Path(__file__).resolve().parent.parent
AGENDA = RAIZ / "agenda"
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v24.0")
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}"
MIDIA_BASE_URL = os.environ.get(
    "MIDIA_BASE_URL", "https://raw.githubusercontent.com/qlozyapp/qlozy-midia-publica/main"
).rstrip("/")
SP = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem horário de verão desde 2019)

REDES = ("instagram", "facebook")
TIPOS = ("imagem", "carrossel", "reel", "story")
MAX_ATRASO = timedelta(hours=3)  # passou disso sem publicar: não publica, marca "vencido"
MAX_TENTATIVAS = 3
IMAGEM_IG = (".jpg", ".jpeg")  # a API do Instagram só aceita JPEG
VIDEO = (".mp4", ".mov")

# Intervalo entre consultas de status. Os testes zeram para rodar rápido.
ESPERA = 5.0


class ErroMeta(Exception):
    """Erro devolvido pela Graph API (ou de validação antes de chamar a API)."""


# --------------------------------------------------------------------- HTTP


def http(metodo: str, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
    """Chamada HTTP que devolve o JSON da resposta. Os testes trocam esta função."""
    dados = None
    if params:
        corpo = urllib.parse.urlencode(params)
        if metodo == "GET":
            url = f"{url}?{corpo}"
        else:
            dados = corpo.encode()
    req = urllib.request.Request(url, data=dados, method=metodo, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        texto = e.read().decode(errors="replace")
        try:
            erro = json.loads(texto).get("error", {})
            msg = erro.get("error_user_msg") or erro.get("message") or texto
            raise ErroMeta(f"HTTP {e.code}: {msg} (code {erro.get('code')}, subcode {erro.get('error_subcode')})") from None
        except (ValueError, AttributeError):
            raise ErroMeta(f"HTTP {e.code}: {texto[:300]}") from None


class Graph:
    def __init__(self, token: str):
        self.token = token

    def get(self, caminho: str, **params) -> dict:
        return http("GET", f"{GRAPH}/{caminho}", {**params, "access_token": self.token})

    def post(self, caminho: str, **params) -> dict:
        return http("POST", f"{GRAPH}/{caminho}", {**params, "access_token": self.token})


# ----------------------------------------------------------------- agenda


def url_midia(caminho: str) -> str:
    if caminho.startswith("http://") or caminho.startswith("https://"):
        return caminho
    return f"{MIDIA_BASE_URL}/{urllib.parse.quote(caminho.lstrip('/'))}"


def ler_quando(texto: str) -> datetime:
    quando = datetime.fromisoformat(texto)
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=SP)
    return quando


def validar_item(item: dict, conferir_arquivos: bool = True) -> list[str]:
    """Devolve a lista de problemas do arquivo de agenda (vazia = ok)."""
    erros = []
    if "quando" not in item:
        erros.append("falta 'quando'")
    else:
        try:
            ler_quando(item["quando"])
        except ValueError:
            erros.append(f"'quando' inválido: {item['quando']}")
    postagens = item.get("postagens")
    if not isinstance(postagens, list) or not postagens:
        return erros + ["falta 'postagens'"]
    vistas = set()
    for i, p in enumerate(postagens):
        rotulo = f"postagens[{i}]"
        rede, tipo, midias = p.get("rede"), p.get("tipo"), p.get("midias") or []
        if rede not in REDES:
            erros.append(f"{rotulo}: rede '{rede}' não suportada (use {', '.join(REDES)})")
            continue
        if rede in vistas:
            erros.append(f"{rotulo}: rede '{rede}' repetida")
        vistas.add(rede)
        if tipo not in TIPOS:
            erros.append(f"{rotulo}: tipo '{tipo}' não suportado (use {', '.join(TIPOS)})")
            continue
        if not midias:
            erros.append(f"{rotulo}: sem mídias")
            continue
        if tipo == "carrossel" and not 2 <= len(midias) <= 10:
            erros.append(f"{rotulo}: carrossel precisa de 2 a 10 imagens (tem {len(midias)})")
        if tipo in ("imagem", "story", "reel") and len(midias) != 1:
            erros.append(f"{rotulo}: {tipo} leva 1 mídia (tem {len(midias)})")
        for m in midias:
            ext = Path(m).suffix.lower()
            if tipo == "reel" and ext not in VIDEO:
                erros.append(f"{rotulo}: reel precisa de vídeo .mp4 ({m})")
            if tipo in ("imagem", "carrossel") and rede == "instagram" and ext not in IMAGEM_IG:
                erros.append(f"{rotulo}: o Instagram só aceita JPEG ({m})")
            if tipo == "story" and ext not in IMAGEM_IG + VIDEO:
                erros.append(f"{rotulo}: story precisa de .jpg ou .mp4 ({m})")
            if tipo == "story" and rede == "facebook" and ext in VIDEO:
                erros.append(f"{rotulo}: story em vídeo no Facebook não é suportado ({m})")
            if conferir_arquivos and not m.startswith("http") and not (RAIZ / m).is_file():
                erros.append(f"{rotulo}: arquivo não existe no repositório ({m})")
        legenda = p.get("legenda", "")
        if tipo == "story" and legenda:
            erros.append(f"{rotulo}: story não tem legenda")
        if len(legenda) > 2200:
            erros.append(f"{rotulo}: legenda com {len(legenda)} caracteres (máx. 2200)")
        if rede == "instagram" and legenda.count("#") > 30:
            erros.append(f"{rotulo}: mais de 30 hashtags")
    return erros


def carregar_agenda() -> list[tuple[Path, dict]]:
    if not AGENDA.is_dir():
        return []
    itens = []
    for arq in sorted(AGENDA.glob("*.json")):
        itens.append((arq, json.loads(arq.read_text(encoding="utf-8"))))
    return itens


def salvar(arq: Path, item: dict) -> None:
    arq.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# -------------------------------------------------------------- Instagram


def ig_esperar(g: Graph, container: str, limite_s: float) -> None:
    fim = time.monotonic() + limite_s
    while True:
        st = g.get(container, fields="status_code,status")
        codigo = st.get("status_code")
        if codigo in ("FINISHED", "PUBLISHED"):
            return
        if codigo in ("ERROR", "EXPIRED"):
            raise ErroMeta(f"o Instagram recusou a mídia: {st.get('status') or codigo}")
        if time.monotonic() >= fim:
            raise ErroMeta(f"o Instagram não terminou de processar a mídia em {int(limite_s)} s (status {codigo})")
        time.sleep(ESPERA)


def ig_ja_publicado(g: Graph, ig_id: str, legenda: str) -> dict | None:
    """Evita duplicar: procura nas últimas mídias um post com a mesma legenda."""
    if not legenda.strip():
        return None
    recentes = g.get(f"{ig_id}/media", fields="id,caption,permalink,timestamp", limit=15).get("data", [])
    for m in recentes:
        if (m.get("caption") or "").strip() == legenda.strip():
            return {"id": m["id"], "link": m.get("permalink")}
    return None


def publicar_instagram(g: Graph, ig_id: str, p: dict) -> dict:
    tipo, legenda = p["tipo"], p.get("legenda", "")
    urls = [url_midia(m) for m in p["midias"]]

    existente = ig_ja_publicado(g, ig_id, legenda) if tipo != "story" else None
    if existente:
        return {**existente, "obs": "já estava no ar (mesma legenda); não publiquei de novo"}

    if tipo == "imagem":
        container = g.post(f"{ig_id}/media", image_url=urls[0], caption=legenda)["id"]
        ig_esperar(g, container, 120)
    elif tipo == "carrossel":
        filhos = []
        for u in urls:
            filho = g.post(f"{ig_id}/media", image_url=u, is_carousel_item="true")["id"]
            ig_esperar(g, filho, 120)
            filhos.append(filho)
        container = g.post(f"{ig_id}/media", media_type="CAROUSEL", children=",".join(filhos), caption=legenda)["id"]
        ig_esperar(g, container, 120)
    elif tipo == "reel":
        params = {"media_type": "REELS", "video_url": urls[0], "caption": legenda, "share_to_feed": "true"}
        if p.get("capa"):
            params["cover_url"] = url_midia(p["capa"])
        container = g.post(f"{ig_id}/media", **params)["id"]
        ig_esperar(g, container, 600)
    elif tipo == "story":
        chave = "video_url" if Path(p["midias"][0]).suffix.lower() in VIDEO else "image_url"
        container = g.post(f"{ig_id}/media", media_type="STORIES", **{chave: urls[0]})["id"]
        ig_esperar(g, container, 600 if chave == "video_url" else 120)
    else:
        raise ErroMeta(f"tipo não suportado: {tipo}")

    midia_id = g.post(f"{ig_id}/media_publish", creation_id=container)["id"]
    link = g.get(midia_id, fields="permalink").get("permalink")
    return {"id": midia_id, "link": link}


# --------------------------------------------------------------- Facebook


def fb_link(g: Graph, objeto: str) -> str | None:
    link = g.get(objeto, fields="permalink_url").get("permalink_url")
    if link and link.startswith("/"):
        link = "https://www.facebook.com" + link
    return link


def fb_ja_publicado(g: Graph, page_id: str, legenda: str) -> dict | None:
    if not legenda.strip():
        return None
    recentes = g.get(f"{page_id}/posts", fields="id,message,permalink_url", limit=15).get("data", [])
    for m in recentes:
        if (m.get("message") or "").strip() == legenda.strip():
            return {"id": m["id"], "link": m.get("permalink_url")}
    return None


def publicar_facebook(g: Graph, page_id: str, p: dict) -> dict:
    tipo, legenda = p["tipo"], p.get("legenda", "")
    urls = [url_midia(m) for m in p["midias"]]

    existente = fb_ja_publicado(g, page_id, legenda) if tipo in ("imagem", "carrossel") else None
    if existente:
        return {**existente, "obs": "já estava no ar (mesmo texto); não publiquei de novo"}

    if tipo == "imagem":
        r = g.post(f"{page_id}/photos", url=urls[0], message=legenda, published="true")
        post_id = r.get("post_id") or r["id"]
        return {"id": post_id, "link": fb_link(g, post_id)}
    if tipo == "carrossel":
        fotos = [g.post(f"{page_id}/photos", url=u, published="false")["id"] for u in urls]
        params = {"message": legenda}
        for i, f in enumerate(fotos):
            params[f"attached_media[{i}]"] = json.dumps({"media_fbid": f})
        post_id = g.post(f"{page_id}/feed", **params)["id"]
        return {"id": post_id, "link": fb_link(g, post_id)}
    if tipo == "story":
        foto = g.post(f"{page_id}/photos", url=urls[0], published="false")["id"]
        r = g.post(f"{page_id}/photo_stories", photo_id=foto)
        return {"id": r.get("post_id") or foto, "link": None}
    if tipo == "reel":
        inicio = g.post(f"{page_id}/video_reels", upload_phase="start")
        video_id = inicio["video_id"]
        envio = http(
            "POST",
            inicio.get("upload_url") or f"{RUPLOAD}/{video_id}",
            headers={"Authorization": f"OAuth {g.token}", "file_url": urls[0]},
        )
        if not envio.get("success", True):
            raise ErroMeta(f"o Facebook não aceitou o vídeo: {envio}")
        g.post(
            f"{page_id}/video_reels",
            upload_phase="finish",
            video_id=video_id,
            video_state="PUBLISHED",
            description=legenda,
        )
        fim = time.monotonic() + 600
        while True:
            st = g.get(video_id, fields="status").get("status", {})
            if st.get("video_status") == "error" or (st.get("processing_phase") or {}).get("status") == "error":
                raise ErroMeta(f"o Facebook recusou o reel: {st}")
            if (st.get("publishing_phase") or {}).get("status") == "complete" or st.get("video_status") == "ready":
                break
            if time.monotonic() >= fim:
                raise ErroMeta(f"o Facebook não terminou de processar o reel em 600 s: {st}")
            time.sleep(ESPERA)
        return {"id": video_id, "link": fb_link(g, video_id)}
    raise ErroMeta(f"tipo não suportado: {tipo}")


# ---------------------------------------------------------------- comandos


def credenciais() -> tuple[str, str, str]:
    faltando = [v for v in ("META_PAGE_TOKEN", "META_PAGE_ID", "META_IG_ID") if not os.environ.get(v)]
    if faltando:
        raise ErroMeta(f"faltam os segredos {', '.join(faltando)} (veja publicador/LEIAME.md)")
    return os.environ["META_PAGE_TOKEN"], os.environ["META_PAGE_ID"], os.environ["META_IG_ID"]


def agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_publicar(agora: datetime, simular: bool = False) -> int:
    """Publica o que venceu. Devolve 1 se algo deu erro (o workflow fica vermelho e o GitHub avisa por e-mail)."""
    houve_erro = False
    graph = page_id = ig_id = None
    for arq, item in carregar_agenda():
        problemas = validar_item(item)
        resultado = item.setdefault("resultado", {})
        if problemas:
            print(f"✗ {arq.name}: arquivo inválido: {'; '.join(problemas)}")
            houve_erro = True
            continue
        quando = ler_quando(item["quando"])
        if quando > agora:
            continue
        mudou = False
        for p in item["postagens"]:
            rede = p["rede"]
            estado = resultado.get(rede, {})
            if estado.get("status") in ("publicado", "vencido", "desistiu"):
                continue
            if agora - quando > MAX_ATRASO and estado.get("status") != "erro":
                resultado[rede] = {"status": "vencido", "em": agora_utc(),
                                   "obs": f"passou mais de {MAX_ATRASO} do horário sem publicar; publique pelo celular"}
                print(f"! {arq.name} [{rede}]: vencido, não publiquei")
                houve_erro = mudou = True
                continue
            if simular:
                print(f"~ {arq.name} [{rede}]: publicaria {p['tipo']} com {len(p['midias'])} mídia(s)")
                continue
            try:
                if graph is None:
                    token, page_id, ig_id = credenciais()
                    graph = Graph(token)
                if rede == "instagram":
                    r = publicar_instagram(graph, ig_id, p)
                else:
                    r = publicar_facebook(graph, page_id, p)
                resultado[rede] = {"status": "publicado", "em": agora_utc(), **r}
                print(f"✓ {arq.name} [{rede}]: {r.get('link') or r.get('id')}")
            except ErroMeta as e:
                tentativas = estado.get("tentativas", 0) + 1
                resultado[rede] = {
                    "status": "erro" if tentativas < MAX_TENTATIVAS else "desistiu",
                    "erro": str(e), "tentativas": tentativas, "em": agora_utc(),
                }
                print(f"✗ {arq.name} [{rede}]: {e} (tentativa {tentativas})")
                houve_erro = True
            mudou = True
            salvar(arq, item)  # grava a cada rede: se o job cair, não republica a anterior
        if mudou:
            salvar(arq, item)
    return 1 if houve_erro else 0


def cmd_validar() -> int:
    ruins = 0
    itens = carregar_agenda()
    for arq, item in itens:
        problemas = validar_item(item)
        if problemas:
            ruins += 1
            print(f"✗ {arq.name}: {'; '.join(problemas)}")
        else:
            print(f"✓ {arq.name}")
    print(f"{len(itens)} arquivo(s), {ruins} com problema")
    return 1 if ruins else 0


def cmd_verificar() -> int:
    token, page_id, ig_id = credenciais()
    g = Graph(token)
    pagina = g.get(page_id, fields="name,instagram_business_account")
    ig = g.get(ig_id, fields="username")
    limite = g.get(f"{ig_id}/content_publishing_limit", fields="quota_usage,config").get("data", [{}])[0]
    ligada = (pagina.get("instagram_business_account") or {}).get("id") == ig_id
    print(f"Página do Facebook: {pagina.get('name')} ({page_id})")
    print(f"Instagram: @{ig.get('username')} ({ig_id}) {'ligado à página' if ligada else '— NÃO está ligado a esta página'}")
    print(f"Posts pela API nas últimas 24 h: {limite.get('quota_usage')} de {(limite.get('config') or {}).get('quota_total')}")
    return 0 if ligada else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=("publicar", "validar", "verificar"), nargs="?", default="publicar")
    ap.add_argument("--agora", help="data/hora ISO para simular o relógio (padrão: agora)")
    ap.add_argument("--simular", action="store_true", help="não chama a API, só mostra o que publicaria")
    a = ap.parse_args(argv)
    try:
        if a.comando == "validar":
            return cmd_validar()
        if a.comando == "verificar":
            return cmd_verificar()
        agora = ler_quando(a.agora) if a.agora else datetime.now(timezone.utc)
        return cmd_publicar(agora, simular=a.simular)
    except ErroMeta as e:
        print(f"✗ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
