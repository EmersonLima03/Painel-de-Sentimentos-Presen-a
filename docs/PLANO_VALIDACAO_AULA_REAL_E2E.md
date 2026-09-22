# Plano de Validação — Aula Real End-to-End

**Documento operacional (sem alteração de código)**  
**Data:** 2026-09-22  
**Ambiente-alvo:** worktree produção `_facial_enroll_prod` + Cloudflare `presenca.sistemadulino.com.br`  
**Pergunta a responder:** *Se uma escola fosse instalada amanhã, conseguimos executar uma aula completa?*

---

## 0. Pré-condições (antes de começar o roteiro)

| Item | Como confirmar | Status esperado |
|------|----------------|-----------------|
| Mini-PC / notebook com USB ou RTSP | Câmera física ligada | OK físico |
| Boot Edge+M2 | `.\scripts\boot_edge_m2.ps1` → BUILD/EDGE/M2/DASHBOARD/TUNNEL OK | Servidores up |
| Tunnel Cloudflare | HTTPS dashboard abre | `https://presenca.sistemadulino.com.br/dashboard` |
| Matcher com embeddings | Emerson reconhecido em Debug Vision (já observado ~0,81–0,89) | Identidade permanente |
| Contas smoke | `.env.smoke.local` | gestor / professor |

**Boot (técnico):**

```powershell
cd "...\_facial_enroll_prod"
.\scripts\boot_edge_m2.ps1 -PublicBaseUrl "https://presenca.sistemadulino.com.br"
```

**Health mínimo:**

| URL | Critério |
|-----|----------|
| `http://127.0.0.1:8000/health` | 200 |
| `http://127.0.0.1:8000/m2/healthz` | `ok`, `roster_source=supabase`, `test_hooks=false` |
| `https://presenca.sistemadulino.com.br/dashboard` | Login React |

---

## 1. Cenário da simulação

### Elenco (lab atual)

| Papel | Quem | Conta / ID |
|-------|------|------------|
| **Escola** | Escola E2E Real | `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1` |
| **Turma** | Turma Teste 1 | `bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1` |
| **Aluno** | Emerson Lima (**você**) | UUID `60e71db8-c88b-4569-8fcd-4624f19a5ee9` · `edge_student_key=p01` · `external_ref=ext-stu-001` |
| **Gestor** | Conta demo | `gestor.demo@sentimentos.test` |
| **Professor** | Conta demo (se usar fluxo “Minhas aulas”) | `professor.demo@sentimentos.test` |
| **Técnico / ops** | Você (mesmo corpo, outro chapéu) | localhost Debug Vision + logs |

### Sistemas que participam

| Sistema | Porta / URL | Papel na aula |
|---------|-------------|----------------|
| Cloudflare Tunnel | `presenca.sistemadulino.com.br` | HTTPS público |
| Edge | `:8000` | Visão, presença, dashboard, proxy M2, LXP client |
| M2 | `:8766` (só loopback) | Cadastro facial (pré-aula) |
| Supabase A | projeto presença | Auth, escolas, alunos, status facial ops |
| Supabase B | LXP Simulator | Recebe attendance (homolog) — **sem biometria** |
| SQLite Edge | `data/dulino_edge.db` | `face_embeddings`, eventos locais, outbox |

### Quem faz o quê (visão rápida)

| Momento | Responsável | Tela / ação | Resultado esperado |
|---------|-------------|-------------|--------------------|
| Subir stack | Técnico | boot + tunnel | Health verde |
| Conferir turma/face | Gestor | Dashboard → Admin + Cadastro facial | Emerson **Cadastrado** |
| Iniciar aula | Gestor ou Professor | Administração / Minhas aulas → iniciar | Sessão AO VIVO |
| Ser reconhecido | Aluno (você) | Frente à USB `cam-web` | Match `p01` / Emerson |
| Monitorar | Técnico | Ao vivo + Debug Vision | Presente + overlay |
| Conferir cloud | Técnico | Supabase A / B + LXP homolog | Evento sem embedding |

---

## 2. Fluxo do gestor antes da aula

### 2.1 Login do gestor

| Campo | Valor |
|-------|--------|
| **Quem** | Gestor |
| **URL/tela** | `https://presenca.sistemadulino.com.br/dashboard` → Login |
| **Sistema** | Dashboard React + Supabase Auth (A) |
| **API** | Supabase Auth `signInWithPassword` |
| **Banco** | Supabase A `auth.users` + `profiles` + `memberships` |
| **Sucesso** | Sidebar com Ao vivo, Cadastro facial, Administração; e-mail `gestor.demo@…` visível |

### 2.2 Seleção da escola

| Campo | Valor |
|-------|--------|
| **Quem** | Gestor (ou ROOT) |
| **URL/tela** | Context de escola ativa no Dashboard (membership) / Administração |
| **Sistema** | AuthContext RBAC |
| **API** | PostgREST `memberships`, `schools` |
| **Banco** | Supabase A `schools`, `memberships` |
| **Sucesso** | Escola ativa = **Escola E2E Real** |

### 2.3 Seleção da turma

| Campo | Valor |
|-------|--------|
| **Quem** | Gestor |
| **URL/tela** | Administração → Turmas / Alunos / Aulas |
| **API** | `class_groups`, `enrollments` |
| **Banco** | Supabase A |
| **Sucesso** | **Turma Teste 1** listada e selecionável |

### 2.4 Conferência dos alunos

| Campo | Valor |
|-------|--------|
| **Quem** | Gestor |
| **URL/tela** | Administração → **Alunos** |
| **API** | `students`, `enrollments` |
| **Banco** | Supabase A |
| **Sucesso** | Emerson Lima presente; matrícula **active** na Turma Teste 1; `edge_student_key` preenchido (`p01` ou auto `e_…`); `external_ref=ext-stu-001` se for validar LXP |

### 2.5 Conferência do cadastro facial

| Campo | Valor |
|-------|--------|
| **Quem** | Gestor |
| **URL/tela** | Dashboard → **Cadastro facial** (iframe M2 via `srcDoc`) |
| **API** | `POST /dashboard/api/m2-gestor-gate` · `GET /api/gestor/schools` · `GET /api/gestor/class-facial-status` |
| **Bancos** | Edge SQLite `face_embeddings` + M2 status + mirror Supabase A `facial_student_enrollments` |
| **Sucesso** | Escola E2E Real → Turma Teste 1 → Emerson **CADASTRADO** (ou Recadastrar). Se cloud mostrar `failed` mas Debug Vision reconhecer: anotar como **AMARELO** (espelho ops vs embeddings locais). |

### 2.6 Configuração da aula

| Campo | Valor |
|-------|--------|
| **Quem** | Gestor ou Professor |
| **URL/tela** | Administração → **Aulas** / “Minhas aulas de hoje” → criar ou selecionar ocorrência → **Iniciar** |
| **API** | lesson context / session bind (Edge + Supabase A `lesson_occurrences` quando aplicável) |
| **Banco** | Supabase A (aula planejada) + Edge session local |
| **Sucesso** | Dashboard **Ao vivo** mostra sessão iniciada (não “Nenhuma aula iniciada”) |

### 2.7 Preparação da câmera

| Campo | Valor |
|-------|--------|
| **Quem** | Técnico (+ Gestor confere preview) |
| **URL/tela** | `http://127.0.0.1:8000/debug/vision` (localhost) · preview Ao vivo `cam-web` |
| **API** | `/debug/mjpeg?camera_id=cam-web` · `/debug/overlay_matches` · overview câmeras |
| **Config** | `config.yaml` → `cam-web` com índice USB (lab: `"2"` XWF) |
| **Sucesso** | Preview com imagem real (não preta); `cameras.online ≥ 1`; overlay eventualmente com face |

---

## 3. Fluxo da aula ao vivo

### 3.1 Pipeline esperado

```
Câmera USB/RTSP (cam-web)
    ↓
Edge Vision (YuNet detecção)
    ↓
Alinhamento / embedding FaceNet
    ↓
FAISS matcher (student_id = edge_student_key, ex. p01)
    ↓
Identificação (Emerson Lima)
    ↓
Presença / check-in (sessão ativa)
    ↓
Dashboard Ao vivo + (opcional) outbox → Supabase A → LXP Simulator B
```

### 3.2 Passo a passo operacional

| # | Responsável | Ação | Onde | Resultado esperado |
|---|-------------|------|------|--------------------|
| 1 | Gestor/Professor | Inicia aula | Administração / Minhas aulas | Sessão `active` no Ao vivo |
| 2 | Técnico | Confirma câmera | Debug Vision | MJPEG fluido, faces ≥ 0 |
| 3 | Aluno (você) | Posiciona rosto na USB ~1–2 m | Sala / webcam | Detecção YuNet |
| 4 | Sistema | Match FAISS | Edge | `student_id=p01`, `full_name=Emerson Lima`, `unknown=false` |
| 5 | Sistema | Presença | Edge session | Presentes incrementa / check-in |
| 6 | Gestor | Observa painel | **Ao vivo** | Nome/contagem; timeline se habilitada |
| 7 | Técnico | Amostra confiança | `/debug/overlay_matches` | Confiança tipicamente ≥ ~0,75 (lab: 0,81–0,89) |

### 3.3 Critérios de sucesso da identificação

| Critério | Como ver | Pass |
|----------|----------|------|
| Aluno reconhecido | Overlay / overlay_matches `label=Emerson Lima` | Sim |
| Chave correta | `student_id=p01` | Sim |
| Não-unknown | `unknown=false` | Sim |
| Presença gerada | Ao vivo PRESENTES ≥ 1 **ou** evento local/outbox | Conferir na execução |
| Timeline | Painel Ao vivo / histórico | Conferir na execução |
| Eventos persistidos | SQLite Edge +/ou ingest Supabase A | Conferir na execução |

---

## 4. Validação TRI

### 4.1 Quando o TRI entra

| Momento | Descrição |
|---------|-----------|
| Boot | Overlay TRI (`config.tri.yaml` / `PRESENCA_CONFIG_OVERLAY`) carregado no Edge **sem** alterar `app/vision` core em missões de produto |
| Runtime | Após detecção/track de pessoa/rosto, módulos de expressão / engajamento aparente / sinais pedagógicos rodam em paralelo ou em cascata configurada |
| Dashboard | Indicadores de engajamento / atenção **aparente** no Ao vivo (disclaimer: estimativa, não diagnóstico) |

### 4.2 O que validar (sem quebrar facial)

| Check | Como | Sucesso |
|-------|------|---------|
| Pipeline facial intacto | Match `p01` continua após vários minutos | Reconhecimento estável |
| TRI não zera faces | `faces_last` / overlay ainda mostram Emerson | Sem regressão |
| Dados TRI no overview | `/dashboard/api/overview` → engagement / observability | Campos presentes sem erro 500 |
| Disclaimer | UI Ao vivo | Texto de estimativa visível |
| Interferência | Alternar olhar / cabeça | Match facial permanece; TRI pode mudar estado (attentive etc.) |

### 4.3 Onde aparece no Dashboard

- **Ao vivo:** cards de engajamento / atenção / alertas leves (quando sessão ativa).
- **Relatórios / Histórico:** agregados se a sessão gerou pontos (validar na corrida).
- **Debug Vision:** pode expor sinais técnicos; facial overlay é a fonte da verdade do nome.

**Regra de aceite TRI nesta simulação:** *não precisa “nota pedagógica perfeita”; precisa provar que TRI não derruba reconhecimento nem o Ao vivo.*

---

## 5. Validação do Dashboard

### 5.1 Ao vivo

| Item | Critério de sucesso |
|------|---------------------|
| Presentes | ≥ 1 quando você está na câmera (ou evidência de check-in) |
| Câmera | Online / sem erro persistente |
| Timeline | Atualiza com eventos da sessão **ou** documentar se vazia (AMARELO) |
| Indicadores | Sem tela quebrada; números coerentes |

### 5.2 Relatórios / Histórico

| Item | Critério |
|------|----------|
| Dados gerados | Sessão aparece após encerrar ou durante |
| Histórico | Consulta sem 500; filtro por escola/turma se existir |

### 5.3 Cadastro facial

| Item | Critério |
|------|----------|
| Status Emerson | **Cadastrado** no gestor |
| Ação | Botão **Recadastrar** (não “Cadastrar rosto”) |

### 5.4 Debug Vision (localhost)

| Item | Critério |
|------|----------|
| Overlay | Caixa no rosto |
| Nome | Emerson Lima |
| Confiança | Numérica estável (anotar min/max da sessão) |
| URL | `http://127.0.0.1:8000/debug/vision` |

---

## 6. Validação Supabase

### 6.1 Supabase A (produto)

| Objeto | O que checar | Sucesso |
|--------|--------------|---------|
| `schools` | Escola E2E Real | 1 linha |
| `class_groups` | Turma Teste 1 | 1 linha |
| `students` | Emerson + `edge_student_key` + `external_ref` | Preenchidos |
| `enrollments` | active na turma | 1 |
| `facial_student_enrollments` | status facial | Preferível `enrolled`; se `failed` com match local → AMARELO (resync) |
| `profiles` / `memberships` | gestor na escola | OK |
| Eventos / ingest | Tabelas ou função ingest usadas pelo Edge | Linhas novas na janela da aula **ou** fila local pending |

**Proibido em A:** blobs de embedding / templates biométricos (ficam no Edge).

### 6.2 Supabase B (LXP Simulator)

| Check | Sucesso |
|-------|---------|
| Somente attendance / domínio LXP | Sem colunas de face embedding |
| Aluno mapeado | `ext-stu-001` (ou ref configurada) |
| Isolamento | M2 **não** escreve em B |
| Sync | Após presença, evento chega no Simulator (ver §7) |

---

## 7. Validação LXP Simulator

### 7.1 Cadeia

```
Presença no Edge (student_id=p01)
    ↓
Mapa lesson_context: p01 → ext-stu-001
    ↓
Cliente LXP (MODULE_LXP_MODE=simulator)
    ↓
Supabase B Functions attendance-events
    ↓
Registro no Simulator / painel LXP Homologação
```

### 7.2 Roteiro

| # | Ação | Onde | Sucesso |
|---|------|------|---------|
| 1 | Confirmar env | Edge boot | `MODULE_LXP_MODE=simulator` (ou equivalente do boot piloto) |
| 2 | Confirmar mapa | Admin Alunos | `p01` ↔ `ext-stu-001` |
| 3 | Gerar presença | Você na câmera com aula ativa | Check-in local |
| 4 | Abrir homolog | Dashboard → **LXP Homologação** | Evento do aluno/turma |
| 5 | (Opcional) SQL/API B | Projeto Simulator | Linha attendance sem biometria |

### 7.3 Critérios

| Campo | Esperado |
|-------|----------|
| Aluno LXP | `ext-stu-001` / Emerson no Simulator |
| Turma / escola | IDs de homolog coerentes com o mapa |
| Formato | Contrato attendance (sem embedding) |
| Falha de rede | Outbox pending no Edge (não perde silencioso) — se testar offline, marcar resultado |

---

## 8. Teste de restart

### 8.1 Procedimento

1. Encerrar Edge + M2 (parar processos `:8000` / `:8766` ou CTRL+C no boot).
2. Subir de novo: `.\scripts\boot_edge_m2.ps1`.
3. (Tunnel Cloudflare deve permanecer rodando à parte.)

### 8.2 Checklist pós-restart

| Item | Como | Sucesso |
|------|------|---------|
| Login | HTTPS dashboard | Entra com mesmo usuário |
| Dashboard React | `/dashboard` | Sem 503 / sem legado |
| M2 | `/m2/healthz` | ok |
| Embeddings | SQLite count `face_embeddings` where `student_id='p01'` | ≥ 1 (lab: 4) |
| Matcher | `POST /internal/matcher/reload` se necessário + Debug Vision | Emerson reconhecido de novo |
| Cadastro facial | Status Cadastrado | Mantém |
| Ao vivo | Nova sessão se a anterior morreu | Consegue iniciar de novo |

---

## 9. Checklist final (preencher na execução)

Legenda de **Status prévio** (antes da corrida manual):

- **VERDE** = já evidenciado neste lab  
- **AMARELO** = precisa teste manual nesta sessão  
- **VERMELHO** = não implementado / fora de escopo piloto

| Etapa | Responsável | Resultado esperado | Resultado obtido | Status prévio | Status execução |
|-------|-------------|--------------------|------------------|---------------|-----------------|
| Boot Edge+M2 | Técnico | Health + tunnel OK | | VERDE | |
| Login gestor | Gestor | Sessão Auth | | VERDE | |
| Escola / turma | Gestor | E2E Real / Turma Teste 1 | | VERDE | |
| Aluno + mapa Edge/LXP | Gestor | Emerson `p01` / `ext-stu-001` | | VERDE | |
| Cadastro facial permanente | Gestor/Aluno | Embeddings + match | | VERDE | |
| Auto `edge_student_key` | Sistema | Novos alunos sem digitação | | VERDE (missão chave) | |
| Preview câmera | Técnico | MJPEG `cam-web` | | VERDE | |
| Iniciar aula / sessão | Gestor/Prof | Ao vivo “sessão iniciada” | | AMARELO | |
| Reconhecimento na aula | Aluno+Edge | Presente identificado | | AMARELO (aula formal); match Debug = VERDE | |
| TRI sem quebrar facial | Técnico | Match + overview engajamento | | AMARELO | |
| Timeline / indicadores | Gestor | Dados coerentes | | AMARELO | |
| Relatórios / Histórico | Gestor | Sessão consultável | | AMARELO | |
| Supabase A ops | Técnico | Sem biometria; status ok | | AMARELO (`facial_*` pode estar defasado) | |
| LXP Simulator B | Técnico | Attendance `ext-stu-001` | | AMARELO | |
| Restart Edge+M2 | Técnico | Reconhece de novo | | AMARELO | |
| Multi-aluno / sala cheia | — | N alunos | | VERMELHO (fora deste roteiro) | |
| Câmera IP campo | — | RTSP estável | | VERMELHO / AMARELO fraco | |
| LXP produção | — | Ambiente real | | VERMELHO | |

---

## 10. Ordem sugerida de execução (1 sessão ~45–60 min)

1. Técnico: boot + health + Debug Vision (2 min)  
2. Gestor: login → Cadastro facial (status Emerson) (3 min)  
3. Gestor/Prof: criar/iniciar aula (5 min)  
4. Aluno: 5 min contínuos na câmera; técnico anota confiança min/max  
5. Gestor: Ao vivo + Relatórios (5 min)  
6. Técnico: queries Supabase A + tela LXP Homologação (10 min)  
7. Técnico: restart + re-reconhecimento (10 min)  
8. Preencher coluna **Resultado obtido** / **Status execução**  
9. Veredito final abaixo  

---

## 11. Veredito (preencher ao final)

| Pergunta | Sim / Não / Parcial | Evidência |
|----------|---------------------|-----------|
| Conseguimos executar uma aula completa amanhã? | | |
| Bloqueador principal (se houver) | | |
| Pronto para piloto controlado 1 sala? | | |

### Critério de “aula completa” neste plano

Considerar **PASS** se:

1. Login + turma + facial Emerson OK  
2. Sessão de aula iniciada no Dashboard  
3. Reconhecimento `p01` com presença ou evidência clara no Ao vivo/Debug  
4. TRI não derruba o facial  
5. Restart mantém reconhecimento  
6. LXP Simulator: **desejável**; se falhar com facial/aula OK → piloto **com ressalva** (homolog LXP), não bloqueio absoluto do reconhecimento  

---

## 12. Referências rápidas

| Recurso | Valor |
|---------|--------|
| Dashboard | `https://presenca.sistemadulino.com.br/dashboard` |
| Debug Vision | `http://127.0.0.1:8000/debug/vision` |
| Overlay matches | `http://127.0.0.1:8000/debug/overlay_matches?camera_id=cam-web` |
| Boot | `.\scripts\boot_edge_m2.ps1` |
| Conta gestor | `gestor.demo@sentimentos.test` |
| Aluno | Emerson Lima / `p01` / `ext-stu-001` |
| Docs relacionados | `docs/OPERACAO_BOOT_PRODUCAO.md`, `docs/FACIAL_ENROLLMENT_PRODUCTION.md` |

---

*Fim do plano. Nenhuma alteração de código associada a este documento.*
