# Roadmap e decisões

## Estado atual por módulo

- **Conectado e validado na webcam (cam-web):** presença, observation quality, MediaPipe Tasks landmarks, expressão ONNX, atenção/sonolência, YOLO celular, eventos temporais, WS RTSP, debug vision.
- **Person-first (analytics):** YOLO person → ByteTrack bruto → **StablePersonTrackManager** (ID estável sob oclusão); IdentityBinding TTL/swap; Pose IMAGE; `phone_detector` debug.
- **Painel de validação controlada:** cenários extras (oclusão TTL, swap, cabeça≠sono, celular mesa, cruzamento).
- **Testado automatizado:** `test_person_centric_pipeline` + regressão de presença; typecheck/build frontend.
- Intelbras / dataset rotulado / longitudinal: **pendentes**.

## Bloqueios atuais

1. TensorFlow completo não instalado (disco) — FER via ONNX  
2. Corpus consentido / longitudinal  
3. Spec HTTP do LXP  
4. Validação de campo Intelbras  
5. Calibração YOLO celular só após amostras reais em `/debug/vision` (`phone_detector`)  

## Próximas etapas (ordem)

1. Validar 1 pessoa (track + TTL + pose + celular) na webcam  
2. Só então 2 / 4 / 8 pessoas e cruzamentos  
3. Configurar RTSP via env (sem Git)  
4. Capturar corpus consentido  
5. Benchmark providers de expressão em ambiente isolado  
6. Calibrar threshold celular com amostras  
7. Medir CPU/RAM/FPS/latência **em hardware real**  
8. Shadow → longitudinal → production seletiva  
9. Integração LXP real  

## Decisões arquiteturais vigentes

- Presença isolada de analytics  
- Person track ≠ face track ≠ identidade  
- **Confirmação facial (12s) ≠ expiração de identidade**; body_continuity sem TTL oculto por decay  
- Margem de identidade nunca inventada  
- Cabeça baixa / celular visível / rosto oculto ≠ labels automáticos de sono/desatenção/uso  
- Observabilidade **por módulo**; temporarily_lost ≠ body_observable  
- Eventos sensíveis com `attribution_status`; uncertain → pending no track  
- Providers pluggable + lazy import  
- Shadow antes de production  
- Baixa qualidade → inconclusivo (não baixo engajamento)  
- Celular nunca confirmado automaticamente  

## Levantamento complementar ao P0 (somente documentação)

Inventário abrangente de cenários reais de sala **ainda não cobertos** ou cobertos só parcialmente. **Não** faz parte da implementação P0; **não** altera thresholds nem detectores.

| Documento | Conteúdo |
|-----------|----------|
| [`MODULAR_CLASSROOM_SCENARIOS.md`](MODULAR_CLASSROOM_SCENARIOS.md) | Fato × temporal × contexto × interpretação × ação; 30 perfis de aula; catálogo A–P; matriz de status; P1/P2/P3; checklist de promoção |
| [`LESSON_CONTEXT_CONFIGURATION.md`](LESSON_CONTEXT_CONFIGURATION.md) | Modelo conceitual de `lesson_context` (YAML ilustrativo); escopos global/escola/turma/aula/fase/exceção |

Fórmula adotada: `observação visual + duração + contexto da aula + configuração + qualidade = interpretação`.

Qualquer item desses docs só vira código após o checklist de promoção (objetivo, detector, temporal, qualidade, inconclusivo, testes, copy, alerta, storage, revisão humana, aprovação de produto).

## Módulos futuros (configuráveis por aula — fora do P0)

Resumo operacional (detalhamento e status por cenário → docs acima):

- Contexto de aula: celular/tablet permitido|obrigatório|proibido; etapa da aula  
- ROI professor / quadro / material / porta  
- Caderno, livro, escrita, leitura, mão levantada  
- Áudio / turnos de fala / colaboração  
- Presença temporal de aula (entrada/saída/retorno/% acompanhado) — **não** tratar “não visível na câmera” como “fora da sala”  
- Baseline individual; PERCLOS decisório após validação própria  
- LXP sem HttpClient até spec  
- Demo isolado do banco real  
- FusionEngine oficial; agregador legado depreciado como primário  
- Thresholds de presença congelados (`presence-yaml-2026-07-23`)  
- Tags `baseline-fase-0` e `pre-spike-sanitized` preservadas  
- Segurança / fraude / multicâmera fundida: **P3** (alto risco; sem promessa)  

## Débitos técnicos

- Dual path legado (temporal aggregator + behavioral WIP)  
- Migration 005 possivelmente já presente em alguns DBs locais (vazia)  
- Providers reais sem aprovação  
- Dashboard legado paralelo ao React  
- Performance real não medida  
- MediaPipe `solutions` pode falhar em algumas versões (face mesh refiner desliga)  
- Drift local possível em `engagement.backend` (híbrido para teste webcam) vs baseline head_pose — documentar ao promover  

## Critérios de conclusão

| Nível | Critério |
|-------|----------|
| **Pronto para demonstração** | Demo E2E + docs oficiais + testes verdes — **atingido** |
| **Pronto para piloto controlado** | RTSP estável + review humana + shadow + base legal mínima |
| **Pronto para produção** | Gates longitudinais + providers aprovados + LXP real (se necessário) + DPIA |
