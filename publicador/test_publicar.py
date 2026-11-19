"""Testes do publicador com a Graph API simulada (nada sai para a internet)."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import publicar as pub

AGORA = datetime.fromisoformat("2026-12-01T10:05:00-03:00")


class GraphFalsa:
    """Responde como a Graph API e registra cada chamada."""

    def __init__(self, recentes_ig=None, recentes_fb=None, status_ig="FINISHED", falhar_em=None):
        self.chamadas = []
        self.recentes_ig = recentes_ig or []
        self.recentes_fb = recentes_fb or []
        self.status_ig = status_ig
        self.falhar_em = falhar_em
        self.n = 0

    def __call__(self, metodo, url, params=None, headers=None):
        params = dict(params or {})
        params.pop("access_token", None)
        caminho = url.split(f"/{pub.GRAPH_VERSION}/", 1)[-1]
        self.chamadas.append((metodo, caminho, params, headers))
        if self.falhar_em and self.falhar_em in caminho:
            raise pub.ErroMeta("HTTP 400: falha simulada")
        self.n += 1
        if metodo == "GET":
            if caminho.endswith("/media") and params.get("fields", "").startswith("id,caption"):
                return {"data": self.recentes_ig}
            if caminho.endswith("/posts"):
                return {"data": self.recentes_fb}
            if params.get("fields") == "status_code,status":
                return {"status_code": self.status_ig}
            if params.get("fields") == "permalink":
                return {"permalink": f"https://www.instagram.com/p/{caminho}/"}
            if params.get("fields") == "permalink_url":
                return {"permalink_url": f"/qlozy/posts/{caminho}"}
            if params.get("fields") == "status":
                return {"status": {"video_status": "ready", "publishing_phase": {"status": "complete"}}}
            return {}
        if caminho.endswith("/video_reels") and params.get("upload_phase") == "start":
            return {"video_id": "v1", "upload_url": "https://rupload.facebook.com/video-upload/x/v1"}
        if "rupload" in url:
            return {"success": True}
        if caminho.endswith("/photos"):
            return {"id": f"foto{self.n}", "post_id": f"pg_{self.n}"}
        return {"id": f"id{self.n}"}

    def caminhos(self, metodo="POST"):
        return [c[1] for c in self.chamadas if c[0] == metodo]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "agenda").mkdir()
        (self.tmp / "posts/x").mkdir(parents=True)
        for f in ("01.jpg", "02.jpg", "01.png", "reel.mp4", "capa.jpg"):
            (self.tmp / "posts/x" / f).write_bytes(b"x")
        self.patches = [
            mock.patch.object(pub, "RAIZ", self.tmp),
            mock.patch.object(pub, "AGENDA", self.tmp / "agenda"),
            mock.patch.object(pub, "ESPERA", 0),
            mock.patch.dict(os.environ, {"META_PAGE_TOKEN": "tok", "META_PAGE_ID": "PAGE", "META_IG_ID": "IG"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def agenda(self, nome, item):
        arq = self.tmp / "agenda" / nome
        arq.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        return arq

    def ler(self, arq):
        return json.loads(arq.read_text(encoding="utf-8"))

    def rodar(self, graph, agora=AGORA):
        with mock.patch.object(pub, "http", graph):
            return pub.cmd_publicar(agora)


CARROSSEL = {
    "issue": 3,
    "quando": "2026-12-01T10:00:00-03:00",
    "postagens": [
        {"rede": "instagram", "tipo": "carrossel", "midias": ["posts/x/01.jpg", "posts/x/02.jpg"], "legenda": "Legenda IG #qlozy"},
        {"rede": "facebook", "tipo": "carrossel", "midias": ["posts/x/01.jpg", "posts/x/02.jpg"], "legenda": "Texto FB"},
    ],
}


class TestValidacao(Base):
    def test_carrossel_valido(self):
        self.assertEqual(pub.validar_item(CARROSSEL), [])

    def test_png_no_instagram_e_recusado(self):
        item = {"quando": "2026-12-01T10:00", "postagens": [
            {"rede": "instagram", "tipo": "imagem", "midias": ["posts/x/01.png"], "legenda": "a"}]}
        self.assertTrue(any("JPEG" in e for e in pub.validar_item(item)))

    def test_arquivo_inexistente_rede_e_tipo(self):
        item = {"quando": "2026-12-01T10:00", "postagens": [
            {"rede": "tiktok", "tipo": "imagem", "midias": ["a.jpg"]},
            {"rede": "instagram", "tipo": "imagem", "midias": ["posts/x/nao.jpg"], "legenda": "a"},
            {"rede": "facebook", "tipo": "gif", "midias": ["posts/x/01.jpg"]}]}
        erros = " | ".join(pub.validar_item(item))
        self.assertIn("tiktok", erros)
        self.assertIn("não existe", erros)
        self.assertIn("gif", erros)

    def test_story_sem_legenda_e_carrossel_com_limite(self):
        item = {"quando": "2026-12-01T10:00", "postagens": [
            {"rede": "instagram", "tipo": "story", "midias": ["posts/x/01.jpg"], "legenda": "não pode"},
            {"rede": "facebook", "tipo": "carrossel", "midias": ["posts/x/01.jpg"]}]}
        erros = " | ".join(pub.validar_item(item))
        self.assertIn("story não tem legenda", erros)
        self.assertIn("2 a 10", erros)

    def test_hora_sem_fuso_vale_sao_paulo(self):
        self.assertEqual(pub.ler_quando("2026-12-01T10:00").utcoffset().total_seconds(), -3 * 3600)


class TestPublicacao(Base):
    def test_carrossel_instagram_e_facebook(self):
        arq = self.agenda("a.json", CARROSSEL)
        g = GraphFalsa()
        self.assertEqual(self.rodar(g), 0)
        res = self.ler(arq)["resultado"]
        self.assertEqual(res["instagram"]["status"], "publicado")
        self.assertTrue(res["instagram"]["link"].startswith("https://www.instagram.com/p/"))
        self.assertEqual(res["facebook"]["status"], "publicado")
        self.assertTrue(res["facebook"]["link"].startswith("https://www.facebook.com/"))
        posts = g.caminhos()
        # 2 filhos + container + publish no IG; 2 fotos não publicadas + feed no FB
        self.assertEqual(posts.count("IG/media"), 3)
        self.assertIn("IG/media_publish", posts)
        self.assertEqual(posts.count("PAGE/photos"), 2)
        self.assertIn("PAGE/feed", posts)
        feed = next(c[2] for c in g.chamadas if c[1] == "PAGE/feed")
        self.assertEqual(feed["message"], "Texto FB")
        fotos = [k for k in feed if k.startswith("attached_media[")]
        self.assertEqual(len(fotos), 2)
        self.assertIn("media_fbid", json.loads(feed["attached_media[0]"]))
        container = next(c[2] for c in g.chamadas if c[2].get("media_type") == "CAROUSEL")
        self.assertEqual(container["caption"], "Legenda IG #qlozy")
        self.assertTrue(container["children"].count(",") == 1)

    def test_nao_publica_antes_da_hora(self):
        arq = self.agenda("a.json", {**CARROSSEL, "quando": "2026-12-01T11:00:00-03:00"})
        g = GraphFalsa()
        self.assertEqual(self.rodar(g), 0)
        self.assertEqual(g.chamadas, [])
        self.assertNotIn("instagram", self.ler(arq).get("resultado", {}))

    def test_nao_publica_de_novo(self):
        arq = self.agenda("a.json", CARROSSEL)
        self.rodar(GraphFalsa())
        g = GraphFalsa()
        self.assertEqual(self.rodar(g), 0)
        self.assertEqual(g.chamadas, [])
        self.assertEqual(self.ler(arq)["resultado"]["instagram"]["status"], "publicado")

    def test_mesma_legenda_ja_no_ar_nao_duplica(self):
        arq = self.agenda("a.json", CARROSSEL)
        g = GraphFalsa(recentes_ig=[{"id": "m9", "caption": "Legenda IG #qlozy", "permalink": "https://www.instagram.com/p/m9/"}])
        self.rodar(g)
        res = self.ler(arq)["resultado"]["instagram"]
        self.assertEqual(res["id"], "m9")
        self.assertIn("já estava no ar", res["obs"])
        self.assertNotIn("IG/media_publish", g.caminhos())

    def test_atrasado_demais_vira_vencido(self):
        arq = self.agenda("a.json", CARROSSEL)
        g = GraphFalsa()
        self.assertEqual(self.rodar(g, agora=datetime.fromisoformat("2026-12-01T14:00:00-03:00")), 1)
        self.assertEqual(g.chamadas, [])
        self.assertEqual(self.ler(arq)["resultado"]["instagram"]["status"], "vencido")

    def test_erro_tenta_de_novo_e_desiste_na_terceira(self):
        arq = self.agenda("a.json", {**CARROSSEL, "postagens": CARROSSEL["postagens"][:1]})
        for esperado in ("erro", "erro", "desistiu"):
            self.assertEqual(self.rodar(GraphFalsa(falhar_em="media_publish")), 1)
            self.assertEqual(self.ler(arq)["resultado"]["instagram"]["status"], esperado)
        g = GraphFalsa()
        self.rodar(g)
        self.assertEqual(g.chamadas, [])

    def test_erro_numa_rede_nao_impede_a_outra(self):
        arq = self.agenda("a.json", CARROSSEL)
        self.assertEqual(self.rodar(GraphFalsa(falhar_em="media_publish")), 1)
        res = self.ler(arq)["resultado"]
        self.assertEqual(res["instagram"]["status"], "erro")
        self.assertEqual(res["facebook"]["status"], "publicado")

    def test_midia_recusada_pelo_instagram(self):
        arq = self.agenda("a.json", {**CARROSSEL, "postagens": CARROSSEL["postagens"][:1]})
        self.rodar(GraphFalsa(status_ig="ERROR"))
        self.assertIn("recusou", self.ler(arq)["resultado"]["instagram"]["erro"])

    def test_reel_nas_duas_redes(self):
        arq = self.agenda("r.json", {"quando": "2026-12-01T10:00", "postagens": [
            {"rede": "instagram", "tipo": "reel", "midias": ["posts/x/reel.mp4"], "capa": "posts/x/capa.jpg", "legenda": "Reel"},
            {"rede": "facebook", "tipo": "reel", "midias": ["posts/x/reel.mp4"], "legenda": "Reel FB"}]})
        g = GraphFalsa()
        self.assertEqual(self.rodar(g), 0)
        ig = next(c[2] for c in g.chamadas if c[2].get("media_type") == "REELS")
        self.assertTrue(ig["video_url"].endswith("/posts/x/reel.mp4"))
        self.assertTrue(ig["cover_url"].endswith("/posts/x/capa.jpg"))
        envio = next(c for c in g.chamadas if "rupload" in c[1])
        self.assertTrue(envio[3]["file_url"].endswith("/posts/x/reel.mp4"))
        fim = next(c[2] for c in g.chamadas if c[2].get("upload_phase") == "finish")
        self.assertEqual(fim["description"], "Reel FB")
        res = self.ler(arq)["resultado"]
        self.assertEqual({res["instagram"]["status"], res["facebook"]["status"]}, {"publicado"})

    def test_story_nas_duas_redes(self):
        arq = self.agenda("s.json", {"quando": "2026-12-01T10:00", "postagens": [
            {"rede": "instagram", "tipo": "story", "midias": ["posts/x/01.jpg"]},
            {"rede": "facebook", "tipo": "story", "midias": ["posts/x/01.jpg"]}]})
        g = GraphFalsa()
        self.assertEqual(self.rodar(g), 0)
        self.assertTrue(any(c[2].get("media_type") == "STORIES" for c in g.chamadas))
        self.assertIn("PAGE/photo_stories", g.caminhos())
        self.assertEqual(self.ler(arq)["resultado"]["facebook"]["status"], "publicado")

    def test_sem_segredos_so_falha_se_houver_algo_vencido(self):
        with mock.patch.dict(os.environ, {"META_PAGE_TOKEN": ""}):
            self.assertEqual(self.rodar(GraphFalsa()), 0)  # agenda vazia
            arq = self.agenda("a.json", CARROSSEL)
            self.assertEqual(self.rodar(GraphFalsa()), 1)
            self.assertIn("META_PAGE_TOKEN", self.ler(arq)["resultado"]["instagram"]["erro"])

    def test_arquivo_invalido_nao_publica(self):
        self.agenda("ruim.json", {"quando": "2026-12-01T10:00", "postagens": [
            {"rede": "instagram", "tipo": "imagem", "midias": ["posts/x/01.png"], "legenda": "a"}]})
        g = GraphFalsa()
        self.assertEqual(self.rodar(g), 1)
        self.assertEqual(g.chamadas, [])


if __name__ == "__main__":
    unittest.main()
