# Mídia pública do @qlozyapp

Peças **finais** de posts já liberados para publicação (imagens PNG e vídeos MP4), servidas por link raw público para o Metricool agendar.

- Só entra aqui o que o Renan moveu para **🟢 Liberado** no quadro "Qlozy Social". Quem copia é a tarefa `qlozy-publicar`.
- Sem briefing, roteiro, SVG-fonte, rascunho ou dado de cliente. Isso fica no repo privado `qlozy-social`.
- Estrutura: `posts/<AAAA-MM-DD>-<slug>/` com `01.png`, `02.png`… (imagem, carrossel, stories) ou `reel.mp4` + `capa.png` (reel).
- **Publicador próprio** (`publicador/`, `agenda/`, `.github/workflows/`): publica no Instagram e no Facebook pela API oficial da Meta, a partir dos arquivos em `agenda/`. Configuração e formato em [publicador/LEIAME.md](publicador/LEIAME.md). É o único código deste repositório e não guarda nenhuma chave: elas ficam nos segredos do GitHub.
- Link usado no Metricool: `https://raw.githubusercontent.com/qlozyapp/qlozy-midia-publica/main/posts/<pasta>/<arquivo>`.
