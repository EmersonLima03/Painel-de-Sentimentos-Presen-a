# Cenários reais de sala de aula — levantamento complementar ao P0

> **Natureza deste documento:** inventário e roadmap documental.  
> **Não** descreve funcionalidades entregues.  
> **Não** altera o plano P0 aprovado, thresholds atuais, detectores ou dependências.  
> Implementação futura exige checklist de promoção (seção final).

Documentos relacionados:

- Plano / decisões P0 e estado do produto: [`ROADMAP.md`](ROADMAP.md)
- Modelo conceitual de configuração por aula: [`LESSON_CONTEXT_CONFIGURATION.md`](LESSON_CONTEXT_CONFIGURATION.md)
- Arquitetura e ética de observação: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`SECURITY_PRIVACY.md`](SECURITY_PRIVACY.md)

---

## 1. Objetivo

Registrar **todos os demais cenários reais de sala de aula** que o sistema ainda **não cobre** ou cobre **apenas parcialmente**, para que não sejam esquecidos na evolução do produto.

A documentação deve permitir responder:

1. Quais cenários reais ainda não são cobertos?
2. Quais dependem apenas de configuração?
3. Quais dependem de novos detectores?
4. Quais dependem do contexto da aula?
5. Quais não podem ser concluídos somente por visão computacional?
6. Quais devem gerar alertas / apenas registrar / ignorar conforme a aula?
7. Como evitar interpretação errada do mesmo comportamento em aulas diferentes?
8. Qual é a ordem recomendada de evolução?

---

## 2. Relação com o P0

O **P0** trata de observação assistida confiável no caminho person-first já existente: tracking corporal, identidade por continuidade, landmarks/EAR, sonolência aparente, atenção visual estimada, celular YOLO, observabilidade por módulo, atribuição de eventos, buffer ao vivo e linguagem de UI.

Este documento **não** revisa nem substitui o P0. Ele lista o que fica **fora** ou **além** do P0: contexto de aula, materiais, participação, presença temporal rica, ROIs pedagógicos, áudio, inclusão configurável, avaliações, aulas práticas, segurança, etc.

| | P0 | Este levantamento |
|--|----|-------------------|
| Código | Em evolução no runtime atual | **Proibido** nesta tarefa |
| Thresholds | Congelados / já definidos no P0 | **Não alterar** aqui |
| Novos detectores | Só o que o P0 já prevê | Apenas **nomeados** como dependência futura |
| Interpretação | Fatos + duração + qualidade | + **contexto da aula** + configuração |

---

## 3. Princípios de observação modular

### Fórmula

```text
observação visual + duração + contexto da aula + configuração + qualidade
    = interpretação do evento
```

### Separação obrigatória

| Camada | Pergunta | Exemplo |
|--------|----------|---------|
| **1. Fato observável** | O que a câmera/sensor detectou? | Celular visível; olhos fechados; pessoa perto da porta |
| **2. Evento temporal** | Por quanto tempo / com que repetição? | 12s contínuos; 3× em 5 min |
| **3. Contexto da aula** | Esperado, permitido, obrigatório, opcional ou proibido? | Prova vs pesquisa |
| **4. Interpretação** | O que o produto pode dizer? | Esperado; possível fora da atividade; inconclusivo |
| **5. Ação** | O que o sistema faz? | Ignorar; registrar; painel; alerta; revisão humana |

### Regras éticas transversais

- Não diagnosticar emoção, TDAH, ansiedade, indisciplina, fraude ou doença.
- Baixa qualidade → **inconclusivo**, nunca “aluno ruim”.
- Identidade `uncertain` → atribuição `pending` / revisão (já alinhado ao P0).
- Detectar objeto **não** confirma uso.
- Olhar para a câmera **não** é atenção pedagógica.
- Segurança / fraude: só com modelos, protocolos e revisão humana — nunca como conclusão automática.

---

## 4. Status no repositório (evidência)

Labels permitidos em **Status atual**:

`implementado` · `parcialmente implementado` · `stub` · `ausente` · `depende de configuração` · `depende de novo detector` · `depende de integração externa` · `precisa de validação`

### Resumo honesto (pós-análise do código)

| Área | Status resumido | Evidência |
|------|-----------------|-----------|
| Person track + continuidade + identity binding | implementado (+ precisa de validação multi-pessoa) | `person_tracker`, `person_track_continuity`, `identity_binding` |
| Presença / check-in facial | implementado | `presence`, enrollment, matcher |
| Landmarks / EAR / sonolência aparente | implementado | `facial_signals`, `attention_drowsiness` |
| Atenção visual (head pose) | implementado | proxy; não é gaze tracker |
| Gaze → ROI pedagógico | ausente / parcialmente (só yaw/pitch) | sem ROI quadro/professor |
| Expressão FER ONNX | implementado (experimental) | providers HSEmotion/DeepFace = stub/lazy |
| Celular YOLO | implementado (+ precisa de validação de campo) | tablet/PC = ausente |
| Pose corporal (cabeça/mãos) | parcialmente implementado | sem taxonomia sentado/em pé pedagógica completa |
| Leitura / escrita / materiais | stub / ausente | `pose_minimal.experimental_*` sempre `None` |
| Mão levantada / participação | stub / ausente | idem |
| Interação / conversa / áudio | ausente | — |
| Contexto / fase de aula | ausente | roadmap; LXP = mock |
| ROI porta / assento / quadro | ausente | — |
| Presença temporal de aula (% / saída) | ausente | “não visível ≠ fora da sala” |
| PERCLOS | parcialmente (métrica off; fora do decisor) | `experimental.perclos_*` |
| Acomodações de acessibilidade | ausente | — |
| Políticas de alerta por tipo de aula | ausente | — |
| Multicâmera com fusão | parcialmente (N pipelines) / fusão ausente | — |
| Segurança / emergência | ausente | roadmap de alto risco |
| Live buffer / timeline / validation panel | implementado | analytics + validation |
| Consent / privacy endpoints | parcialmente implementado | DPIA / base legal pendentes |

---

## 5. Perfis de aula (mínimo 30)

Para cada perfil: comportamentos **esperados**, **neutros**, **relevantes**, **potencialmente incompatíveis**, e o que é **impossível interpretar sem contexto adicional**.

| # | Perfil | Esperados | Neutros | Relevantes | Pot. incompatíveis | Sem contexto adicional |
|---|--------|-----------|---------|------------|--------------------|------------------------|
| 1 | Aula expositiva | olhar quadro/professor; sentado | micro-desvios | sonolência aparente; celular prolongado | saída longa; celular se proibido | “desatenção” só por olhar lateral breve |
| 2 | Leitura individual | cabeça baixa; livro/caderno | quietude | olhos fechados + baixa mov. | celular se proibido | “sono” só por cabeça baixa |
| 3 | Escrita / cópia | cabeça baixa; mãos na mesa | quietude | ausência prolongada | celular; conversa se proibida | escrita real sem detector de mão/material |
| 4 | Atividade individual | material; eventual pergunta | movimento local | celular; saída | — | engajamento cognitivo |
| 5 | Trabalho em dupla | orientação mútua; fala baixa | troca de material | isolamento forçado | — | “cola” vs colaboração |
| 6 | Trabalho em grupo | cluster; deslocamento curto | ruído visual | aluno isolado | — | qualidade da colaboração |
| 7 | Avaliação / prova | foco no material; quietude | cabeça baixa | celular; olhar prova alheia; saída | comunicação | fraude automática |
| 8 | Apresentação de alunos | em pé; frente; deslocamento | aplausos | celular da plateia | — | qualidade da apresentação |
| 9 | Debate | orientação a falantes; gestos | conversa lateral breve | — | — | quem “venceu” o debate |
| 10 | Aula com vídeos | olhar tela; escuro parcial | quietude | sono; celular | — | atenção ao conteúdo do vídeo |
| 11 | Aula com computador | olhar tela; mãos no teclado | postura inclinada | celular paralelo | — | produtividade |
| 12 | Aula com celular/tablet | dispositivo na mão/mesa | — | uso não previsto se outro device | — | tipo de app |
| 13 | Programação | PC; cabeça baixa; digitação | — | celular pessoal se proibido | — | “programando de verdade” |
| 14 | Robótica | em pé; ferramentas; grupo | oclusões | EPI faltando (se policy) | — | aprendizado |
| 15 | Maker | deslocamento; ferramentas | oclusões | área restrita (futuro) | — | risco sem detector dedicado |
| 16 | Laboratório | bancada; óculos; grupo | cabeça baixa | área restrita | — | experimento correto |
| 17 | Prática com deslocamento | andando; fora do assento | — | saída pela porta | — | “vagabundagem” |
| 18 | Educação física | movimento amplo; chão | — | (visão de sala típica inadequada) | — | quase tudo sem câmera adequada |
| 19 | Artística | material; postura variada | — | — | — | qualidade estética |
| 20 | Música / expressão corporal | movimento; instrumentos | — | — | — | afinação / expressão artística |
| 21 | Correção coletiva | olhar quadro; eventual fala | — | celular | — | compreensão |
| 22 | Transição | deslocamento; conversa | bagunça visual | — | — | quase tudo é ruído |
| 23 | Entrada | porta; assentos | atrasos | visitante | — | intenção do atraso |
| 24 | Saída | porta; fluxo | — | aluno isolado após | — | — |
| 25 | Intervalo | sala vazia / parcial | — | aluno sozinho (policy) | — | — |
| 26 | Híbrida / remota | (tela + sala) | — | — | — | exige integração externa |
| 27 | Atendimento individual | professor+aluno | outros quietos | — | — | conteúdo do atendimento |
| 28 | Professor auxiliar | 2 adultos | — | — | — | papéis sem ID de staff |
| 29 | Acessibilidade | acomodações | posturas atípicas | — | alertas “padrão” sem exceção | diagnóstico |
| 30 | Emergência / evacuação | fluxo porta; protocolo | — | (só humano + SOP) | alertas pedagógicos | detecção automática sem modelo |

---

## 6. Catálogo de cenários (grupos A–P)

Em cada grupo: fato → temporal → contexto → interpretação → ação (padrão sugerido). Status reflete o repo **hoje**.

### A. Presença, entrada, saída e permanência

Diferenças obrigatórias de vocabulário:

| Termo | Significado |
|-------|-------------|
| Não visível | Fora do enquadramento / oclusão — **não** implica fora da sala |
| Fora do assento | Corpo fora da ROI de assento (exige ROI) |
| Fora da região esperada | Fora de zona pedagógica configurada |
| Saída provável | Cruzou/aproximou porta com duração |
| Saída confirmada | Regra forte + ideally sensor/porta/integração |
| Ausência temporária | Fora por poucos minutos com retorno |
| Ausência prolongada | Acima do limiar de política |
| Presença parcial | % do tempo de aula acompanhado (faixas 25/50/75) |

Cenários (amostra completa do pedido): entrada antes/atrasada; saiu e retornou / não retornou; fora poucos vs muitos minutos; % aula; fora do frame; troca de lugar; outra área; saiu pela porta vs sumiu; passou na porta sem sair; várias entradas; pós-chamada; saída antecipada; durante prova; autorizado; acompanhado; visitante; professor no lugar do aluno; assento trocado.

| Interpretação típica | Ação típica |
|----------------------|-------------|
| Presente / retorno | Registrar |
| Ausência temporária | Registrar; painel se repetir |
| Ausência prolongada / % baixo | Alerta discreto ou resumo |
| Saída durante prova | Revisão humana |
| Visitante / não cadastrado | Track-only + review |
| Não visível | **Nunca** “faltou” automático |

**Status:** presença/check-in **implementado**; temporal de aula / porta / assento **ausente** (ROI **depende de novo detector**/calibração + **depende de configuração**).

### B. Posição, postura e deslocamento

Fatos: sentado, inclinado, cabeça baixa/apoiada, deitado na mesa, virado, em pé, andando, aproximação, movimento alto/baixo, oclusão, cadeira vazia, cluster, chão pedagógico, cadeira de rodas, acomodação postural.

**Não** concluir hiperatividade / ansiedade / indisciplina.

**Status:** head pose + pose parcial **parcialmente implementado**; sentado/em pé/assento/cadeira vazia **ausente** / **depende de novo detector** + ROI.

### C. Olhos, face e sinais aparentes de fadiga

Separar: sinal · repetição · duração · combinação · qualidade insuficiente · possível fadiga · provável sonolência aparente.

Casos: piscada; fechamento prolongado/repetido; parcial; um olho oculto; óculos/reflexo/escuros; esfregar olhos; mão no rosto; bocejo aparente; risada/fala; máscara; cabelo; luz; olhar baixo; cochilo; cabeça caindo; baixa mov. + olhos fechados; ângulo ruim.

**Status:** EAR + possible/probable drowsiness + oclusão mão **implementado** / parcial; bocejo/esfregar **ausente**; PERCLOS decisório **ausente** (métrica experimental parcial).

### D. Materiais pedagógicos

Objetos futuros: caderno, livro, apostila, folha, prova, caneta, lápis, borracha, régua, calculadora, robótica, maker, eletrônicos, PC, tablet, celular, fone, lab, instrumento, artístico.

Cadeia mínima para “provável leitura”: objeto visível → aberto → gaze ao objeto → permanência → (opcional) virar página — **nenhum elo sozinho basta**.

**Status:** celular **implementado**; demais **depende de novo detector**; reading/writing fields **stub**.

### E. Leitura e escrita

Precisa: objeto + mãos + movimento fino + gaze aproximado + ROI mesa + contexto.

**Status:** **ausente** / **stub**; taxonomia UI “possível leitura” **não** é detector.

### F. Celular, tablet e computador

Estados: não detectado · visível · na mesa · na mão · perto do rosto · possível/provável interação · prolongado · autorizado/obrigatório/opcional/não previsto · em avaliação · professor · compartilhado · parado · guardando · recebendo · mostrando tela · calculadora · foto da atividade · fone · olhar PC · duas telas.

Contexto define: esperado / registrar / alertar / ignorar / revisar.

**Status:** pipeline celular **implementado** (+ validação de campo); política por aula **ausente**; tablet/PC **depende de novo detector**.

### G. Atenção visual e regiões pedagógicas

ROIs: professor, quadro, tela, projetor, material, colega, porta, janela, celular, PC, área da atividade, fora da tarefa.

Cenários: olhar cada ROI; alternância normal; desvio breve vs persistente; ROI não configurada; professor em movimento; quadro mudou; gaze não confiável.

**Status:** atenção agregada **implementado**; ROIs e gaze-alvo **ausente**.

### H. Participação

Mão levantada, respondendo, apresentando, quadro, pergunta, não atendida, tempo até resposta, repetição, distribuição, nunca chamado, grupo, gestos, polegar, sinal combinado, sem mão, deslocamento, aplausos, resposta coletiva.

Separar **participação observável** de **aprendizagem**.

**Status:** hand raise **stub**; resto **ausente** (áudio = integração/detector novo).

### I. Interação entre alunos

Conversa, orientação mútua, compartilhar material, dupla/grupo, ajuda, mostrar atividade, cópia visual, paralela, prevista vs fora do momento, isolado, troca de objetos, conflito, brincadeira, contato acidental, grupo andando, oclusão mútua.

**Status:** **ausente** (visão de proximidade + possivelmente áudio).

### J. Professor e dinâmica da aula

Fala, escreve, apresenta, circula, atende, pergunta, inicia/encerra, libera celular, pede grupo, muda fase, ausente, substituto, multi-professor, auxiliar, bloqueia câmera, entra na região dos alunos.

Fase: manual · LXP · professor · inferida (futuro) · timeline.

**Status:** fase/contexto **ausente**; LXP HTTP **depende de integração externa** (mock parcial).

### K. Avaliações e provas

Início/fim; policies de material; comunicação; olhar prova alheia; saída; sem escrever longo; auxílio; entrega; tempo extra; PC; prova em grupo/oral; leitor/auxiliar.

**Nunca** classificar fraude automaticamente → revisão + “possivelmente incompatível” + evidências + contexto.

**Status:** **ausente** (depende de configuração + detectores + produto).

### L. Práticas, maker, robótica, laboratório

Em pé, deslocamento, equipe, ferramentas, celular para registro, bancada, rosto oculto, EPI, área restrita, ferramenta perigosa, fila, equipamento parado.

**Cabeça baixa / fora do assento não alertam negativamente por padrão.**

**Status:** **ausente** / alto risco parcial se misturado com métricas atuais sem contexto.

### M. Inclusão e acessibilidade

Mobilidade, cadeira de rodas, postura, movimentos repetitivos, gestos, sem contato visual, tech assistiva, tablet/fones permanentes, cuidador, baixa visão, auditivo, Libras, saídas frequentes, prova adaptada, posição especial.

Sem inferir diagnóstico. Exceções configuráveis sem excesso de dado sensível no painel.

**Status:** **ausente**.

### N. Condições ambientais e limitações técnicas

Escuro, contraluz, reflexo, câmera tremendo/movida/obstruída, lente suja, baixa res, frame drop, atraso, RTSP down, relógio errado, multicâmera/duplicata, layout mudou, distância, aglomeração, uniforme, casaco, mochila, rosto pequeno, máscara, óculos, boné, cabelo.

Resultado: ↓ confiança · inconclusivo · alerta **técnico** · recomendação — **nunca** conclusão negativa sobre o aluno.

**Status:** observation quality **implementado** (parcial frente a lista completa); multicâmera fusão **ausente**; RTSP campo **precisa de validação**.

### O. Ocorrências excepcionais e segurança (roadmap separado)

Queda, chão, aglomeração, corrida, conflito, intruso, evacuação, fumaça, objeto perigoso, sala vazia inesperada, isolado pós-aula, emergência médica aparente, pedido de ajuda.

**Não implementar nem prometer** sem modelos, validação, protocolos e revisão humana.

**Status:** **ausente** · prioridade **P3** · risco alto.

### P. Privacidade, identidade e governança

Sem biometria autorizada; visitante; incerto; swap; correção; contestação; track-only; retenção; exclusão; sem gravação; área não autorizada; papéis de acesso; export; auditoria; correção humana; mudança de modelo/threshold no semestre.

Exigir: revisão humana · histórico · provenance · justificativa · contestação · **não** usar para punição/nota automática.

**Status:** attribution/provenance/review **parcialmente / implementado** no P0; DPIA/consent formal **ausente**; acomodações **ausente**.

---

## 7. Matriz principal

Legenda de status: ver seção 4.  
“Regra temporal inicial” é **sugestão documental**, não threshold de produto.

| Módulo | Cenário | Fato observável | Contexto necessário | Regra temporal inicial | Interpretação possível | Ação sugerida | Dependências | Status atual |
|--------|---------|-----------------|---------------------|------------------------|------------------------|---------------|--------------|--------------|
| Identidade | Rosto confirmado | Face match no person track | Cadastro + consent | Instantâneo se margem ok | Identidade confirmada | Usar em analytics | Matcher | implementado |
| Identidade | Continuidade corporal | Track estável sem face | — | Enquanto corpo observável | Identidade mantida | Painel / eventos com caveat | Continuity engine | implementado |
| Identidade | Incerto | Ambiguidade / reassociação | — | Imediato ao sinal duro | Identidade pendente | Attribution pending | Identity binding | implementado |
| Presença | Check-in do dia | Face match em janela | Turma/turno | Dedup day/shift | Presente (chamada) | Registrar presença | Presence pipeline | implementado |
| Presença | Não visível ≠ falta | Track perdido / fora do frame | Layout câmera | — | Inconclusivo espacial | Não marcar falta | Política produto | parcialmente implementado |
| Presença | Entrada pela porta | Cruzamento ROI porta | ROI + horários aula | Persistência 2–5s | Entrada provável | Registrar | ROI porta | ausente |
| Presença | Saída confirmada | ROI porta + sumiço prolongado | ROI + política | Ausência > limiar | Saída / ausência | Alerta ou resumo | ROI + timeline aula | ausente |
| Presença | % acompanhado 25/50/75 | Tempo track∩identidade / duração aula | Início/fim aula | Janela da aula | Presença parcial | Resumo final | Contexto aula | depende de configuração |
| Presença | Visitante | Pessoa sem cadastro | Policy visitantes | — | Não identificado | Track-only + review | Identity | parcialmente implementado |
| Postura | Cabeça baixa | Pitch / pose | Tipo de aula | Curto vs longo | Esperado vs relevante | Ignorar ou registrar | Pose + contexto | parcialmente implementado |
| Postura | Em pé / andando | Pose/skeleton locomotor | Maker vs expositiva | Duração | Esperado vs deslocamento | Contexto decide | Detector postura | depende de novo detector |
| Postura | Cadeira vazia | Assento ROI sem pessoa | Mapa de assentos | > N s | Possível ausência local | Registrar | Seat ROI | ausente |
| Fadiga | Olhos fechados prolongados | EAR baixo | Qualidade ok | possible/probable (P0) | Sonolência aparente | Evento importante | Landmarks | implementado |
| Fadiga | Oclusão facial | Mão no rosto / pose | — | — | Face não observável | Pausar métricas face | Body pose | implementado |
| Fadiga | Bocejo aparente | Abertura boca + padrão | — | Repetição | Possível fadiga | Registrar | Detector boca dedicado | ausente |
| Fadiga | PERCLOS decisório | % olhos fechados | Validação científica | Janela 60s+ | — | Fora do decisor até validar | Experimental | parcialmente implementado |
| Atenção | Atenção estimada | Yaw/pitch estáveis | — | Janela visual_attention | high/mod/low/inconc. | Painel | Landmarks | implementado |
| Atenção | Olhar quadro/professor | Gaze ∩ ROI | ROI calibradas | Persistência | Atenção à exposição | Registrar | ROI + gaze | ausente |
| Atenção | Olhar câmera | Face frontal à cam | — | — | **Não** atenção pedagógica | Ignorar como atenção | Policy UI | depende de configuração |
| Dispositivos | Celular visível→interação | YOLO phone + assoc. | Policy aula | 5s / 12s (P0) | Possível/provável interação | Alerta se não permitido | phone_yolo | implementado |
| Dispositivos | Celular permitido | Mesmo fato | Aula com celular | — | Comportamento esperado | Ignorar ou só registrar | lesson_context | depende de configuração |
| Dispositivos | Celular em prova | Mesmo fato | assessment | Mais curto / review | Poss. incompatível | Revisão humana | Contexto | depende de configuração |
| Dispositivos | Tablet / PC | Classe detector | Aula digital | A definir | Visível / interação | Contexto | Novo detector | depende de novo detector |
| Materiais | Livro/caderno visível | Detector objeto | Leitura/escrita | — | Material presente | Registrar | Detector | depende de novo detector |
| Materiais | Provável leitura | Objeto+gaze+tempo | Leitura | Cadeia de evidências | Provável leitura | Painel / resumo | Multi-detector | ausente |
| Materiais | Provável escrita | Mãos+material+mov. fino | Escrita | Idem | Provável escrita | Idem | Multi-detector | stub |
| Participação | Mão levantada | Pose braço | Aula expositiva | Hold > 1–2s | Possível participação | Painel | Hand/pose | stub |
| Participação | Distribuição | Contagem eventos | Turma | Sessão | Métricas de vez | Resumo | Agregação | ausente |
| Interação | Orientação mútua | Pose/proximidade | Dupla/grupo | Duração | Colaboração vs paralela | Contexto decide | Detector social | ausente |
| Interação | Conversa | Áudio e/ou faces | Fase aula | Turnos | Colaboração / paralela | Contexto | Áudio | depende de novo detector |
| Professor | Fase da aula | Evento config/LXP | lesson_context | — | Mudança de interpretação | Reaplicar policies | LXP/UI | ausente |
| Professor | LXP real | Payload HTTP | Spec | — | Sync contexto | Integração | Http client | depende de integração externa |
| Avaliação | Comportamento incompatível | Fatos + policy | assessment | Evidência + duração | Para revisão | Fila humana | Contexto+detectors | ausente |
| Avaliação | Fraude automática | — | — | — | **Proibido** | Nunca | — | ausente |
| Prática | Em pé em maker | Locomotion | maker/lab | — | Esperado | Não alertar | Contexto | depende de configuração |
| Inclusão | Exceção de alerta | Flag acomodação | Política inclusão | — | Suprimir alerta X | Aplicar exceção | Config individual | ausente |
| Ambiente | Baixa qualidade | Métricas quality | — | Frame a frame | Inconclusivo | Alerta técnico | observation_quality | implementado |
| Ambiente | RTSP caiu | Watchdog | — | — | Feed indisponível | Alerta técnico | rtsp | parcialmente implementado |
| Multicâmera | Mesma pessoa 2 cams | Dois tracks | Calibração | — | Duplicata possível | Dedup futuro | Fusão | ausente |
| Segurança | Queda / conflito / fumaça | Modelos específicos | SOP escola | — | Sinal para humano | Protocolo | Modelos+legal | ausente |
| Privacidade | Sem consent biometria | Flag aluno | LGPD | — | Só track anônimo | Não match | Privacy | parcialmente implementado |
| Privacidade | Contestação de evento | Evento + provenance | Processo escola | — | Correção humana | Auditoria | Review UI | parcialmente implementado |
| Timeline | Eventos ao vivo | Buffer em memória | — | Sessão | Observação assistida | Debug/painel | live_event_buffer | implementado |
| Validação | Painel controlado | Cenários scriptados | Lab | — | QA | Usar em testes | validation/* | implementado |
| Expressão | Classe aparente | FER | — | Intervalo | Expressão aparente | Não diagnóstico | expression | implementado |
| Clima | Clima coletivo | Agregado | — | ~15s | Clima turma | Painel agregado | climate | parcialmente implementado |

*(A matriz é deliberadamente representativa; o catálogo A–P é a lista canônica completa. Novos cenários devem ser acrescentados aqui antes de qualquer issue de código.)*

---

## 8. Modelo conceitual de configuração

Ver detalhe completo em [`LESSON_CONTEXT_CONFIGURATION.md`](LESSON_CONTEXT_CONFIGURATION.md).

Ideia central: a mesma observação visual muda de ação conforme `lesson_type` + `phase` + `devices` + `alerts` + `accommodations`.

Exemplo mínimo (conceitual — **não** existe no código):

```yaml
lesson_context:
  lesson_type: "lecture"
  phase: "explanation"
  devices: { phone: { allowed: false, alert_after_seconds: 12 } }
  expected_behaviors: { leaving_seat: false, group_interaction: false }
  alerts: { probable_phone_interaction: true, leaving_seat: false }
```

---

## 9. Dependências técnicas (reaproveitar vs novo)

### Reaproveitar (já no repo)

| Bloco | Uso futuro |
|-------|------------|
| `StablePersonTrackManager` + identity binding | Presença temporal, ausência, % aula |
| `observation_quality` | Gate de todos os novos módulos |
| `phone` + association | Policy por aula sem novo detector |
| `body_pose` / landmarks | Base para mão levantada, oclusão, postura |
| `live_event_buffer` + timeline + provenance | Linha do tempo de aula e auditoria |
| `validation` panel | Corpus de regressão de novos cenários |
| LXP mock/outbox | Evoluir para HttpLXP quando houver spec |
| `modules.*.mode` (disabled/debug/shadow/production) | Gate de promoção por módulo |

### Novos detectores / fontes (não existentes)

| Dependência | Cenários desbloqueados |
|-------------|------------------------|
| ROI editor (porta, quadro, professor, assentos, mesa) | Presença espacial, atenção regional, saída |
| Detector materiais (livro/caderno/folha/…) | Leitura/escrita |
| Hand raise / hand landmarks pedagógicos | Participação |
| Tablet / laptop classes | Aulas digitais |
| Proximidade / orientação social | Interação |
| Áudio / diarização | Conversa, turnos, professor falando |
| Mapa de assentos | Cadeira vazia, troca de lugar |
| Acomodações store | Inclusão |
| Modelos de segurança | Grupo O (P3) |
| Fusão multicâmera | Duplicatas / cobertura |

### Só configuração / produto (sem detector novo)

- Celular permitido vs proibido vs obrigatório  
- Desligar alerta de “fora do assento” / “cabeça baixa” por perfil  
- Fase da aula manual  
- O que vai para painel vs resumo vs ignore  
- Copy ética da UI  

### Só visão insuficiente

- Aprendizagem / compreensão  
- Fraude com certeza  
- Diagnóstico clínico ou socioemocional  
- Conteúdo da tela do celular  
- Intenção (“quer participar”)  
- Maioria dos cenários de Ed. Física / música sem sensor adequado  

---

## 10. Priorização sugerida

Classificação após checar dependências e risco (não aceitar lista “bonita” automaticamente).

### P1 — Alto valor e viabilidade próxima

| Item | Por quê | Risco | Dependência |
|------|---------|-------|-------------|
| `lesson_context` mínimo (tipo + fase + phone policy) | Desambigua celular/cabeça baixa/assento sem novos pesos | Baixo se só config | Produto + UI/LXP leve |
| Alertas condicionados a `devices.phone.allowed` | Reusa detector atual | Baixo | Config |
| Timeline de aula (início/fim/fase) sobre buffer existente | Base para % presença e resumo | Baixo | Config tempos |
| ROI porta (calibração) + ausência temporal honest | Entrada/saída **provável** sem afirmar “fora da escola” | Médio (FP porta) | ROI tool |
| Resumo de aula (agregar eventos já emitidos) | Valor pedagógico sem novos CV | Baixo | Agregação |
| Regras de duração já existentes expostas por política | Clareza operacional | Baixo | Docs + config |
| ROI professor/quadro/material (após porta) | Atenção regional | Médio (gaze fraco) | ROI + melhorar gaze |
| Leitura/escrita **só após** detector material + mãos | Alto valor, mas **não** antes do detector | Alto FP se prematuro | Novo detector |
| Mão levantada | Valor claro; pose já parcial | Médio | Completar pose/hands |

**Adiado dentro de P1 até evidência:** leitura/escrita e mão levantada entram em backlog P1 **condicionado** a detector — não como “próximo commit”.

### P2 — Multimodal e pedagógico

- Fase via LXP HTTP (spec)  
- Interação entre alunos (proximidade)  
- Participação agregada  
- Áudio / turnos de fala  
- Atividades práticas com policies específicas  
- Comparações por etapa da aula  
- Tablet/PC  
- Acomodações (flags)  

### P3 — Avançado ou alto risco

- Segurança / emergência / conflito  
- Fraude em avaliação (mesmo “semântica suave” exige jurídico)  
- Inferências complexas (cola, engajamento profundo)  
- Acessibilidade com modelos específicos  
- Multicâmera com identidade global  
- Integrações institucionais amplas  

---

## 11. Riscos e limitações

| Risco | Mitigação documental |
|-------|----------------------|
| Mesmo fato, aula diferente, alerta errado | Sempre passar por `lesson_context` antes da ação |
| “Não visível” → falta | Vocabulário A obrigatório |
| Cabeça baixa → sono | Só com olhos + duração + qualidade (+ contexto) |
| Celular → uso confirmado | Já proibido no P0; manter |
| Detector material → “está estudando” | Cadeia de evidências |
| Segurança “demo” | Não prometer; P3 |
| Thresholds alterados no semestre | Provenance + aprovação |
| Dados sensíveis de inclusão no painel | Flags opacas |
| Dual-path legado | Novos módulos só no person-first oficial |

---

## 12. Privacidade e governança

- Revisão humana para eventos sensíveis e avaliações.  
- Histórico de alterações de config e thresholds.  
- Provenance em todo evento interpretado.  
- Contestação e correção com trilha.  
- Sem uso automático para punição ou nota.  
- Biometria só com base legal; visitante sem match.  
- Gravação off por default (alinhado a `privacy.*`).  
- Este levantamento **não** autoriza novos processamentos — só nomeia requisitos futuros.

---

## 13. Critérios para transformar cenário documentado em funcionalidade

Um cenário **só** sai deste documento e entra no produto quando tiver **todos**:

1. Objetivo claro  
2. Fato observável definido  
3. Contexto necessário definido  
4. Detector ou fonte de dados disponível  
5. Regra temporal  
6. Regra de qualidade  
7. Estados possíveis  
8. Condição inconclusiva  
9. Tratamento de oclusão  
10. Risco de falso positivo documentado  
11. Testes automatizados  
12. Validação com vídeos reais  
13. Copy da interface  
14. Política de alerta  
15. Política de armazenamento  
16. Revisão humana, quando necessária  
17. Aprovação de produto  

Sem isso: permanece aqui como **backlog documental**.

---

## 14. Checklist para futuras implementações

- [ ] Atualizar status na matriz deste arquivo  
- [ ] Não misturar com mudanças de threshold P0 sem RF separada  
- [ ] Shadow mode antes de production (`modules.*.mode`)  
- [ ] Cenário no painel de validação quando aplicável  
- [ ] Docs de TESTING + copy ética  
- [ ] Decisão de produto registrada no ROADMAP  
- [ ] Se envolver biometria/áudio/segurança: SECURITY_PRIVACY + jurídico  

---

## 15. Itens que exigem decisão de produto

1. Quem define `lesson_type` / `phase` no dia a dia (professor, coordenação, LXP)?  
2. Celular em aula “com pesquisa”: registrar sempre ou só alertar se prolongado?  
3. Ausência: a partir de quantos minutos vira alerta vs só resumo?  
4. % de presença acompanhada: comunicar à escola com qual linguagem?  
5. ROI: ferramenta interna ou calibração por visita técnica?  
6. Avaliações: a escola quer fila de revisão ou apenas registro?  
7. Áudio: permitido pela política da escola?  
8. Acomodações: qual granularidade mínima sem estigmatizar?  
9. Multicâmera: uma sala / uma câmera no piloto ou cobertura ampla?  
10. Segurança: fica **fora** do produto pedagógico por quanto tempo?  
11. Relação com nota / disciplina: compromisso público de **não** automatizar punição?  
12. Vocabulário oficial dos 30 perfis (IDs estáveis para LXP)?  

---

## 16. Ordem recomendada de evolução (síntese)

1. Fechar validação de campo do que o P0 já entrega (multi-pessoa, RTSP, phone calib).  
2. Introduzir **apenas configuração** `lesson_context` (phone policy + fase + alert toggles).  
3. Timeline de aula + resumo a partir de eventos existentes.  
4. ROI porta + presença temporal honesta.  
5. ROIs pedagógicos + melhorar atenção regional.  
6. Detectores de material / mão levantada com shadow.  
7. LXP HTTP quando houver spec.  
8. Interação / áudio (P2).  
9. Segurança e fraude (P3, se houver mandato institucional).  

---

## Histórico

| Data | Nota |
|------|------|
| 2026-07-27 | Criação do levantamento complementar ao P0 (somente documentação). |
