# TRI congelado — baseline validado (não quebrar)

**Branch oficial deste congelamento:** `tri/congelado-baseline-validado`  
**Data do congelamento:** 2026-08-31  
**Recongelamento LIVE:** 2026-09-14 — ver [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md)  
**Base Git anterior:** `98a9daa` → este branch inclui todo o trabalho acumulado até o congelamento.

---

## Regra de ouro (leia antes de qualquer PR)

> **Cenários marcados ✅ em [`BASELINE_MANUAL_APROVADO_TRI.md`](BASELINE_MANUAL_APROVADO_TRI.md) são CONTRATO.**  
> **Não altere código, parâmetros ou UI que afetem essas áreas sem reteste manual na webcam.**  
> Se quebrar um ✅, o TRI **não** pode ser considerado fechado.

Isso não significa “nunca mais evoluir o produto”. Significa:

1. Mudanças em área sensível → **obrigatório** rerodar o cenário ✅ correspondente.  
2. Validação TRI → **sempre** com `config.tri.yaml` (não o `config.yaml` de experimentos).  
3. Novos cenários (C, I, EX−, etc.) → desenvolver **sem** regredir os ✅ já aprovados.

---

## Como rodar o perfil congelado (obrigatório para validar TRI)

```powershell
cd Presenca
.\venv\Scripts\Activate.ps1
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Dashboard: http://127.0.0.1:8000/dashboard  
- Debug: http://127.0.0.1:8000/debug/vision  

**Provider TRI:** `fer_onnx` + `smile_boost_enabled: true` (contrato EX+/EX=).  
**Não usar** HSEmotion/DeepFace no path de fechamento TRI sem aprovação explícita e reteste completo.

---

## O que está ✅ travado (não quebrar)

| ID | Cenário | Áreas sensíveis no código |
|----|---------|---------------------------|
| **J/K** | Oclusão 1/2 mãos | `body_pose.py`, `occlusion_head_arbitration.py`, `analytics_track.py` (hold oclusão) |
| **B** | Garrafa ≠ celular | `phone_yolo.py`, `person_phone.py` |
| **D** | Celular real | idem + filtros de associação |
| **E3** | Celular na cara / uso | `person_phone.py` (`_phone_raised_to_face`) + `phone_yolo.py` (`raised_roi`) |
| **E4** | Celular no peito ≠ uso | `person_phone.py` (`_phone_on_chest`) + `chest_roi` |
| **C** | Fone ≠ celular | `phone_yolo.py` / `_phone_in_ear_zone` |
| **E-lat** | Celular ao lado, olhar câmera ≠ uso | `phone_lateral_visible_not_use` |
| **G** | Olhos fechados | `analytics_track.py` (drowsiness / `eyes_observable`) |
| **H** | Cabeça baixa | `body_pose.py`, `occlusion_head_arbitration.py`, `analytics_track.py` (head_down) |
| **ATTN** | Baixa atenção persistente | atenção + agregador + relatório |
| **EX+/EX=** | Expressão positiva/neutra | `config.tri.yaml`, `_compute_expression`, `fer_onnx` |

Detalhe completo: [`BASELINE_MANUAL_APROVADO_TRI.md`](BASELINE_MANUAL_APROVADO_TRI.md).

---

## O que entrou neste branch (além do baseline ✅)

Tudo que estava na working tree no momento do congelamento, incluindo:

- Dashboard pedagógico (**Respostas da aula**, tempos por categoria, episódios).  
- Ajustes de expressão, cabeça baixa, baixa atenção derivada, merge de episódios.  
- Providers experimentais (HSEmotion/DeepFace) no `config.yaml` de **dev** — **não** substituem o perfil TRI.  
- Testes novos (`test_occlusion_continuity`, `test_expression_negative_contract`, etc.).  
- Documentação de validação e calibração.

**Importante:** parte do trabalho em `config.yaml` é **sandbox de desenvolvimento**. O contrato validado em webcam usa **`config.tri.yaml`**.

---

## Testes mínimos antes de merge neste branch

```powershell
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
pytest tests/test_fer_onnx.py tests/test_tri_config_overlay.py -m tri -q
pytest tests/test_occlusion_continuity.py tests/test_occlusion_hysteresis.py tests/test_head_down_visibility_gate.py tests/test_session_aggregator.py -q
```

---

## O que ainda falta para TRI 100%

Matriz manual incompleta: A, C×3 formais, E1, E2, F, P1–P5.  
E3/E4/D/C (1 take) e lateral-sem-uso **reaprovados LIVE 2026-09-13/14**.  
H/I/L/J/EX+ não foram o take desta sessão (contratos de agosto seguem).  
Ver [`VALIDACAO_FINAL_CENARIOS_TRI.md`](VALIDACAO_FINAL_CENARIOS_TRI.md) e [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md).

**Este congelamento não declara TRI 100%** — declara **baseline ✅ protegido** + código versionado para continuar o fechamento com segurança.

---

## Fluxo de trabalho recomendado

```
tri/congelado-baseline-validado   ← baseline ✅ + trabalho acumulado (esta branch)
        │
        ├── fixes só em cenários PENDENTES (C, I, EX−, …)
        │   └── retestar TODOS os ✅ afetados
        │
        └── após matriz 100% → tag tri-emocoes-dashboard-v1.0 → merge develop/main
```

**Nunca** editar direto em `main`/`develop` áreas sensíveis sem passar por esta branch e pelos testes acima.
