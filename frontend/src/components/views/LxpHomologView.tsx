import { PageHeader } from "../layout/PageHeader";
import { SectionHeader } from "../ui/SectionHeader";
import { EmptyState, LoadingState, ErrorState } from "../ui/EmptyState";
import { useLxpHomologData } from "../../hooks/useLxpHomologData";

function disp(v: unknown): string {
  if (v === null || v === undefined || v === "") return "Não observado";
  return String(v);
}

function statusClass(s?: string): string {
  const x = String(s || "").toLowerCase();
  if (x === "ok" || x === "sent" || x === "online") return "homolog-ok";
  if (x === "pending" || x === "retrying") return "homolog-pending";
  if (x === "fail" || x === "failed" || x === "offline") return "homolog-fail";
  if (x === "disabled") return "homolog-disabled";
  return "homolog-idle";
}

function stepIcon(s?: string): string {
  const x = String(s || "").toLowerCase();
  if (x === "ok") return "🟢";
  if (x === "pending") return "🟡";
  if (x === "fail") return "🔴";
  return "⚪";
}

export function LxpHomologView() {
  const { data, err, loading, selectedEventId, setSelectedEventId, selectedRow } =
    useLxpHomologData(2000);

  if (loading && !data) return <LoadingState label="Carregando homologação LXP…" />;
  if (err && !data) return <ErrorState message={err} />;
  if (!data?.ok && data?.error) {
    return <ErrorState message={data.error} />;
  }

  const env = data?.environment || {};
  const sim = data?.simulator || {};
  const ctx = data?.context || {};
  const steps = data?.pipeline?.steps || [];
  const detail = data?.pipeline?.detail;
  const summary = data?.outbox_summary || {};
  const history = data?.history || [];
  const presence = data?.presence || [];
  const idem = data?.idempotency || {};
  const tracks = data?.recognition?.tracks || [];

  // Prefer server detail for selected; if user picks another row, show row fields
  const showDetail =
    selectedEventId && detail?.event_id === selectedEventId
      ? detail
      : selectedRow
        ? {
            event_id: selectedRow.event_id,
            checkin_event_id: selectedRow.source_checkin_event_id,
            student_id_edge: selectedRow.edge_id,
            external_student_id: selectedRow.external_id,
            map_label:
              selectedRow.edge_id && selectedRow.external_id
                ? `${selectedRow.edge_id} → ${selectedRow.external_id}`
                : null,
            lesson_id: selectedRow.lesson_id,
            session_id: selectedRow.session_id,
            attendance: selectedRow.attendance,
            occurred_at: selectedRow.occurred_at,
            source: selectedRow.source,
            contract_version: selectedRow.contract_version,
            outbox_status: selectedRow.status,
            retry_count: selectedRow.retries,
            http_status: null,
            resultado: null,
            attendance_id: null,
          }
        : detail;

  return (
    <section className="lxp-homolog-view" data-testid="lxp-homolog-view">
      <PageHeader
        title={env.title || "LXP Attendance"}
        subtitle={env.subtitle || "Painel de Homologação"}
      />

      <div className="panel panel-soft homolog-header">
        <div className="homolog-header-row">
          <span className="homolog-badge" data-testid="lxp-homolog-badge">
            {env.badge || "SIMULATOR"}
          </span>
          <span className={`homolog-sim-status ${statusClass(sim.status)}`}>
            Status: {String(sim.status || "—").toUpperCase()}
          </span>
        </div>
        <p className="homolog-disclaimer" data-testid="lxp-homolog-disclaimer">
          {env.disclaimer ||
            "Ambiente de homologação — não conectado ao LXP de produção."}
        </p>
        <p className="muted">
          <strong>{env.simulator_label || "LXP ATTENDANCE SIMULATOR"}</strong>
          <br />
          Supabase: <code>{env.project_ref || "zasbmqwwkecmjbebejev"}</code>
          {sim.host ? (
            <>
              {" "}
              · host <code>{sim.host}</code>
            </>
          ) : null}
          {sim.reason ? (
            <>
              <br />
              Motivo: {String(sim.reason)}
            </>
          ) : null}
        </p>
        <p>
          <a
            className="btn"
            href="http://127.0.0.1:8000/homolog/simulator-admin/admin.html"
            target="_blank"
            rel="noreferrer"
          >
            Ver Simulator
          </a>
          <span className="muted" style={{ marginLeft: 8 }}>
            admin.html complementar
          </span>
        </p>
      </div>

      <div className="panel" data-testid="lxp-homolog-context">
        <SectionHeader title="Contexto da aula" subtitle="Sessão / lesson context atuais" />
        <dl className="homolog-dl">
          <div>
            <dt>Escola</dt>
            <dd>{disp(ctx.escola ?? ctx.school_id)}</dd>
          </div>
          <div>
            <dt>Turma</dt>
            <dd>{disp(ctx.turma)}</dd>
          </div>
          <div>
            <dt>Disciplina</dt>
            <dd>{disp(ctx.disciplina)}</dd>
          </div>
          <div>
            <dt>Aula</dt>
            <dd>{disp(ctx.aula)}</dd>
          </div>
          <div>
            <dt>Lesson ID</dt>
            <dd>
              <code>{disp(ctx.lesson_id)}</code>
            </dd>
          </div>
          <div>
            <dt>Duração</dt>
            <dd>
              {ctx.duracao_minutos != null ? `${ctx.duracao_minutos} min` : "Não observado"}
            </dd>
          </div>
          <div>
            <dt>Sala</dt>
            <dd>{disp(ctx.sala)}</dd>
          </div>
          <div>
            <dt>Session ID</dt>
            <dd>
              <code>{disp(ctx.session_id)}</code>
            </dd>
          </div>
        </dl>
        {tracks.length > 0 && (
          <p className="muted">
            Reconhecido agora:{" "}
            {tracks.map((t) => t.student_id || "?").join(", ")}
          </p>
        )}
      </div>

      <div className="panel" data-testid="lxp-homolog-pipeline">
        <SectionHeader
          title="Fluxo principal"
          subtitle="Câmera → check-in → outbox → SyncWorker → Simulator → presença"
        />
        <ol className="homolog-pipeline">
          {steps.map((st: any, i: number) => (
            <li key={st.id || i} className={statusClass(st.status)}>
              <div className="homolog-step-head">
                <span aria-hidden>{stepIcon(st.status)}</span>
                <strong>{st.label}</strong>
              </div>
              <div className="homolog-step-info">
                <code>{disp(st.info)}</code>
                {st.horario ? (
                  <span className="muted"> · {String(st.horario)}</span>
                ) : null}
              </div>
              {i < steps.length - 1 ? <div className="homolog-arrow">↓</div> : null}
            </li>
          ))}
        </ol>
        {!steps.length && (
          <EmptyState title="Sem fluxo" message="Aguardando eventos reais no Edge." />
        )}
      </div>

      <div className="metric-row" data-testid="lxp-homolog-summary">
        <div className="metric-card">
          <span className="metric-label">Pending</span>
          <span className="metric-value">{summary.pending ?? 0}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Sent</span>
          <span className="metric-value">{summary.sent ?? 0}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Failed</span>
          <span className="metric-value">{summary.failed ?? 0}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Retries</span>
          <span className="metric-value">{summary.retries_total ?? 0}</span>
        </div>
      </div>

      <div className="panel" data-testid="lxp-homolog-event">
        <SectionHeader title="Evento" subtitle="Detalhe do evento selecionado" />
        {showDetail ? (
          <dl className="homolog-dl">
            <div>
              <dt>event_id</dt>
              <dd>
                <code>{disp(showDetail.event_id)}</code>
              </dd>
            </div>
            <div>
              <dt>checkin_event_id</dt>
              <dd>
                <code>{disp(showDetail.checkin_event_id)}</code>
              </dd>
            </div>
            <div>
              <dt>Mapa</dt>
              <dd>
                <strong>{disp(showDetail.map_label)}</strong>
              </dd>
            </div>
            <div>
              <dt>Edge / Externo</dt>
              <dd>
                <code>{disp(showDetail.student_id_edge)}</code> →{" "}
                <code>{disp(showDetail.external_student_id)}</code>
              </dd>
            </div>
            <div>
              <dt>lesson_id</dt>
              <dd>
                <code>{disp(showDetail.lesson_id)}</code>
              </dd>
            </div>
            <div>
              <dt>session_id</dt>
              <dd>
                <code>{disp(showDetail.session_id)}</code>
              </dd>
            </div>
            <div>
              <dt>attendance</dt>
              <dd>{disp(showDetail.attendance)}</dd>
            </div>
            <div>
              <dt>occurred_at</dt>
              <dd>{disp(showDetail.occurred_at)}</dd>
            </div>
            <div>
              <dt>source</dt>
              <dd>{disp(showDetail.source)}</dd>
            </div>
            <div>
              <dt>contract_version</dt>
              <dd>{disp(showDetail.contract_version)}</dd>
            </div>
            <div>
              <dt>outbox status</dt>
              <dd>{disp(showDetail.outbox_status)}</dd>
            </div>
            <div>
              <dt>retry count</dt>
              <dd>{disp(showDetail.retry_count)}</dd>
            </div>
            <div>
              <dt>HTTP status</dt>
              <dd>{disp(showDetail.http_status)}</dd>
            </div>
            <div>
              <dt>resultado</dt>
              <dd>{disp(showDetail.resultado)}</dd>
            </div>
            <div>
              <dt>attendance_id</dt>
              <dd>
                <code>{disp(showDetail.attendance_id)}</code>
              </dd>
            </div>
          </dl>
        ) : (
          <EmptyState title="Nenhum evento" message="Sem lxp_attendance_event no outbox." />
        )}
      </div>

      <div className="panel" data-testid="lxp-homolog-history">
        <SectionHeader title="Histórico" subtitle="Eventos LXP no outbox Edge" />
        {history.length === 0 ? (
          <EmptyState title="Vazio" message="Nenhum evento LXP observado." />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Horário</th>
                  <th>Aluno</th>
                  <th>Edge ID</th>
                  <th>External ID</th>
                  <th>Lesson</th>
                  <th>Event ID</th>
                  <th>Status</th>
                  <th>Destino</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row: any) => (
                  <tr
                    key={row.event_id}
                    className={row.event_id === selectedEventId ? "is-selected" : ""}
                    onClick={() => setSelectedEventId(row.event_id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>{disp(row.horario)}</td>
                    <td>{disp(row.aluno)}</td>
                    <td>
                      <code>{disp(row.edge_id)}</code>
                    </td>
                    <td>
                      <code>{disp(row.external_id)}</code>
                    </td>
                    <td>
                      <code>{disp(row.lesson_id)}</code>
                    </td>
                    <td>
                      <code>{disp(row.event_id)}</code>
                    </td>
                    <td className={statusClass(row.status)}>{disp(row.status)}</td>
                    <td>{disp(row.destino)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel" data-testid="lxp-homolog-presence">
        <SectionHeader
          title="Presença recebida"
          subtitle="attendance_records no Simulator"
        />
        {presence.length === 0 ? (
          <EmptyState
            title="Nenhum registro"
            message="Simulator sem attendance_records visíveis (ou offline/disabled)."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Aluno</th>
                  <th>Lesson</th>
                  <th>Attendance</th>
                  <th>Horário</th>
                  <th>source_event_id</th>
                  <th>attendance_id</th>
                </tr>
              </thead>
              <tbody>
                {presence.map((row: any, i: number) => (
                  <tr key={row.attendance_id || i}>
                    <td>
                      <code>{disp(row.aluno)}</code>
                    </td>
                    <td>
                      <code>{disp(row.lesson_id)}</code>
                    </td>
                    <td>{disp(row.attendance)}</td>
                    <td>{disp(row.horario)}</td>
                    <td>
                      <code>{disp(row.source_event_id)}</code>
                    </td>
                    <td>
                      <code>{disp(row.attendance_id)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel" data-testid="lxp-homolog-idempotency">
        <SectionHeader title="Idempotência" subtitle="Receipts reais do Simulator" />
        {!idem.observed ? (
          <p className="muted">
            {idem.message || "Idempotência não observada nesta execução."}
          </p>
        ) : (
          <div>
            <p>
              event_id: <code>{disp(idem.event_id)}</code>
            </p>
            <ul>
              {(idem.receipts || []).map((r: any, i: number) => (
                <li key={i}>
                  {i === 0 ? "Primeiro envio" : `Reenvio ${i}`}:{" "}
                  <strong>{String(r.result_status || "—").toUpperCase()}</strong>
                  {r.http_status != null ? ` (HTTP ${r.http_status})` : ""}
                </li>
              ))}
            </ul>
            <p>
              Registro final: <strong>{idem.attendance_record_count ?? "—"}</strong>{" "}
              attendance record(s)
            </p>
          </div>
        )}
      </div>

      <div className="panel" data-testid="lxp-homolog-timeline">
        <SectionHeader title="Timeline" subtitle="Cadeia do evento selecionado" />
        <ol className="homolog-timeline">
          {steps.map((st: any) => (
            <li key={`tl-${st.id}`}>
              <span className="muted">{st.horario ? String(st.horario) : "—"}</span>
              <strong> {st.label}</strong>
              <div>
                <code>{disp(st.info)}</code>
              </div>
            </li>
          ))}
        </ol>
      </div>

      {err ? <p className="warn-text">Atualização: {err}</p> : null}
    </section>
  );
}
