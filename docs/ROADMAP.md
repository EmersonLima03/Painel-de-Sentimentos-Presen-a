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
- Margem de identidade nunca inventada  
- Cabeça baixa / celular visível / rosto oculto ≠ labels automáticos de sono/desatenção/uso  
- Providers pluggable + lazy import  
- Shadow antes de production  
- Baixa qualidade → inconclusivo (não baixo engajamento)  
- Celular nunca confirmado automaticamente  
- LXP sem HttpClient até spec  
- Demo isolado do banco real  
- FusionEngine oficial; agregador legado depreciado como primário  
- Thresholds de presença congelados (`presence-yaml-2026-07-23`)  
- Tags `baseline-fase-0` e `pre-spike-sanitized` preservadas  

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
