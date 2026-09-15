# Backlog — fusão multicâmera (sala real)

**Status:** ausente / P3 · registrado 2026-09-14 (conversa LIVE TRI)  
**Não confundir com:** N câmeras em paralelo no `config.yaml` (já existe — pipelines **independentes**).

Hoje: multi-câmera = N streams separados.  
Falta: **multi-visão fundida** (cams “conversam”; melhor ângulo vence sem perder sinais).

---

## Problema de produto (fileiras + círculo)

- Fileiras de frente ao quadro e mesas em círculo **sempre** geram costas, perfil e oclusão.
- Uma câmera não cobre a sala.
- Exemplo-alvo: aluno de **costas** na cam A e de **frente com celular** na cam B → o alerta que vale é o da cam B (melhor evidência), sem duplicar nem perder o episódio.

---

## Camada de fusão a construir (ordem sugerida)

1. **Identidade global estável** — mesmo `student_id` em cam A e cam B (face quando houver + continuidade; mapa de assentos ajuda costas/costas).
2. **Score de observabilidade** por `(aluno, câmera)` — frontalidade, rosto visível, qualidade.
3. **Árbitro por tipo de sinal** — celular/expressão preferem vista frontal; presença pode usar qualquer cam.
4. **Deduplicar alertas** — um episódio por aluno/sala (não 2× “celular na mão”).
5. **UI com fonte** — card mostra `evidence_camera_id` (ex.: “evidência da cam-quadro”).

Também necessário no caminho: live state unificado (não last-write-wins), track IDs namespaced por `camera_id`, calibração/placement (não só software).

---

## Base que já existe (não reinventar)

- N cameras em `config.yaml` + orchestrator por `camera_id`
- Galeria FaceNet / `student_id`
- `observation_quality`, pose, phone, drowsiness **por track**
- Dashboard de turma (`/dashboard`) para multi-pessoa **num feed**
- Docs: `MODULAR_CLASSROOM_SCENARIOS.md` (fusão ausente), `ROADMAP.md` (P3)

## Explicitamente NÃO feito

- Re-ID / binding cross-camera
- Escolha da câmera com melhor observabilidade
- Merge de eventos entre cams
- Playbook de layout fileiras vs círculo + posicionamento de cams

---

## Relação com o TRI atual

O TRI mono-câmera (sinais calibrados F/G/H/J/K/celular) **continua válido**: a fusão **consome** esses sinais; não os substitui.  
Não abrir fusão multicâmera sem TRI 1-cam estável na matriz manual restante.
