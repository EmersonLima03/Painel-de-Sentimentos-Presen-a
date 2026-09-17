import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "../../layout/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../../ui/EmptyState";
import { useAuth } from "../../../cloud/AuthContext";
import {
  assignTeacher,
  enrollStudent,
  fetchCameras,
  fetchClassGroups,
  fetchDevices,
  fetchEnrollments,
  fetchMyClassGroups,
  fetchRooms,
  fetchSchool,
  fetchStudents,
  fetchSubjects,
  fetchTeacherAssignments,
  fetchTeam,
  inviteTeamMember,
  removeTeacherAssignment,
  revokeDeviceCredentials,
  setEnrollmentStatus,
  updateDevice,
  updateSchoolName,
  upsertCamera,
  upsertClassGroup,
  upsertRoom,
  upsertStudent,
  upsertSubject,
  type ClassGroupRow,
  type StudentRow,
  type SubjectRow,
} from "../../../cloud/adminApi";

export type AdminSection =
  | "school"
  | "team"
  | "subjects"
  | "classes"
  | "students"
  | "rooms"
  | "devices"
  | "cameras";

const GESTOR_SECTIONS: { id: AdminSection; label: string }[] = [
  { id: "school", label: "Minha escola" },
  { id: "team", label: "Equipe" },
  { id: "subjects", label: "Disciplinas" },
  { id: "classes", label: "Turmas" },
  { id: "students", label: "Alunos" },
  { id: "rooms", label: "Salas" },
  { id: "devices", label: "Dispositivos" },
  { id: "cameras", label: "Câmeras" },
];

type Props = { initialSection?: AdminSection };

export function AdminShellView({ initialSection = "school" }: Props) {
  const auth = useAuth();
  const [section, setSection] = useState<AdminSection>(initialSection);

  if (auth.loading) return <LoadingState label="Carregando conta…" />;
  if (!auth.configured) {
    return (
      <EmptyState
        title="Cloud não configurado"
        message="Defina VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY."
      />
    );
  }
  if (!auth.email) {
    return (
      <EmptyState
        title="Faça login"
        message="Entre em Configurações → Conta Sentimentos para administrar a escola."
      />
    );
  }
  if (!auth.activeSchoolId || !auth.activeOrganizationId) {
    return (
      <EmptyState
        title="Sem escola vinculada"
        message="Seu usuário não possui membership em nenhuma escola."
      />
    );
  }

  // Professor/monitor: visão limitada (turmas)
  if (!auth.isGestor) {
    return <ProfessorLimitedView />;
  }

  return (
    <div className="admin-shell">
      <PageHeader
        title="Administração"
        subtitle="Cadastro da escola — apenas a sua organização"
      />
      {auth.memberships.length > 1 && (
        <label className="admin-school-switch">
          Escola
          <select
            value={auth.activeSchoolId}
            onChange={(e) => auth.setActiveSchoolId(e.target.value)}
          >
            {auth.memberships.map((m) => (
              <option key={m.school_id} value={m.school_id}>
                {(m.schools as any)?.name || m.school_id} ({m.role})
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="admin-layout">
        <nav className="admin-subnav" aria-label="Administração">
          {GESTOR_SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`sidebar-item ${section === s.id ? "active" : ""}`}
              onClick={() => setSection(s.id)}
            >
              {s.label}
            </button>
          ))}
        </nav>
        <div className="admin-content panel">
          {section === "school" && (
            <SchoolAdmin schoolId={auth.activeSchoolId} />
          )}
          {section === "team" && (
            <TeamAdmin
              schoolId={auth.activeSchoolId}
              organizationId={auth.activeOrganizationId}
            />
          )}
          {section === "subjects" && (
            <SubjectsAdmin
              schoolId={auth.activeSchoolId}
              organizationId={auth.activeOrganizationId}
            />
          )}
          {section === "classes" && (
            <ClassesAdmin
              schoolId={auth.activeSchoolId}
              organizationId={auth.activeOrganizationId}
            />
          )}
          {section === "students" && (
            <StudentsAdmin
              schoolId={auth.activeSchoolId}
              organizationId={auth.activeOrganizationId}
            />
          )}
          {section === "rooms" && (
            <RoomsAdmin
              schoolId={auth.activeSchoolId}
              organizationId={auth.activeOrganizationId}
            />
          )}
          {section === "devices" && <DevicesAdmin schoolId={auth.activeSchoolId} />}
          {section === "cameras" && (
            <CamerasAdmin
              schoolId={auth.activeSchoolId}
              organizationId={auth.activeOrganizationId}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function Flash({ msg }: { msg: string }) {
  if (!msg) return null;
  return <p className={msg.startsWith("Erro") ? "error-text" : "ok-text"}>{msg}</p>;
}

function SchoolAdmin({ schoolId }: { schoolId: string }) {
  const [name, setName] = useState("");
  const [org, setOrg] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      const { data, error } = await fetchSchool(schoolId);
      if (error) setMsg(`Erro: ${error.message}`);
      else if (data) {
        setName(data.name);
        setOrg((data as any).organizations?.name || "");
      }
    })();
  }, [schoolId]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const { error } = await updateSchoolName(schoolId, name.trim());
    setBusy(false);
    setMsg(error ? `Erro: ${error.message}` : "Escola atualizada.");
  }

  return (
    <div>
      <h2>Minha escola</h2>
      <form className="admin-form" onSubmit={save}>
        <label>
          Organização
          <input value={org} disabled readOnly />
        </label>
        <label>
          Nome da escola
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit" disabled={busy}>
          Salvar
        </button>
      </form>
    </div>
  );
}

function TeamAdmin({ schoolId, organizationId }: { schoolId: string; organizationId: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    role: "professor" as "professor" | "monitor" | "gestor",
    temporary_password: "",
  });

  async function reload() {
    const { data, error } = await fetchTeam(schoolId);
    if (error) setMsg(`Erro: ${error.message}`);
    else setRows(data || []);
  }

  useEffect(() => {
    void reload();
  }, [schoolId]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await inviteTeamMember({
        ...form,
        school_id: schoolId,
        email: form.email.trim(),
        full_name: form.full_name.trim(),
      });
      setMsg("Membro convidado. A senha temporária foi definida — peça a troca no primeiro acesso.");
      setForm({ full_name: "", email: "", role: "professor", temporary_password: "" });
      await reload();
    } catch (err: any) {
      setMsg(`Erro: ${err.message || err}`);
    }
  }

  return (
    <div>
      <h2>Equipe</h2>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Nome</th>
            <th>E-mail</th>
            <th>Papel</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.profiles?.full_name || "—"}</td>
              <td>{r.profiles?.email || "—"}</td>
              <td>{r.role}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <EmptyState title="Nenhum membro" message="Convide professores ou monitores." />}
      <h3>Adicionar membro</h3>
      <form className="admin-form" onSubmit={invite}>
        <label>
          Nome
          <input
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            required
          />
        </label>
        <label>
          E-mail
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
          />
        </label>
        <label>
          Papel
          <select
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value as any })}
          >
            <option value="professor">Professor</option>
            <option value="monitor">Monitor</option>
            <option value="gestor">Gestor</option>
          </select>
        </label>
        <label>
          Senha temporária
          <input
            type="password"
            value={form.temporary_password}
            onChange={(e) => setForm({ ...form, temporary_password: e.target.value })}
            required
            minLength={8}
          />
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit">
          Convidar
        </button>
      </form>
      <p className="muted small">organization_id: {organizationId.slice(0, 8)}…</p>
    </div>
  );
}

function SubjectsAdmin({ schoolId, organizationId }: { schoolId: string; organizationId: string }) {
  const [rows, setRows] = useState<SubjectRow[]>([]);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");

  async function reload() {
    const { data, error } = await fetchSubjects(schoolId);
    if (error) setMsg(`Erro: ${error.message}`);
    else setRows((data as SubjectRow[]) || []);
  }
  useEffect(() => {
    void reload();
  }, [schoolId]);

  const filtered = useMemo(
    () => rows.filter((r) => r.name.toLowerCase().includes(q.toLowerCase())),
    [rows, q],
  );

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await upsertSubject({
      school_id: schoolId,
      organization_id: organizationId,
      name: name.trim(),
      external_ref: code.trim() || null,
      is_active: true,
    });
    setMsg(error ? `Erro: ${error.message}` : "Disciplina criada.");
    if (!error) {
      setName("");
      setCode("");
      await reload();
    }
  }

  async function toggle(row: SubjectRow) {
    const { error } = await upsertSubject({ ...row, is_active: !row.is_active });
    if (error) setMsg(`Erro: ${error.message}`);
    else await reload();
  }

  return (
    <div>
      <h2>Disciplinas</h2>
      <div className="admin-toolbar">
        <input placeholder="Buscar…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Código</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {filtered.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td>
              <td>{r.external_ref || "—"}</td>
              <td>{r.is_active ? "Ativo" : "Inativo"}</td>
              <td>
                <button type="button" className="btn ghost" onClick={() => void toggle(r)}>
                  {r.is_active ? "Desativar" : "Ativar"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="admin-form" onSubmit={add}>
        <h3>Adicionar disciplina</h3>
        <label>
          Nome
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          Código (opcional)
          <input value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit">
          Adicionar
        </button>
      </form>
    </div>
  );
}

function ClassesAdmin({ schoolId, organizationId }: { schoolId: string; organizationId: string }) {
  const [rows, setRows] = useState<ClassGroupRow[]>([]);
  const [team, setTeam] = useState<any[]>([]);
  const [subjects, setSubjects] = useState<SubjectRow[]>([]);
  const [assignments, setAssignments] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ name: "", year_label: "", shift: "" });
  const [assign, setAssign] = useState({ profile_id: "", class_group_id: "", subject_id: "" });

  async function reload() {
    const [c, t, s, a] = await Promise.all([
      fetchClassGroups(schoolId),
      fetchTeam(schoolId),
      fetchSubjects(schoolId),
      fetchTeacherAssignments(schoolId),
    ]);
    if (c.error) setMsg(`Erro: ${c.error.message}`);
    setRows((c.data as ClassGroupRow[]) || []);
    setTeam((t.data || []).filter((m: any) => m.role === "professor"));
    setSubjects((s.data as SubjectRow[]) || []);
    setAssignments(a.data || []);
  }
  useEffect(() => {
    void reload();
  }, [schoolId]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const name = form.name.trim();
    if (!name) {
      setMsg("Erro: informe o nome da turma.");
      return;
    }
    if (!schoolId || !organizationId) {
      setMsg("Erro: escola/organização não selecionada.");
      return;
    }
    const { data, error } = await upsertClassGroup({
      school_id: schoolId,
      organization_id: organizationId,
      name,
      year_label: form.year_label.trim() || null,
      shift: form.shift.trim() || null,
      is_active: true,
    });
    if (error) {
      setMsg(`Erro: ${error.message}`);
      return;
    }
    setMsg("Turma criada.");
    setForm({ name: "", year_label: "", shift: "" });
    if (data) {
      setRows((prev) => {
        const row = data as ClassGroupRow;
        if (prev.some((r) => r.id === row.id)) return prev;
        return [...prev, row].sort((a, b) => a.name.localeCompare(b.name));
      });
    }
    await reload();
  }

  async function doAssign(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await assignTeacher({
      school_id: schoolId,
      organization_id: organizationId,
      profile_id: assign.profile_id,
      class_group_id: assign.class_group_id,
      subject_id: assign.subject_id || null,
    });
    setMsg(error ? `Erro: ${error.message}` : "Professor atribuído.");
    if (!error) await reload();
  }

  return (
    <div>
      <h2>Turmas</h2>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Série/ano</th>
            <th>Turno</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td>
              <td>{r.year_label || "—"}</td>
              <td>{r.shift || "—"}</td>
              <td>{r.is_active ? "Ativo" : "Inativo"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="admin-form" onSubmit={add}>
        <h3>Adicionar turma</h3>
        <label>
          Nome
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        </label>
        <label>
          Série/ano
          <input
            value={form.year_label}
            onChange={(e) => setForm({ ...form, year_label: e.target.value })}
            placeholder="Ex.: 8º Ano"
          />
        </label>
        <label>
          Turno
          <input
            value={form.shift}
            onChange={(e) => setForm({ ...form, shift: e.target.value })}
            placeholder="Ex.: Manhã"
          />
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit">
          Adicionar
        </button>
      </form>

      <h3>Professor ↔ turma</h3>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Professor</th>
            <th>Turma</th>
            <th>Disciplina</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {assignments.map((a) => (
            <tr key={a.id}>
              <td>{a.profiles?.full_name || a.profile_id}</td>
              <td>{a.class_groups?.name || a.class_group_id}</td>
              <td>{a.subjects?.name || "—"}</td>
              <td>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={async () => {
                    if (!confirm("Remover atribuição?")) return;
                    await removeTeacherAssignment(a.id);
                    await reload();
                  }}
                >
                  Remover
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="admin-form" onSubmit={doAssign}>
        <label>
          Professor
          <select
            value={assign.profile_id}
            onChange={(e) => setAssign({ ...assign, profile_id: e.target.value })}
            required
          >
            <option value="">Selecione</option>
            {team.map((m) => (
              <option key={m.profile_id} value={m.profile_id}>
                {m.profiles?.full_name || m.profile_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Turma
          <select
            value={assign.class_group_id}
            onChange={(e) => setAssign({ ...assign, class_group_id: e.target.value })}
            required
          >
            <option value="">Selecione</option>
            {rows.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Disciplina (opcional)
          <select
            value={assign.subject_id}
            onChange={(e) => setAssign({ ...assign, subject_id: e.target.value })}
          >
            <option value="">—</option>
            {subjects.filter((s) => s.is_active !== false).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit">
          Atribuir
        </button>
      </form>
    </div>
  );
}

function StudentsAdmin({ schoolId, organizationId }: { schoolId: string; organizationId: string }) {
  const [rows, setRows] = useState<StudentRow[]>([]);
  const [classes, setClasses] = useState<ClassGroupRow[]>([]);
  const [enrolls, setEnrolls] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ full_name: "", external_ref: "" });
  const [enroll, setEnroll] = useState({ student_id: "", class_group_id: "" });

  async function reload() {
    const [s, c, e] = await Promise.all([
      fetchStudents(schoolId),
      fetchClassGroups(schoolId),
      fetchEnrollments(schoolId),
    ]);
    if (s.error) setMsg(`Erro: ${s.error.message}`);
    setRows((s.data as StudentRow[]) || []);
    setClasses((c.data as ClassGroupRow[]) || []);
    setEnrolls(e.data || []);
  }
  useEffect(() => {
    void reload();
  }, [schoolId]);

  const filtered = rows.filter((r) => r.full_name.toLowerCase().includes(q.toLowerCase()));

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await upsertStudent({
      school_id: schoolId,
      organization_id: organizationId,
      full_name: form.full_name.trim(),
      external_ref: form.external_ref.trim() || null,
      is_active: true,
    });
    setMsg(error ? `Erro: ${error.message}` : "Aluno criado.");
    if (!error) {
      setForm({ full_name: "", external_ref: "" });
      await reload();
    }
  }

  async function doEnroll(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await enrollStudent({
      school_id: schoolId,
      organization_id: organizationId,
      student_id: enroll.student_id,
      class_group_id: enroll.class_group_id,
    });
    setMsg(error ? `Erro: ${error.message}` : "Matrícula criada.");
    if (!error) await reload();
  }

  return (
    <div>
      <h2>Alunos</h2>
      <div className="admin-toolbar">
        <input placeholder="Buscar aluno…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Matrícula</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((r) => (
            <tr key={r.id}>
              <td>{r.full_name}</td>
              <td>{r.external_ref || "—"}</td>
              <td>{r.is_active ? "Ativo" : "Inativo"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="admin-form" onSubmit={add}>
        <h3>Adicionar aluno</h3>
        <label>
          Nome
          <input
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            required
          />
        </label>
        <label>
          Matrícula / ref. externa (opcional)
          <input
            value={form.external_ref}
            onChange={(e) => setForm({ ...form, external_ref: e.target.value })}
          />
        </label>
        <button className="btn primary" type="submit">
          Adicionar
        </button>
      </form>

      <h3>Matrículas</h3>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Aluno</th>
            <th>Turma</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {enrolls.map((e) => (
            <tr key={e.id}>
              <td>{e.students?.full_name || e.student_id}</td>
              <td>{e.class_groups?.name || e.class_group_id}</td>
              <td>{e.status}</td>
              <td>
                {e.status === "active" && (
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={async () => {
                      if (!confirm("Retirar aluno da turma?")) return;
                      await setEnrollmentStatus(e.id, "ended");
                      await reload();
                    }}
                  >
                    Retirar
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="admin-form" onSubmit={doEnroll}>
        <h3>Matricular</h3>
        <label>
          Aluno
          <select
            value={enroll.student_id}
            onChange={(e) => setEnroll({ ...enroll, student_id: e.target.value })}
            required
          >
            <option value="">Selecione</option>
            {rows.filter((r) => r.is_active).map((r) => (
              <option key={r.id} value={r.id}>
                {r.full_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Turma
          <select
            value={enroll.class_group_id}
            onChange={(e) => setEnroll({ ...enroll, class_group_id: e.target.value })}
            required
          >
            <option value="">Selecione</option>
            {classes.filter((c) => c.is_active).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit">
          Matricular
        </button>
      </form>
    </div>
  );
}

function RoomsAdmin({ schoolId, organizationId }: { schoolId: string; organizationId: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ name: "", code: "", description: "" });

  async function reload() {
    const { data, error } = await fetchRooms(schoolId);
    if (error) setMsg(`Erro: ${error.message}`);
    else setRows(data || []);
  }
  useEffect(() => {
    void reload();
  }, [schoolId]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await upsertRoom({
      school_id: schoolId,
      organization_id: organizationId,
      name: form.name.trim(),
      code: form.code.trim() || null,
      description: form.description.trim() || null,
      is_active: true,
    });
    setMsg(error ? `Erro: ${error.message}` : "Sala criada.");
    if (!error) {
      setForm({ name: "", code: "", description: "" });
      await reload();
    }
  }

  return (
    <div>
      <h2>Salas</h2>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Código</th>
            <th>Descrição</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td>
              <td>{r.code || "—"}</td>
              <td>{r.description || "—"}</td>
              <td>{r.is_active ? "Ativo" : "Inativo"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="admin-form" onSubmit={add}>
        <h3>Adicionar sala</h3>
        <label>
          Nome
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        </label>
        <label>
          Código
          <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
        </label>
        <label>
          Descrição
          <input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit">
          Adicionar
        </button>
      </form>
    </div>
  );
}

function DevicesAdmin({ schoolId }: { schoolId: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [rooms, setRooms] = useState<any[]>([]);
  const [msg, setMsg] = useState("");

  async function reload() {
    const [d, r] = await Promise.all([fetchDevices(schoolId), fetchRooms(schoolId)]);
    if (d.error) setMsg(`Erro: ${d.error.message}`);
    setRows(d.data || []);
    setRooms(r.data || []);
  }
  useEffect(() => {
    void reload();
  }, [schoolId]);

  return (
    <div>
      <h2>Dispositivos Edge</h2>
      <p className="muted">Token secreto nunca é exibido. Revogar invalida credenciais ativas.</p>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Device code</th>
            <th>Sala</th>
            <th>Status</th>
            <th>Last seen</th>
            <th>Versão</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.id}>
              <td>
                <input
                  defaultValue={d.display_name}
                  onBlur={async (e) => {
                    if (e.target.value !== d.display_name) {
                      await updateDevice(d.id, { display_name: e.target.value });
                      await reload();
                    }
                  }}
                />
              </td>
              <td>
                <code>{d.device_code}</code>
              </td>
              <td>
                <select
                  value={d.room_id || ""}
                  onChange={async (e) => {
                    await updateDevice(d.id, { room_id: e.target.value || null });
                    await reload();
                  }}
                >
                  <option value="">—</option>
                  {rooms.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </td>
              <td>{d.status}</td>
              <td>{d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "—"}</td>
              <td>{d.app_version || "—"}</td>
              <td>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={async () => {
                    if (!confirm("Revogar credenciais deste device?")) return;
                    const { error } = await revokeDeviceCredentials(d.id);
                    setMsg(error ? `Erro: ${error.message}` : "Credenciais revogadas.");
                    await reload();
                  }}
                >
                  Revogar
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && (
        <EmptyState
          title="Nenhum dispositivo"
          message="Devices são registrados no Edge; aqui você associa sala e revoga acesso."
        />
      )}
      <Flash msg={msg} />
    </div>
  );
}

function CamerasAdmin({ schoolId, organizationId }: { schoolId: string; organizationId: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [rooms, setRooms] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ label: "", room_id: "", edge_camera_id: "" });

  async function reload() {
    const [c, r] = await Promise.all([fetchCameras(schoolId), fetchRooms(schoolId)]);
    if (c.error) setMsg(`Erro: ${c.error.message}`);
    setRows(c.data || []);
    setRooms(r.data || []);
  }
  useEffect(() => {
    void reload();
  }, [schoolId]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await upsertCamera({
      school_id: schoolId,
      organization_id: organizationId,
      room_id: form.room_id,
      label: form.label.trim(),
      edge_camera_id: form.edge_camera_id.trim(),
      is_active: true,
    });
    setMsg(error ? `Erro: ${error.message}` : "Câmera cadastrada.");
    if (!error) {
      setForm({ label: "", room_id: "", edge_camera_id: "" });
      await reload();
    }
  }

  return (
    <div>
      <h2>Câmeras</h2>
      <p className="muted">Cadastro de infraestrutura — sem fusão multicâmera neste MVP.</p>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Sala</th>
            <th>ID técnico</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>{c.label}</td>
              <td>{c.rooms?.name || c.room_id}</td>
              <td>
                <code>{c.edge_camera_id}</code>
              </td>
              <td>{c.is_active ? "Ativo" : "Inativo"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="admin-form" onSubmit={add}>
        <h3>Adicionar câmera</h3>
        <label>
          Nome
          <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} required />
        </label>
        <label>
          Sala
          <select
            value={form.room_id}
            onChange={(e) => setForm({ ...form, room_id: e.target.value })}
            required
          >
            <option value="">Selecione</option>
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          ID técnico (edge_camera_id)
          <input
            value={form.edge_camera_id}
            onChange={(e) => setForm({ ...form, edge_camera_id: e.target.value })}
            required
          />
        </label>
        <Flash msg={msg} />
        <button className="btn primary" type="submit">
          Adicionar
        </button>
      </form>
    </div>
  );
}

function ProfessorLimitedView() {
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      const { data, error } = await fetchMyClassGroups();
      setLoading(false);
      if (error) setErr(error.message);
      else setRows(data || []);
    })();
  }, []);

  if (loading) return <LoadingState />;
  if (err) return <ErrorState message={err} />;

  return (
    <div>
      <PageHeader
        title="Minhas turmas"
        subtitle="Acesso do professor/monitor — sem administração de cadastro"
      />
      <div className="panel">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Turma</th>
              <th>Série</th>
              <th>Turno</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{r.year_label || "—"}</td>
                <td>{r.shift || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && (
          <EmptyState title="Nenhuma turma" message="Nenhuma turma atribuída ao seu usuário." />
        )}
      </div>
    </div>
  );
}
