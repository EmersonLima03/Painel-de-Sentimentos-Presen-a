# Cadastro facial em produção (student-centric)

## Arquitetura

```
Cloudflare Named Tunnel (presenca.sistemadulino.com.br)
        ↓
Edge :8000  (M1 + M3 + TRI + Dashboard + proxy M2)
        ↓
M2 :8766 (bind 127.0.0.1 only)
```

- **Supabase A** = presença/produto + status de enrollment (`facial_student_enrollments` + `facial_enrollment_*` legado).
- **Supabase B** = LXP homologação — **nunca** recebe enrollment facial.
- Templates biométricos ficam no Edge (`face_embeddings` + FAISS). **Nunca** no Supabase.

## Fluxo do gestor

1. Dashboard → Cadastro facial
2. Seleciona escola e turma (Supabase A)
3. Vê alunos oficiais + status: Não cadastrado / Em andamento / Cadastrado
4. **Cadastrar rosto** ou **Recadastrar** → gera convite individual
5. QR/link: `https://presenca.sistemadulino.com.br/e/<token>` (somente token opaco)

## Fluxo do aluno

`/e/<token>` → confirma identidade → câmera → frente/direita/esquerda/validate → óculos → FaceNet → conclusão

Pipeline preservado: YuNet, alignment, quality, pose, FaceNet, glasses.

## Persistência

```
FaceNet (.npy TEMP)
  → promote (enrollment_promote.py)
  → face_embeddings (SQLite Edge, student_id = edge_student_key)
  → POST http://127.0.0.1:8000/internal/matcher/reload  (loopback)
  → FAISS
```

Status produto: `facial_student_enrollments.status` = `enrolled` (dual-write SQLite + Supabase A).

## Compatibilidade

Campanhas (`facial_enrollment_campaigns/roster/sessions`) continuam existindo **internamente**
(1 aluno = 1 campanha de 1 roster). A UX de produto **não** pede “iniciar campanha”.

Templates TEMP antigos (ex.: p01 de POC) **não** são promovidos automaticamente.
Só vira permanente após novo complete → promote.

## Segurança

- M2 só em `127.0.0.1:8766`
- `M2_POC_TEST_HOOKS=0` em produção (`/force-step` → 404)
- QR sem nome, student_id, embedding ou segredo
- `/internal/matcher/reload` apenas loopback
- Reset de teste: `scripts/reset_enrollment_test_data.py` (confirmação explícita)

## Rollback

1. Reverter branch `feat/facial-enrollment-production`
2. Manter tabelas `facial_*` (não DROP)
3. UX antiga de campanha ainda atendida por `/api/gestor/campaigns`

## Reset lab

```bash
set M2_RESET_ENV=lab
set M2_RESET_CONFIRM=RESET-ENROLLMENT-TEST
python scripts/reset_enrollment_test_data.py --dry-run
python scripts/reset_enrollment_test_data.py --execute --sqlite --gallery-temp
```
