# Validação final — cenários controlados do TRI (visão)

**Objetivo de qualidade:** 100% de aprovação nos cenários controlados definidos para o fechamento do TRI.

**Checkpoint Git:** `98a9daa` (dashboard TRI + validação pré-ajustes). Working tree atual = proteções orelha/`eyes_observable` pós-checkpoint. **Não há tag de entrega estável.**

**Disclaimer:** estimativas visuais; sem diagnóstico.

**Estado do fechamento TRI:** **NÃO ENCERRADO** — matriz manual parcial.

**Baseline humano (consulta fixa):** [`docs/BASELINE_MANUAL_APROVADO_TRI.md`](BASELINE_MANUAL_APROVADO_TRI.md) — cenários ✅ aprovados na webcam; consultar **antes** de editar oclusão/celular/sono/atenção/expressão/cabeça baixa. **Não quebrar ✅ sem reteste.**

**Sessão 2026-08-03 (aprovados):** B (garrafa), D (celular real), G (olhos fechados), J/K (revalidação oclusão), ATTN (baixa atenção persistente), EX+/EX= (expressão positiva/neutra na sessão).  
**Débitos / revalidação:** EX− (expressão negativa). **H ✅ aprovado 2026-08-03 ~10:31/10:34.**

---

## Como capturar payload (manual)

```powershell
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Debug UI: `/debug/vision`
- Snapshot: `GET /api/v1/live/debug-snapshot` (localhost)
- Campos: `phones`, `rejected_detections`, tracks → `phone`, `face_occlusion`, `head`, `drowsiness`, `expression`, `observation_quality`, EAR/pitch
- Registrar por teste: duração | payload | esperado | obtido | aprovado/reprovado | `git rev-parse --short HEAD` | iluminação | câmera

Não persistir frames sem consentimento. Vídeos locais: `data/validation/tri/` (gitignored).

---

## Matriz de cenários

| ID | Cenário | Duração | Resultado esperado | Resultado proibido | Antes (webcam 2026-07-29) | Depois | Aprovado |
|----|---------|---------|--------------------|--------------------|---------------------------|--------|----------|
| A | Garrafa transparente na mão | 20s | not_detected / rejeitado | phone_in_hand, possible/probable | — | Auto: bottle/aspect reject OK | pendente manual (B ✅ cobre escura) |
| B | Copo térmico / garrafa escura | 20s ×3 | idem A | interação celular | **FP:** bbox + “Celular na mão” | Manual: garrafa sem FP | **✅ 2026-08-03** |
| C | Fone / região orelha | 20s ×3 | não celular (fone) | phone_near / eventos | **FP:** bbox no fone | Auto: `ear_region` por combinação | pendente manual ×3 |
| D | Celular real na mão | 2/5/12/15s | progressão temporal | confirmed_* auto | preservar | Manual: “detecção ótima” | **✅ 2026-08-03** |
| E1 | Celular na mesa parado | 30s | visible/near ok; sem in_hand | uso | — | Auto: mesa ≠ in_hand | pendente manual |
| E2 | Mão perto sem pegar | 10s | sem possible/probable | interação | — | Auto: wrist longe OK | pendente manual |
| E3 | Pegar e usar | 15s+ | in_hand → possible/probable | confirmed | — | Auto: pickup OK | pendente manual |
| F | Digitando / olhar teclado | 60s | head_down / inconclusivo ok | possible/probable drowsiness | risco EAR↓ | Auto: pause por `eyes_observable` | pendente manual (G ✅) |
| G | Olhos fechados frontais | limiares 6s/30s | possible/probable nos limiares | evento &lt;2.5s | — | Manual: “olhos fechados ótimo” | **✅ 2026-08-03** |
| H | Cabeça baixa parcial | &lt;8s / ≥8s | short / persistent; evento + card com duração ≈ real | sono auto; 0s; banner 2s após 40s | misto / parcial 10:17 | Print 10:31 **37s** contínuos; 10:34 **14s** — card alinhado | **✅ 2026-08-03** |
| EX− | Expressão negativa | ~8–10s sustentado | predominantly_negative (conf≥0.42, ≥2 amost.); surpresa fora do relatório; cara séria→neutra; sorriso sem flicker inconclusivo | FP cara séria; DeepFace A/B | 0s raiva/choro; flicker sorriso | Código 2026-08-03 | **revalidar manual** |
| I | Cabeça fora / rosto sumiu | 20s | face_not_observable / pose_inconclusive; sem inventar head_down | sono | OK parcial | Auto: sem promoção só por sumiço | pendente manual |
| J | Uma mão no rosto | &lt;8 / &gt;8 / 20s | oclusão + inconclusivos | sono; head_down auto | fragmentava / falhava 1 mão | Revalidado “ótimo” | **✅ 2026-07-30 / 08-03** |
| K | Duas mãos no rosto | 20s+ contínuo | oclusão persistente contínua | sono; episódios 6–10s | ~36s em 4 pedaços | Continuidade estável | **✅ 2026-07-30 / 08-03** |
| L | Mão perto sem cobrir | 20s ×3 | no máx. oclusão breve | persistente; celular FP | — | — | pendente manual ×3 |
| ATTN | Baixa atenção visual persistente | sustentado | evento/sinal persistente; sem virar sono | some o evento | — | Manual: “ótima” | **✅ 2026-08-03** |
| EX+/= | Expressão positiva / neutra (sessão) | sessão | sorriso→positiva; tempos relatório coerentes | sorriso longo sempre neutro | smile_boost off quebrava | Positiva 16m56s / Neutra 20m59s | **✅ 2026-08-03** |

### Controles positivos (anti falso-negativo)

| ID | Controle | Esperado | Depois (auto) | Aprovado |
|----|----------|----------|---------------|----------|
| P1 | Celular real na orelha | não rejeitar só por zona; in_hand com punho | `_context_reject` passa; wrist→in_hand | pendente manual |
| P2 | Celular real vertical | detectável / in_hand com punho | aspect+assoc OK | pendente manual |
| P3 | Celular segurado no colo | in_hand / near com punho | assoc OK | pendente manual |
| P4 | Celular parcialmente coberto pela mão | ainda associado (near/in_hand) | wrist OK | pendente manual |
| P5 | Celular na mesa → pegar de verdade | idle sem interação → in_hand após pegar | table→pickup OK | pendente manual |

### Template de registro manual (copiar por repetição)

```
ID/rep: _
Duração: _
Commit: _
Iluminação / câmera: _
Payload (resumo): phone.state=… rejected=… head=… drowsiness=… occ=… eyes_obs=…
Esperado: _
Obtido: _
Aprovado/Reprovado: _
```

### Registros manuais (sessão 2026-07-30)

```
ID/rep: J (1 mão)
Duração: ~20–40s contínuos
Commit base checkpoint: 98a9daa (+ working tree oclusão continuity)
Iluminação / câmera: ambiente interno / debug vision RTSP
Payload: face_occlusion persistent; eventos "Rosto coberto" + persistente; attn/drow inconclusive; identity continuity
Esperado: oclusão estável sem sono
Obtido: evento ~16–38s+ contínuo
Aprovado/Reprovado: APROVADO
```

```
ID/rep: K (2 mãos)
Duração: contínuo (sem fragmentação)
Commit base checkpoint: 98a9daa (+ working tree oclusão continuity)
Iluminação / câmera: ambiente interno / debug vision RTSP
Esperado: oclusão persistente contínua
Obtido: estável / aprovado pelo testador
Aprovado/Reprovado: APROVADO
```

### Registros manuais (sessão 2026-08-03)

```
ID/rep: B (garrafa)
Esperado: sem interação celular
Obtido: garrafa não detectada como celular — OK
Aprovado/Reprovado: APROVADO
```

```
ID/rep: D (celular real)
Obtido: detecção de celular ótima (testador)
Aprovado/Reprovado: APROVADO
```

```
ID/rep: G (olhos fechados)
Obtido: ótimo (testador)
Aprovado/Reprovado: APROVADO
```

```
ID/rep: J/K (revalidação oclusão)
Obtido: “Rosto coberto / não observável está ótimo”
Aprovado/Reprovado: APROVADO (revalidação)
```

```
ID/rep: ATTN (baixa atenção persistente)
Obtido: ótima (testador)
Aprovado/Reprovado: APROVADO
```

```
ID/rep: EX+/= (expressão sessão)
Obtido: Positiva 16m56s / Neutra 20m59s — ótima; smile_boost TRI on
Aprovado/Reprovado: APROVADO
```

```
ID/rep: H (cabeça baixa) — reprovado inicial
Duração real: >1 min cabeça baixa (só topo da cabeça / rosto fora)
Obtido: card “Postura inconclusiva”; eventos ao vivo “Nenhum evento relevante”; relatório ~14s / 0s
Esperado: head_down short/persistent + evento ao vivo + tempo ≈ real
Aprovado/Reprovado: REPROVADO — débito aberto
```

```
ID/rep: H (cabeça baixa) — progresso 2026-08-03 ~10:17–10:21 (pós-fix peito/zona ombros)
Iluminação / câmera: webcam RTSP /debug/vision
Print 1: ~30s cabeça baixa real; rosto sumido ~44s no UI
  Obtido: evento “Cabeça baixa prolongada” presente (timer UI ~2s); card Cabeça ainda “Postura inconclusiva”; atenção baixa ativa
Print 2: ~40s cabeça baixa real; rosto sumido ~42s
  Obtido: eventos “Atenção visual baixa · 22s” + “Cabeça baixa prolongada · 7s”; card/atenção coerentes com rosto sumido
Esperado: duração do evento/card/relatório ≈ tempo real contínuo (1 episódio)
Obtido vs esperado: MUITO MELHOR que 0s/sem evento; ainda SUBCONTA (evento reinicia / card oscila inconclusivo)
Aprovado/Reprovado: PARCIAL — corrigido em seguida (started_at / card continuity)
```

```
ID/rep: H (cabeça baixa) — APROVAÇÃO 2026-08-03 ~10:31 e ~10:34
Iluminação / câmera: webcam RTSP /debug/vision
Print 1 (~10:31): evento “Cabeça baixa prolongada · 37 s”; card Cabeça “prolongada” + duração contínua 37 s; rosto sumido ~39 s; attn baixa; sono/expr inconclusivos
Print 2 (~10:34): evento · 14 s; card duração contínua 14 s; testador: ambos “incrível”
Esperado: continuidade ≈ real; card = evento; sem sono; peito ≠ oclusão
Obtido: alinhado (37s/14s)
Aprovado/Reprovado: APROVADO — contrato em docs/BASELINE_MANUAL_APROVADO_TRI.md (H ✅)
```

```
ID/rep: EX− (expressão negativa)
Obtido: ainda sem contrato/definição clara
Aprovado/Reprovado: PENDENTE (definir melhor no próximo passo)
```

### Achados baseline (prints)

1. **B** — ~~térmico FP~~ → **2026-08-03 aprovado** (garrafa sem FP).  
2. **C** — fone → bbox + `phone_near_person` (ainda pendente ×3).  
3. **H** — **✅ 2026-08-03 10:31/10:34:** evento + card contínuos (ex. 37s / 14s); não quebrar (baseline H).  
4. **J** — mão no rosto → oclusão + inconclusivos + continuidade **OK** (revalidado).  
5. **I/H** — cabeça apoiada → às vezes `Cabeça baixa (breve)` **OK** (não cobre H extremo).  
6. **EX+/=** — tempos de sessão positiva/neutra **OK** com `smile_boost_enabled: true`.

### Correções aplicadas (código)

| Problema | Correção | Thresholds globais YOLO? |
|----------|----------|---------------------------|
| Fone→in_hand | Sem `near_face` sozinho como `in_hand`; exige punho | Não |
| Térmico/garrafa | `_context_reject_reason` altura relativa (fora da orelha); **não** rejeitar celular vertical real (`keep_vertical_phone`); card: timer só em in_hand/interação (near ≠ uso) | Não |
| Fone YOLO | `ear_region_implausible` **por combinação** (pequeno + sem punho + zona + geom + instável); celular real na orelha passa | Não |
| Mesa | lower-body ≠ in_hand abaixo ~90% sem punho | Não |
| Digitação→sono | Acumulador baseado em `eyes_observable` (face, landmarks_quality, pose_score, oclusão); pitch/`head_down` não são bloqueio absoluto; pausa sem reset indevido | Limiares 6s/30s intactos |
| Cabeça / sumiço | pose confiável → short/persistent; senão inconclusive; nunca promover só por rosto sumir | — |
| Oclusão 1/2 mãos fragmentava | Hold `face_missing_hold_seconds=15`; zona cabeça/cotovelo; event clear-hold longo; UI sem “Sem oclusão” com pause | Não |

**Depois (automático):** regressões A/B/C/E/F/H/I + oclusão continuity + P1–P5.  
**Depois (manual):** **J ✅ K ✅** (2026-07-30); **B ✅ D ✅ G ✅ ATTN ✅ EX+/EX= ✅ H ✅** + revalidação J/K (2026-08-03).  
**Aberto / revalidar:** EX−, C×3, E1–E3, F, I, L×3, P1–P5 formais, A.

Consulta permanente do que já está aprovado: **`docs/BASELINE_MANUAL_APROVADO_TRI.md`**.

**Presença / IdentityBinding / `/debug/vision` layout / contexto pedagógico / Supabase / arquitetura dashboard:** não alterados nesta etapa.

---

## Thresholds vigentes (não alterar sem teste de fronteira)

| Chave | Valor tipico |
|-------|----------------|
| `phone_yolo_conf_threshold` | 0.42 |
| `phone_yolo_max_height_width_ratio` | 2.7 |
| `phone_possible_after` / `probable` | 5s / 12s |
| `drowsiness_possible` / `probable` | 6s / 30s |
| `head_down_event_min_seconds` | 8s |
| `face_occlusion_persistent_seconds` | 5s |

---

## Fixture / testes

- `tests/fixtures/tri_validation_scenarios.json`
- `tests/test_phone_false_positive_regression.py`
- `tests/test_phone_positive_controls.py`
- `tests/test_phone_table_interaction.py`
- `tests/test_typing_not_drowsiness.py`
- `tests/test_head_down_visibility_gate.py`
- `tests/test_occlusion_continuity.py` (J/K — anti-fragmentação / 1 mão)

## Critério para declarar fechamento

Só declarar **“100% de aprovação nos cenários controlados definidos para o fechamento do TRI.”** quando:

1. Nenhum cenário obrigatório reprovado na matriz manual;  
2. Nenhum teste obrigatório skipped;  
3. `pytest tests -q` + `npm run typecheck` + `npm run build` verdes;  
4. Matriz manual completa (incl. B/C/K/L ×3 e P1–P5).

Enquanto houver “pendente manual”, o TRI **permanece aberto**.

## Limitações

Webcam real ≠ corpus rotulado; YOLO COCO 67 confunde objetos; pose lite falha em ângulos extremos.
