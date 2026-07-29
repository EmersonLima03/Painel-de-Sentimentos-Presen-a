# Entrega TRI — Módulo de Expressões Aparentes e Dashboard

**Status:** implementação de fechamento pronta para validação manual + evidências + versão estável  
**Branch de referência:** `feat/painel-de-sentimentos`  
**Data:** 2026-07-29

Nome técnico do módulo entregue: **Expressões Aparentes**, **Clima visual aparente** e **Atenção visual estimada** + dashboard unificado.  
Evite chamar o componente de “modelo de sentimentos” fora do enunciado literal abaixo.

---

## Disclaimer (obrigatório)

O sistema estima **expressões faciais aparentes** e sinais visuais observáveis. **Não** identifica sentimentos internos, **não** realiza diagnóstico e **não** comprova engajamento ou aprendizagem.

---

## Objetivo original do TRI (literal)

> Desenvolver o modelo de IA para extração de sentimentos em tempo real e criar a interface gráfica unificada para relatórios de engajamento e humor.

## Interpretação técnica adotada

| Termo do enunciado | Interpretação no produto |
|--------------------|---------------------------|
| Sentimentos / humor | **Expressão aparente** normalizada + **clima visual aparente** da turma |
| Engajamento | **Atenção visual estimada** + tempos observáveis (não nota nem aprendizagem) |
| Tempo real | Pipeline edge + dashboard Ao vivo (~2 s de poll) |
| Relatórios | Aba **Relatório da aula** (sessão acumulada) |

---

## Arquitetura (resumo)

```text
Frame (webcam/RTSP/demo)
  → Person track + face
  → FerOnnxProvider (perfil TRI) → fer_onnx.py → emotion-ferplus-8.onnx
  → Normalização ética (positive|neutral|negative|surprise|inconclusive)
  → Atenção / qualidade / eventos (RealtimeAnalyticsEngine)
  → LiveSessionStore
  → API /api/v1/* + WebSocket
  → Dashboard React (/dashboard): Ao vivo + Relatório
```

**Presença** (check-in facial) permanece isolada. `/debug/vision` não foi alterado neste fechamento.

---

## Provider utilizado (TRI) — caminho real confirmado

| Item | Valor |
|------|--------|
| Provider de entrega | `fer_onnx` |
| Classe / arquivo | [`app/vision/expressions/fer_onnx_provider.py`](../app/vision/expressions/fer_onnx_provider.py) (`FerOnnxProvider`) |
| Inferência ONNX | [`app/vision/fer_onnx.py`](../app/vision/fer_onnx.py) |
| Modelo | `data/models/emotion-ferplus-8.onnx` |
| Factory | `create_expression_provider("fer_onnx")` em [`expressions/__init__.py`](../app/vision/expressions/__init__.py) |

**Nota histórica:** `fer_legacy_provider.py` (Mini-XCEPTION / eventual ONNX via health legado) **não** é o caminho oficial da entrega TRI. Continua disponível para experimentos; o perfil TRI aponta **somente** para `fer_onnx`.

Modo de módulo no perfil TRI: `debug` (produção longitudinal exige aprovação à parte).

---

## Ativação confirmada no loader

Implementado em [`app/config.py`](../app/config.py):

| Mecanismo | Variável / arquivo | Status |
|-----------|-------------------|--------|
| Overlay | `PRESENCA_CONFIG_OVERLAY=config.tri.yaml` | **Sim** — mesclado **depois** de `config.yaml` |
| Base alternativa | `PRESENCA_CONFIG` / `CONFIG_YAML` | Sim |
| Env expressão | `EXPRESSION_PROVIDER` | **Sim** (nome exato) |
| Env cadeia | `EXPRESSION_FALLBACK_CHAIN` | **Sim** (nome exato) |
| Env modo | `MODULE_EXPRESSION_MODE` | **Sim** (nome exato) |
| Log | evento `settings_loaded` | **Sim** — paths resolvidos, missing, provider, chain, mode, overlay |

Arquivo overlay: [`config.tri.yaml`](../config.tri.yaml) (existe na raiz do projeto).

Se apenas `EXPRESSION_PROVIDER=fer_onnx` for setado (sem chain), o loader força `EXPRESSION_FALLBACK_CHAIN=fer_onnx` para **evitar fallback silencioso** para HSEmotion.

No boot do analytics: log `expression_provider_selected` (sucesso) ou `expression_provider_fallback` / `expression_provider_unavailable`.

### Opção A — overlay (recomendado)

```powershell
cd Presenca
.\venv\Scripts\Activate.ps1
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"   # ou "demo"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Confira no log: `settings_loaded` com `config.tri.yaml` e `expression_provider=fer_onnx`.

### Opção B — variáveis de ambiente

```powershell
$env:EXPRESSION_PROVIDER = "fer_onnx"
$env:EXPRESSION_FALLBACK_CHAIN = "fer_onnx"
$env:MODULE_EXPRESSION_MODE = "debug"
```

O `config.yaml` padrão **não** é alterado (HSEmotion experimental permanece para outros usos).

---

## Estados produzidos

### Expressão aparente

`positive` · `neutral` · `negative` · `surprise` · `inconclusive`

### Atenção visual estimada

`high` · `moderate` · `low` · `inconclusive`

### Qualidade / clima

Baixa qualidade → expressão/atenção **inconclusivas**.  
**Clima visual aparente** agrega amostras conclusivas (~15 s) + histórico na sessão.

---

## Telas do dashboard

| Tela | Conteúdo |
|------|----------|
| **Ao vivo** | KPIs; grade com **Expressão aparente** compacta; clique → atenção, confiança, amostras, observabilidade; clima; eventos; timeline |
| **Relatório** | Resumo / Presença / Sinais / Qualidade / Clima / Por aluno |
| Escola / Histórico | Fora do TRI |
| `/debug/vision` | Sem regressão intencional |

---

## Checklist manual reproduzível

### Cenário 1 — Rosto frontal (gate objetivo, ~20 s)

Com rosto frontal, iluminado e observável durante **20 segundos**:

- `expression.status` = `available` (no track / health);
- `sample_count` aumenta;
- `model_name` = `emotion-ferplus-8`;
- pelo menos **uma** amostra conclusiva é publicada (`smoothed_state` ≠ `inconclusive` em algum momento, ou `is_conclusive`);
- `confidence` permanece entre **0 e 1**;
- nenhuma exceção de inferência é registrada no log.

Não exige acertar uma emoção específica (sorriso ≠ obrigatório).

### Cenário 2 — Sorriso / mudança (**complementar**)

Novas inferências; UI pode atualizar; clima pode refletir amostras. **Sem** promessa científica.

### Cenário 3 — Rosto coberto (**obrigatório**)

Queda de observabilidade; `expression` inconclusiva; atenção inconclusiva quando necessário; nenhuma emoção inventada.

### Cenário 4 — Cabeça baixa (**obrigatório**)

Sinal/descrição de cabeça baixa; **não** sono automático; expressão inconclusiva se rosto inadequado.

### Cenário 5 — Relatório (**obrigatório**)

Presente; tempo observável; atenção; expressão aparente; clima coletivo; timeline; eventos; períodos inconclusivos.

---

## Evidências

### Obrigatórias

- [ ] Provider e modelo disponíveis (`fer_onnx` / `emotion-ferplus-8`)
- [ ] Teste `pytest … -m tri` verde **sem skip** no ambiente oficial
- [ ] Ao vivo com expressão aparente (grade + detalhe)
- [ ] Oclusão → inconclusivo
- [ ] Relatório com expressão, atenção e clima
- [ ] `npm run typecheck`
- [ ] `npm run build`
- [ ] Suíte relevante verde
- [ ] Documentação atualizada (este arquivo + `ESTAGIO_ATUAL`)
- [ ] Log `settings_loaded` / `expression_provider_selected` anexado ou citado
- [ ] Commit ou tag estável registrado

### Complementares (não bloqueiam o fechamento técnico)

- [ ] Vídeo demonstrativo
- [ ] Sorriso mudando a expressão
- [ ] Comparação entre cenários
- [ ] Gravação mais longa
- [ ] Intelbras
- [ ] Múltiplas pessoas

---

## Comandos

```powershell
cd Presenca
.\venv\Scripts\Activate.ps1
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Gate TRI completo (ONNX + overlay/env) — sem skip no ambiente oficial
pytest tests/test_fer_onnx.py tests/test_tri_config_overlay.py -m tri -q

# Suíte relevante
pytest tests/test_fer_onnx.py tests/test_tri_config_overlay.py tests/test_emotion_mapping.py tests/test_session_aggregator.py tests/test_live_session_dashboard.py tests/test_demo_mode.py tests/test_occlusion_hysteresis.py -q
```

```powershell
cd frontend
npm run typecheck
npm run build
```

Marcador Pytest registrado em [`pytest.ini`](../pytest.ini):

```ini
markers =
    tri: testes obrigatórios para o fechamento do TRI
```

---

## Limitações

- Estimativa visual; sem diagnóstico.
- Sem validação longitudinal para produção ampla.
- Relatório live em memória (restart perde agregação).
- Multi-escola / histórico / LXP / Supabase / P1 contexto: pós-TRI.
- Acurácia de expressão não garantida.

---

## Itens pós-TRI

1. Evidências obrigatórias + commit/tag  
2. P1 Contexto pedagógico  
3. Persistência / histórico real  
4. Supabase / multi-escola  
5. Campo Intelbras / multi-pessoa  
6. `modules.expression: production` só com aprovação longitudinal  

---

## Gate oficial de conclusão

O fechamento do TRI será considerado **concluído** somente quando:

- [ ] O arquivo `emotion-ferplus-8.onnx` estiver presente.
- [ ] O provider `fer_onnx` carregar **sem fallback silencioso**.
- [ ] `expression.status` estiver `available` em condição observável.
- [ ] `model_name` informar `emotion-ferplus-8`.
- [ ] `sample_count` aumentar durante a execução.
- [ ] Pelo menos uma amostra conclusiva for produzida em cenário controlado.
- [ ] Baixa observabilidade produzir `expression=inconclusive`.
- [ ] Atenção e expressão aparecerem no dashboard Ao vivo.
- [ ] O clima visual aparente aparecer quando houver amostras suficientes.
- [ ] O Relatório da aula apresentar expressão, atenção, clima e períodos inconclusivos.
- [ ] Demo e RTSP utilizarem bancos e identificações de simulação corretamente separados.
- [ ] O teste marcado como `tri` passar **sem skip** no ambiente oficial.
- [ ] A suíte relevante passar.
- [ ] `npm run typecheck` passar.
- [ ] `npm run build` passar.
- [ ] `/debug/vision` e presença permanecerem sem regressões.
- [ ] Evidências forem anexadas a este documento (seção Evidências).
- [ ] Commit ou tag estável for registrado.
