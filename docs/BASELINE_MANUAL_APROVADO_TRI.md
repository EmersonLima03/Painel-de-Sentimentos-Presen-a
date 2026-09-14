# Baseline manual aprovado — TRI (visão)

> **CONGELADO** — branch `tri/congelado-baseline-validado` · ver [`TRI_CONGELADO.md`](TRI_CONGELADO.md)  
> **Regra:** cenários ✅ abaixo **não podem regredir**. Não editar áreas sensíveis sem reteste manual.

Documento **fixo** para consultar **antes** de editar oclusão, celular, sono, atenção, expressão ou cabeça baixa.  
Se uma mudança quebrar o comportamento abaixo, **revalidar na webcam** antes de considerar ok.

**Disclaimer:** estimativas visuais; sem diagnóstico.  
**TRI:** ainda aberto (matriz incompleta). Só cenários listados como ✅ estão travados por validação humana.

**Última sessão de aprovação humana:** 2026-09-13/14 — Emerson Lima (`/debug/vision`, RTSP local, LIVE). Detalhe: [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md).

---

## Como usar este arquivo

1. Antes de mexer nos arquivos sensíveis da seção afetada → ler o cenário ✅.  
2. Depois da edição → reexecutar o cenário ✅ e os testes automáticos citados.  
3. Ao aprovar um novo cenário manual → acrescentar aqui **e** marcar a matriz em `docs/VALIDACAO_FINAL_CENARIOS_TRI.md`.  
4. **Nunca** “melhorar” um cenário ✅ sem reteste manual: oclusão, celular/garrafa, **peito vs uso na frente do rosto (E4+E3 juntos)**, sono, atenção baixa persistente, expressão positiva/neutra, **cabeça baixa (H)**.

---

## Contrato — não quebrar (resumo)

| Área | ✅ Travado | Proibido regressar para |
|------|------------|-------------------------|
| Oclusão 1/2 mãos (J/K) | Evento “Rosto coberto / não observável” estável; attn/sono inconclusivos | Sem evento; fragmentação; sono inventado |
| L — mão próxima sem bloquear | Face observável → `face_occlusion=none` válido; near opcional; sem persistent por proximidade | Tratar queixo/bochecha como oclusão; exigir `hand_near_face` |
| Celular vs garrafa (B) | Garrafa **não** vira interação/celular na mão | FP bbox + “Celular na mão” em garrafa |
| Celular real (D) | Detecção / progressão útil com celular real | FN sistemático com celular real na mão |
| Celular no peito (E4) | Peito + olhar à câmera → visível/near, **não** uso | Interação/atenção baixa só porque o aparelho está no peito |
| Celular na frente do rosto (E3) | À frente do rosto / pegar e usar → in_hand → possible/probable | “Não indica uso” com celular na cara; quebrar E3 ao corrigir E4 |
| Celular ao lado (E-lat) | Ao lado + olhar câmera → visível/near, **não** uso | Tratar lateral como E3; oclusão inventada |
| Olhos fechados (G) | Possible/probable nos limiares 6s/30s | Eventos &lt;2.5s; FP de sono ao digitar |
| Atenção baixa persistente | Evento / sinal de baixa atenção persistente quando aplicável | Sumir o evento ou confundir com sono |
| Expressão +/neutra (EX) | Sorriso sustentado → positiva; sessão com tempos +/neutra coherentes | Sorriso longo sempre neutro (`smile_boost` off) |
| Cabeça baixa (H) | Evento + card “prolongada” com duração ≈ tempo real; 1 episódio contínuo | 0s / sem evento; banner 2s após 40s; card inconclusivo com evento aberto; peito→oclusão falsa |
| Perfil / lateral (I) | `head_turned` **ou** `pose_inconclusive`; sem head_down/sono só por perfil | Exigir só `pose_inconclusive`; inventar `head_down_persistent` ou sono por lateral |
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

### L — Mão próxima / apoio sem bloquear ✅

| Campo | Valor |
|-------|--------|
| Data | **2026-09-09** (vídeos oficiais NEW6 + alinhamento de contrato) |
| Evidência | `L_mao_parcial_rosto.mp4` (queixo; face observável); cobertura = J via `L_uma_mao_cobrindo_rosto.mp4`; K = `K_duas_maos_cobrindo_rosto.mp4` |
| Esperado | Se olhos/nariz/boca e landmarks utilizáveis → `face_occlusion=none` **válido**; `hand_near_face` **opcional** (não critério de aprovação); **não** promover `persistent_*` só por proximidade |
| Oclusão real (J/K) | Cobertura que prejudica observabilidade → `possible_face_occlusion_by_hand` → ~5s → `persistent_possible_face_occlusion` → recuperação |
| Obtido | L parcial sem oclusão = correto; uma mão / duas mãos cobrindo = possible→persistent→recovery OK |
| Proibido que volte | Queixo/bochecha virar oclusão persistente; exigir `hand_near_face` para “passar” L; confundir near com oclusão |
| Arquivos sensíveis | Docs de contrato; **não** exigir mudança de detector só por L parcial |
| Testes | `tests/test_l_occlusion_contract.py`, `tests/test_occlusion_continuity.py`, `tests/test_occlusion_hysteresis.py` |

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
| Data | 2026-08-03; **revalidado LIVE 2026-09-13** (alerta `probable` verdadeiro, não só lock no fim) |
| Esperado | Celular real detectável / progressão útil; sem `confirmed_*` automático indevido |
| Obtido | Aprovado — “detecção de celular está ótimo”; LIVE: caixa contínua + `probable` durante o uso |
| Proibido que volte | FN sistemático; “travou no fim” após FN no pickup; confirmed automático sem revisão |
| Arquivos / testes | Idem B + `tests/test_phone_positive_controls.py` |
| Params tipicos | `phone_possible_after` 5s / `probable` 12s; hold fechamento celular ~12s |

### E4 — Celular no peito, olhar à câmera ✅

| Campo | Valor |
|-------|--------|
| Data | **2026-09-03**; **revalidado LIVE 2026-09-13** (peito + olhar câmera = near, não uso) |
| Testador | Emerson Lima |
| Câmera / UI | `/debug/vision`, XWF-1080P USB, overlay TRI |
| Esperado | Aparelho **visível** (bbox magenta ok). Card: **próximo / não indica uso**. Atenção **não** baixa por `derived_from_phone`. Sem `possible`/`probable`. |
| Obtido | Aprovado — peito + olhar à frente não computa uso |
| Proibido que volte | “Provável interação” + atenção baixa só porque o celular está no peito |
| Arquivos sensíveis | `app/vision/person_phone.py` (`_phone_on_chest`, `_phone_below_face_on_torso`, `_phone_raised_to_face`) |
| Testes | `tests/test_phone_filters.py` (`test_in_hand_heuristic_phone_on_chest`, `test_portrait_phone_on_chest_looking_forward_not_interaction`, `test_chest_phone_looking_forward_not_probable_even_with_wrist`) |

### E3 — Pegar / usar na frente do rosto ✅

| Campo | Valor |
|-------|--------|
| Data | 2026-08-03 (detecção D); **aprovado LIVE 2026-09-13/14** (cara / uso; par E4 no mesmo dia) |
| Esperado | Celular **à frente do rosto** (olhando o aparelho) → `phone_in_hand` e, com persistência, `possible` (≥5s) / `probable` (≥12s). Sem `confirmed_*` automático. Recorte YOLO só no bloco das câmeras, **colado no rosto**, ainda é uso. |
| Obtido | Aprovado na webcam 2026-09-13/14. Código: `phone_raised_to_face` + `raised_roi` + gap colado ≠ lateral. |
| Proibido que volte | Card “não indica uso” com celular na cara; flicker sistemático `not_detected` no uso real; corrigir E4 ou “ao lado” quebrando E3 |
| Arquivos / testes | Idem E4 + `test_phone_raised_to_face_looking_forward_is_in_hand`, `test_real_phone_near_face_with_wrist_still_in_hand`, `tests/test_phone_positive_controls.py`, `tests/test_phone_table_interaction.py` |
| Regra de par | **E4 e E3 sempre retestados juntos.** Ajuste de peito sem reteste de uso na cara = regressão. |

### E-lat — Celular ao lado, olhar câmera (não uso) ✅

| Campo | Valor |
|-------|--------|
| Data | **2026-09-13/14 LIVE** |
| Esperado | Aparelho **visível** ao lado do corpo, olhar à câmera → `phone_near_person` / `phone_lateral_visible_not_use`; **sem** in_hand / possible / probable; **sem** oclusão inventada |
| Distinguir de E3 | Encostar/sobre o rosto (mesmo bbox parcial só nas câmeras) = uso, não “ao lado” |
| Proibido que volte | `large_handheld_upper` promover lateral a uso; gap colado no rosto virar “não uso” |

**Paridade anti-regressão (celular):** após editar `person_phone.py` / `phone_yolo.py`, rodar:

```
pytest tests/test_phone_filters.py tests/test_phone_table_interaction.py tests/test_phone_positive_controls.py tests/test_phone_false_positive_regression.py -q
```

Depois, webcam: 20s peito olhando câmera → 15s celular na frente do rosto.

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

### I — Perfil / lateral / rosto sumiu sem look-down ✅

| Campo | Valor |
|-------|--------|
| Data | **2026-09-09** (contrato alinhado + evidência `Iperfil.mp4`) |
| Evidência | Offline TRI: predominância `head_turned` + `pose_inconclusive`; **0** `head_down_*`; **0** possible/probable drowsiness; identidade real E2E `p01` sem troca + reconfirmação |
| Esperado | Perfil/lateral verdadeiro → `head_turned` **ou** `pose_inconclusive` (ambos válidos). `head_turned` = lateralidade observável (`lateral_nose_offset`). `pose_inconclusive` = geometria insuficiente / face missing sem geom look-down |
| Proibido | `head_down_persistent` (ou short promovido) só por perfil; `possible_drowsiness` / `probable_drowsiness` só por perfil/lateral |
| Distinguir de H / HEADDOWN | H/HEADDOWN = look-down / topo da cabeça com evidência corporal; I = virar/sair sem afirmar cabeça baixa |
| Arquivos sensíveis | Contrato/docs; **não** exigir mudança de `body_pose` só para forçar `pose_inconclusive` |
| Testes | `tests/test_tri_pending_scenarios.py` (contrato I), `tests/test_head_down_visibility_gate.py` |

---

## Débitos abertos / em calibração

### EX− — Expressão negativa ✅ FECHADO 2026-09-09 (HSEmotion VGAF)

| Campo | Valor |
|-------|--------|
| Data | **2026-09-09** — promoção controlada `hsemotion_vgaf` como default |
| Evidência | Offline 4/4: EXseria→neutra; EXpositiva_v2→positiva; EXnegativa_v2_triste/raiva→negativa |
| Backend | `hsemotion_vgaf` async ~2 s; FER+ permanece fallback (`EXPRESSION_EMOTION_BACKEND=fer_onnx`) |
| Mapping | sad/angry/fear/disgust/contempt → `negative`; surprise → inconclusive; sem smile/frown no path VGAF |
| Cara séria | permanece **neutra** (VGAF) |
| Proibido | DeepFace A/B no path TRI; diagnosticar emoção; FP cara séria→negativa |
| Docs | `docs/EMOTION_BACKEND_HSEMOTION_VGAF.md` |
| Testes | `tests/test_hsemotion_vgaf_experimental.py`, `tests/test_expression_negative_contract.py` |

### EX+/EX= — preservados com VGAF

Sorriso → `predominantly_positive`; cara séria/neutra → `predominantly_neutral` (validado nos mesmos vídeos EX da promoção).

---

## Ainda pendentes na matriz (não travados)

A (garrafa transparente formal), sync matriz C/F/E1–E2/P com closes offline. **EX−:** ✅ 2026-09-09. **I:** ✅ 2026-09-09. **L:** ✅ 2026-09-09. **E3/E4:** contrato de código travado 2026-09-03; confirmar no roteiro visual após restart.

Ver matriz: `docs/VALIDACAO_FINAL_CENARIOS_TRI.md`.

---

## Regra de ouro

> Comportamento ✅ acima é **contrato de produto** para o TRI.  
> Alterar código/params sem reteste manual do cenário = risco de regressão silenciosa.  
> Em dúvida: consultar este arquivo **antes** de editar.
