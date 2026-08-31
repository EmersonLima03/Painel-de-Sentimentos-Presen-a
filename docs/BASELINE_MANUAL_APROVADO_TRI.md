# Baseline manual aprovado — TRI (visão)

> **CONGELADO** — branch `tri/congelado-baseline-validado` · ver [`TRI_CONGELADO.md`](TRI_CONGELADO.md)  
> **Regra:** cenários ✅ abaixo **não podem regredir**. Não editar áreas sensíveis sem reteste manual.

Documento **fixo** para consultar **antes** de editar oclusão, celular, sono, atenção, expressão ou cabeça baixa.  
Se uma mudança quebrar o comportamento abaixo, **revalidar na webcam** antes de considerar ok.

**Disclaimer:** estimativas visuais; sem diagnóstico.  
**TRI:** ainda aberto (matriz incompleta). Só cenários listados como ✅ estão travados por validação humana.

**Última sessão de aprovação humana:** 2026-08-03 — Emerson Lima (`/debug/vision`, RTSP local).

---

## Como usar este arquivo

1. Antes de mexer nos arquivos sensíveis da seção afetada → ler o cenário ✅.  
2. Depois da edição → reexecutar o cenário ✅ e os testes automáticos citados.  
3. Ao aprovar um novo cenário manual → acrescentar aqui **e** marcar a matriz em `docs/VALIDACAO_FINAL_CENARIOS_TRI.md`.  
4. **Nunca** “melhorar” um cenário ✅ sem reteste manual: oclusão, celular/garrafa, sono, atenção baixa persistente, expressão positiva/neutra, **cabeça baixa (H)**.

---

## Contrato — não quebrar (resumo)

| Área | ✅ Travado | Proibido regressar para |
|------|------------|-------------------------|
| Oclusão 1/2 mãos (J/K) | Evento “Rosto coberto / não observável” estável; attn/sono inconclusivos | Sem evento; fragmentação; sono inventado |
| Celular vs garrafa (B) | Garrafa **não** vira interação/celular na mão | FP bbox + “Celular na mão” em garrafa |
| Celular real (D) | Detecção / progressão útil com celular real | FN sistemático com celular real na mão |
| Olhos fechados (G) | Possible/probable nos limiares 6s/30s | Eventos &lt;2.5s; FP de sono ao digitar |
| Atenção baixa persistente | Evento / sinal de baixa atenção persistente quando aplicável | Sumir o evento ou confundir com sono |
| Expressão +/neutra (EX) | Sorriso sustentado → positiva; sessão com tempos +/neutra coherentes | Sorriso longo sempre neutro (`smile_boost` off) |
| Cabeça baixa (H) | Evento + card “prolongada” com duração ≈ tempo real; 1 episódio contínuo | 0s / sem evento; banner 2s após 40s; card inconclusivo com evento aberto; peito→oclusão falsa |
| Expressão negativa | **Ainda NÃO aprovado** — ver débitos | — |

---

## Cenários aprovados (webcam)

### J — Uma mão no rosto ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-07-30; **revalidado 2026-08-03** (“Rosto coberto / não observável está ótimo”) |
| Testador | Emerson Lima |
| Câmera / UI | `/debug/vision`, RTSP local |
| Esperado | Evento “Rosto coberto / não observável”; oclusão persistente; atenção e sonolência **inconclusivas**; identidade por continuidade |
| Obtido | Aprovado — evento estável; sem sono; continuidade OK |
| Proibido que volte | Sem evento com 1 mão; “Sem oclusão facial” com mão cobrindo; sono/atenção baixa inventados |
| Arquivos sensíveis | `app/vision/body_pose.py`, `app/pipeline/analytics_track.py` (hold oclusão), `app/pipeline/occlusion_head_arbitration.py`, `app/static/debug_vision.html` |
| Testes de regressão | `tests/test_occlusion_continuity.py`, `tests/test_occlusion_hysteresis.py`, `tests/test_head_down_visibility_gate.py` |
| Params | `face_occlusion.clear_hold_seconds` (4), `face_missing_hold_seconds` (15), `persistent_seconds` (5), `confirm_seconds` (0.7) |

### K — Duas mãos no rosto ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-07-30; revalidado junto com oclusão em 2026-08-03 |
| Esperado | Oclusão persistente contínua; atenção/sono inconclusivos; sem head_down automático por oclusão |
| Obtido | Aprovado |
| Proibido que volte | Evento abrindo/fechando várias vezes; relatório só com pedaços |
| Arquivos / testes / params | Idem J — `face_missing_hold_seconds` evita fragmentação |

### B — Garrafa / objeto NÃO-celular ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-08-03 |
| Testador | Emerson Lima |
| Esperado | Garrafa na mão **não** gera interação celular / “Celular na mão” |
| Obtido | Aprovado — “coloquei a garrafa e ele não detectou, certo” |
| Proibido que volte | FP YOLO + card de uso de celular em garrafa/térmico |
| Arquivos sensíveis | `app/vision/phone_yolo.py`, `app/vision/person_phone.py` (associação/rejeição), filtros `bottle_like` / `keep_vertical_phone`, UI timer só em in_hand/interação |
| Testes | `tests/test_phone_false_positive_regression.py`, `tests/test_phone_filters.py`, `tests/test_phone_table_interaction.py` |
| Nota | Controles positivos P1–P5 (celular real) não podem regredir ao endurecer rejeição de garrafa |

### D — Celular real (detecção geral) ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-08-03 |
| Esperado | Celular real detectável / progressão útil; sem `confirmed_*` automático indevido |
| Obtido | Aprovado — “detecção de celular está ótimo” |
| Proibido que volte | FN sistemático; ou confirmed automático sem revisão |
| Arquivos / testes | Idem B + `tests/test_phone_positive_controls.py` |
| Params tipicos | `phone_possible_after` 5s / `probable` 12s; hold fechamento celular ~12s |

### G — Olhos fechados (sonolência aparente) ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-08-03 |
| Esperado | Possible ~6s / probable ~30s com olhos fechados frontais; **não** sono ao digitar |
| Obtido | Aprovado — “olhos fechados está ótimo” |
| Proibido que volte | Eventos &lt;2.5s; digitação→sono; sono afirmado com rosto ocluído |
| Arquivos sensíveis | `app/pipeline/analytics_track.py` (drowsiness / `eyes_observable`), limiares em `config.yaml` → `drowsiness` |
| Testes | `tests/test_typing_not_drowsiness.py` |
| Params | `possible_after_seconds` 6, `probable_after_seconds` 30, EAR ~0.18 |

### ATTN — Baixa atenção visual persistente ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-08-03 |
| Esperado | Sinal/evento de baixa atenção visual **persistente** quando o olhar/atenção permanece baixa de forma sustentada (sem inventar sono) |
| Obtido | Aprovado — “baixa atenção visual persistente está ótima” |
| Proibido que volte | Evento some; ou baixa atenção vira sonolência automática |
| Arquivos sensíveis | agregação de atenção em `analytics_track` / live session / UI eventos ao vivo e relatório |
| Nota | Distinguir de cabeça baixa (H) e de oclusão (J/K → atenção **inconclusiva**, não “baixa”) |

### EX+ / EX= — Expressão aparente positiva e neutra ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-08-03 |
| Esperado | Sorriso sustentado → **predominantemente positiva**; cara séria → neutra; relatório com tempos coerentes ao longo da sessão |
| Obtido | Aprovado — ex.: Positiva **16 min 56s** / Neutra **20 min 59s** na sessão; “está ótima também” |
| Proibido que volte | Sorriso longo sempre neutro; `smile_boost_enabled: false` no perfil TRI sem reteste |
| Arquivos sensíveis | `config.tri.yaml` (`smile_boost_enabled: true`, `provider: fer_onnx`), `app/pipeline/analytics_track.py` (`_compute_expression`), `app/vision/emotion_engagement.py` (heurística sorriso), providers em `app/vision/expressions/` |
| Params TRI | `expression.smile_boost_enabled: true`, `minimum_confidence_positive` ~0.50, janela ~8s |
| Doc relacionada | `docs/TROUBLESHOOTING.md` → “Sorriso aparece como expressão neutra” |

### H — Cabeça baixa (ângulo extremo / leitura) ✅

| Campo | Valor |
|-------|--------|
| Data | **2026-08-03 ~10:31 e ~10:34** (aprovação humana; pós-fix continuidade) |
| Testador | Emerson Lima |
| Câmera / UI | `/debug/vision`, RTSP local |
| Print 1 (~10:31) | Cabeça baixa clara; evento **“Cabeça baixa prolongada · 37 s”**; card Cabeça **igual** + “Duração contínua: 37 s”; rosto sumido ~39 s; atenção baixa; sono/expressão inconclusivos. Testador: “resultado incrível” |
| Print 2 (~10:34) | Idem; evento **· 14 s**; card **prolongada · 14 s** contínuos. Testador: “também” incrível |
| Esperado | ≥8 s → `head_down_short` → `head_down_persistent`; evento ao vivo; card alinhado; duração ≈ tempo real; **não** sono; **não** oclusão por mão (J/K) |
| Obtido | Aprovado — continuidade ok; peito não mata head_down |
| Proibido que volte | Sem evento; relatório 0s; banner com poucos segundos após dezenas de segundos reais; card “Postura inconclusiva” com evento aberto; punho no peito forçando oclusão e apagando head_down; head_down sob mão no rosto (J/K) |
| Arquivos sensíveis | `app/vision/body_pose.py` (zona ombros / `shoulders_without_face_look_down`), `app/pipeline/occlusion_head_arbitration.py` (não inventar oclusão por peito), `app/pipeline/analytics_track.py` (`_tick_head_down_duration`, `_head_state_for_track`, `started_at`=`head_down_since`, clear-hold 12s), `app/static/debug_vision.html` (card duração) |
| Params | `head_down.event_min_seconds` / `short_to_persistent` **8**; `inconclusive_hold_seconds` **12**; `suppress_when_occlusion` true só com mão **acima dos ombros**; `allow_face_missing_proxy` false |
| Testes de regressão | `tests/test_head_down_visibility_gate.py`, `tests/test_head_down_accumulator.py`, `tests/test_occlusion_hysteresis.py` (oclusão ainda ganha de head_down), `tests/test_occlusion_continuity.py` (J/K) |

---

## Débitos abertos / em calibração

### EX− — Expressão negativa (contrato 2026-08-03 — revalidar)

| Campo | Valor |
|-------|--------|
| Mapeamento | sad/angry/fear/disgust/contempt → `negative`; **surprise descartada** (sem bucket “Mista/surpresa”) |
| Limiares TRI | `minimum_confidence_negative: 0.42`; ≥2 amostras; `frown_boost_enabled: true` (bico/cantos caídos — FER+ marca como neutra ~75%) |
| Sorriso | smile_boost → `predominantly_positive` **sem** passar por inconclusivo |
| Cara séria | permanece **neutra** (negativa fraca é rebaixada) |
| Proibido | DeepFace A/B no path TRI; diagnosticar emoção; FP cara séria→negativa; bucket surpresa no relatório |
| Arquivos | `analytics_track._compute_expression` / `_smooth_expression`, `config.tri.yaml`, `normalization.py`, `SessionAnswers.tsx` |
| Testes | `tests/test_expression_negative_contract.py` |
| Status | **Código atualizado 2026-08-03 — aguarda aprovação manual** (raiva/choro ~10 s; sorriso sem flicker) |

---

## Ainda pendentes na matriz (não travados)

A (garrafa transparente formal), C×3 (fone), E1–E3, F (digitação vs sono — G aprovado ajuda), I, L×3, P1–P5 formais, EX−.

Ver matriz: `docs/VALIDACAO_FINAL_CENARIOS_TRI.md`.

---

## Regra de ouro

> Comportamento ✅ acima é **contrato de produto** para o TRI.  
> Alterar código/params sem reteste manual do cenário = risco de regressão silenciosa.  
> Em dúvida: consultar este arquivo **antes** de editar.
