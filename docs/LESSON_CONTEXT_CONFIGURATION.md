# Configuração modular do contexto da aula

Documento **conceitual**. Não descreve um schema implementado no código. Complementa [`MODULAR_CLASSROOM_SCENARIOS.md`](MODULAR_CLASSROOM_SCENARIOS.md).

## Objetivo

Definir **como** uma aula (ou fase de aula) informa ao edge:

- o que está acontecendo;
- o que é esperado / permitido / proibido;
- quais detectores e alertas fazem sentido;
- quais limites de tempo aplicar;
- quais exceções individuais existem **sem** expor diagnóstico clínico.

## Escopos de configuração

| Escopo | Exemplos | Quem altera | Validação técnica |
|--------|----------|------------|-------------------|
| **Global (produto)** | Vocabulário de status; política “nunca confirmed automático”; labels éticos | Engenharia + produto | Obrigatória |
| **Escola** | Câmeras, privacidade default, retenção, ROI físicos base | Operação / DPO | Obrigatória |
| **Turma** | Layout de carteiras, zonas recorrentes, lista de alunos | Coordenação | Recomendada |
| **Aula (`lesson`)** | `lesson_type`, materiais, dispositivos, alertas on/off | Professor / LXP | Produto |
| **Fase (`phase`)** | Explicação → prática → correção | Professor / LXP / timeline | Produto |
| **Exceção individual** | Flags de acomodação (sem diagnóstico) | Coordenação / inclusão | Jurídico + produto |
| **Thresholds de detector** | EAR, IoU, TTL de track | Engenharia | **Não** alterar sem validação e testes |

### O que não deve ser modificado sem validação técnica

- Thresholds de presença congelados (`presence-yaml-…`).
- EAR / drowsiness / phone duration defaults sem corpus.
- TTL de person track e regras de identity binding.
- Qualquer detector de segurança/fraude.
- Políticas de armazenamento e biometria.

### O que pode variar por aula/fase (produto)

- `allowed` / `required` de dispositivos e materiais.
- Quais alertas estão ligados.
- Quais comportamentos são “esperados” (só mudam interpretação/ação, não o fato bruto).
- ROIs pedagógicos daquela aula.
- Limites de ausência / repetição **acima** de um piso técnico mínimo.

## Modelo conceitual (YAML ilustrativo)

```yaml
lesson_context:
  lesson_id: ""
  class_id: ""
  school_id: ""
  source: "manual"          # manual | lxp | inferred_future
  lesson_type: "lecture"    # ver catálogo de perfis
  phase: "explanation"      # explanation | practice | assessment | transition | entry | exit | ...
  started_at: null
  ends_at: null

  expected_behaviors:
    looking_at_board: true
    looking_at_teacher: true
    looking_at_material: false
    writing: false
    reading: false
    group_interaction: false
    leaving_seat: false
    standing: false
    device_use: false

  devices:
    phone:
      allowed: false
      required: false
      alert_after_seconds: 12      # só se allowed=false; piso técnico separado
      register_only: false
    tablet:
      allowed: false
      required: false
    computer:
      allowed: false
      required: false
    headphones:
      allowed: false
      required: false

  materials:
    notebook_expected: true
    book_expected: false
    worksheet_expected: false
    calculator_allowed: false
    exam_sheet_expected: false

  zones:
    board_roi: null
    teacher_roi: null
    material_roi: null
    door_roi: null
    seat_rois: []
    group_work_rois: []
    out_of_task_rois: []

  detectors:
    # intenções de ativação — não implica detector existente
    person_tracking: true
    face_identity: true
    phone: true
    pose_body: true
    materials: false
    hand_raise: false
    student_interaction: false
    audio: false

  alerts:
    probable_phone_interaction: true
    prolonged_absence: true
    possible_drowsiness: true
    leaving_seat: false
    conversation: false
    head_down: false          # em leitura/prática: false por padrão

  recording_policy:
    show_on_panel: ["possible_drowsiness", "probable_phone_interaction"]
    register_only: ["brief_look_away", "head_down_short"]
    ignore_when_expected: ["leaving_seat", "group_interaction", "device_use"]
    important_events: ["prolonged_absence", "possible_drowsiness"]
    review_queue: ["assessment_incompatible_behavior"]

  thresholds:
    # só limiares de política pedagógica; limiares de CV ficam no YAML técnico
    prolonged_absence_seconds: 300
    temporary_absence_seconds: 120
    repeated_event_window_seconds: 300
    presence_partial_percentiles: [25, 50, 75]

  accommodations:
    enabled: true
    # preferir IDs opacos + flags comportamentais, sem diagnóstico
    entries: []
    # exemplo conceitual:
    # - student_ref: "opaque-uuid"
    #   allow_device_always: true
    #   allow_leaving_seat: true
    #   suppress_alerts: ["possible_drowsiness"]
    #   notes_internal: ""   # não exibir no painel operacional

  provenance:
    configured_by: ""
    configured_at: null
    lxp_payload_hash: null
```

## Mapeamento perfil → defaults sugeridos (conceitual)

| `lesson_type` | Celular | Fora do assento | Cabeça baixa | Interação | Sonolência |
|---------------|---------|-----------------|--------------|-----------|------------|
| `lecture` | alerta | relevante | neutro/relevante | alerta se prolongada | alerta |
| `individual_reading` | alerta | neutro | esperado | neutro | só com olhos fechados + baixa mov. |
| `writing` | alerta | neutro | esperado | neutro | idem |
| `pair_work` / `group_work` | conforme policy | esperado | neutro | esperado | alerta |
| `assessment` | alerta forte / revisão | relevante | neutro | revisão (não fraude auto) | alerta |
| `maker` / `robotics` / `lab` | pode ser esperado | esperado | esperado | esperado | só combinação forte |
| `entry` / `exit` / `break` | registrar | esperado | ignorar | neutro | off ou suave |
| `emergency` | off pedagógico | off | off | off | off; protocolo humano |

Defaults **não** são código. Qualquer ativação exige o checklist de promoção em `MODULAR_CLASSROOM_SCENARIOS.md`.

## Integração com fontes

| Fonte | Uso | Status no repo |
|-------|-----|----------------|
| Manual (UI professor) | Selecionar tipo/fase | **ausente** |
| LXP HTTP | Empurrar `lesson_context` | **depende de integração externa** (só mock/outbox hoje) |
| Timeline local | Registrar mudanças de fase | **parcialmente implementado** (timeline de eventos; sem fase de aula) |
| Inferência automática de fase | Último recurso | **ausente** — alto risco; não priorizar cedo |

## Relação com configuração técnica atual

Hoje o runtime usa `config.yaml` / env para **módulos técnicos** (`modules.*.mode`, `phone.*`, `drowsiness.*`, `identity_binding.*`). Isso **não** substitui `lesson_context`:

| Camada técnica (existente) | Camada pedagógica (futura) |
|----------------------------|----------------------------|
| Detector ligado/desligado | Interpretação do mesmo fato |
| Threshold de CV | Threshold de política (alerta sim/não) |
| Qualidade → inconclusivo | Contexto → esperado vs incompatível |
| Attribution / pending | Acomodação / revisão humana |

## Privacidade neste modelo

- Acomodações: flags mínimas; sem diagnóstico no painel.
- Não exportar `notes_internal` para dashboards de turma.
- Mudança de threshold técnico no semestre deve gerar provenance auditável.
- Contestação de evento: manter fato bruto + contexto vigente no momento do evento.

## Próximo passo documental (não implementação)

1. Validar vocabulário de `lesson_type` / `phase` com produto.
2. Definir quem pode editar cada escopo.
3. Spec mínima LXP para payload `lesson_context`.
4. Só então abrir issue de implementação P1.
