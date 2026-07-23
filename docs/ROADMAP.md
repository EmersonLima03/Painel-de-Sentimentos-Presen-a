# Roadmap e decisões

## Estado atual por módulo

Ver tabela em [README.md](README.md). Atualização 2026-07-23:

- **Conectado no runtime RTSP/webcam:** quality, landmarks, expressão FER (ou unavailable), atenção, sonolência, phone status explícito via `RealtimeAnalyticsEngine`.
- **Testado automatizado:** 62 pytest; typecheck/build frontend.
- **Testado na webcam:** presença já validada localmente; analytics depende de reinício do servidor com o código novo — **sem declaração de acurácia**.
- Providers reais: **experimental / shadow / não aprovado para produção**.
- Intelbras / dataset rotulado / longitudinal: **pendentes**.

## Bloqueios atuais

1. Credenciais RTSP / câmera alcançável  
2. Corpus consentido para spike offline  
3. Benchmark FER / HSEmotion / DeepFace  
4. Validação longitudinal (`longitudinal_approval_recorded`)  
5. Spec HTTP do LXP (sem `HttpLXPClient` até lá)  

## Próximas etapas (ordem)

1. Configurar RTSP via env (sem Git)  
2. Capturar corpus consentido  
3. Benchmark providers de expressão em ambiente isolado  
4. Validar tracking / binding em câmera  
5. Validar associação de celular  
6. Calibrar sonolência aparente  
7. Medir CPU/RAM/FPS/latência **em hardware real**  
8. Validar dashboard em aula piloto  
9. Promover módulos selecionados para **shadow**  
10. Validação longitudinal  
11. Production seletiva  
12. Integração LXP real  

## Decisões arquiteturais vigentes

- Presença isolada de analytics  
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
