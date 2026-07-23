# Segurança, privacidade e ética (LGPD)

## Princípios

Biometria facial é **dado sensível**. Finalidade atual: presença educacional e indicadores visuais **aparentes** no edge, com minimização de dados.

**Disclaimer obrigatório:** estimativas visuais; não diagnóstico; não comprovação de aprendizagem.

## Já implementado (técnico)

| Controle | Situação |
|----------|----------|
| Expressão: sem rótulos clínicos na UI | Sim (`predominantly_*` / display_pt) |
| DeepFace só emotion (contrato) | Sim; **não instalado no core** nesta etapa |
| Analytics RTSP sem mock | Sim (`RealtimeAnalyticsEngine`) |
| Sem persistência contínua de frames no debug | Sim |
| API não expõe embeddings | Sim |
| Debug vision: localhost + auth | Sim |
| RTSP/credenciais fora de respostas | Sim (não logar URL completa) |
| Variáveis de ambiente para segredos | Sim |
| Banco demo isolado do real | Sim |
| Review humana para confirmação de eventos | Sim (celular nunca auto-confirmed) |
| Proibição de raça/gênero/idade/etnia nos providers DeepFace | Contrato: só `emotion` |
| Auth por token opcional | Sim |
| Testes não tocam DB prod | Sim |
| Migration 005 gated | Sim |

## Pendente (governança / jurídico)

| Tema | Status |
|------|--------|
| Base legal e consentimento formal | A definir com jurídico |
| Política de retenção operacional assinada | Config existe (`data_retention_days`); processo pendente |
| Fluxo de exclusão comunicada ao titular | Endpoint privacy existe; processo pendente |
| Uso com crianças/adolescentes | Requer avaliação jurídica reforçada |
| DPIA / RIPD | Pendente antes de produção |
| Contrato LXP real e DPA | Pendente |

## Dados e retenção

- **Banco real:** presença, embeddings locais, fila de eventos, sessões  
- **Banco demo:** apenas simulação; apagável sem impacto  
- Evidências de review: flags de privacy no YAML (default sem raw video)  
- Logs: sem senhas, embeddings ou frames  

## Riscos

- Falsos positivos/negativos de identidade e de sinais comportamentais  
- Interpretação indevida de “emoção” ou “atenção” como avaliação de aluno  
- Exposição de RTSP se committed no Git  

**Recomendação:** validação jurídica antes de qualquer piloto com dados reais de estudantes.
