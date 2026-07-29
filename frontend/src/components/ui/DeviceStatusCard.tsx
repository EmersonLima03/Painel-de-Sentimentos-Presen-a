type CameraItem = {
  camera_id?: string;
  status?: string;
  online?: boolean;
  name?: string;
};

type Props = {
  online?: number | null;
  total?: number | null;
  items?: CameraItem[] | null;
};

export function DeviceStatusCard({ online, total, items }: Props) {
  const hasAgg = online != null && total != null;
  const list = items || [];

  if (!hasAgg && list.length === 0) {
    return (
      <div className="panel">
        <h3>Status dos dispositivos</h3>
        <p className="muted">
          Agregação de dispositivos da escola ainda não está disponível neste dispositivo.
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h3>Status dos dispositivos (local)</h3>
      {hasAgg && (
        <p>
          Online: <strong>{online}</strong> / {total}
        </p>
      )}
      {list.length > 0 && (
        <ul className="device-list">
          {list.map((c, i) => {
            const st = c.online === false || c.status === "offline" ? "offline" : "online";
            return (
              <li key={c.camera_id || i}>
                <span className={`status-badge ${st === "online" ? "good" : "danger"}`}>
                  {st === "online" ? "Online" : "Offline"}
                </span>{" "}
                {c.name || c.camera_id || `Câmera ${i + 1}`}
              </li>
            );
          })}
        </ul>
      )}
      <p className="muted state-hint">
        Detalhes técnicos avançados permanecem em /debug/vision e no painel legado.
      </p>
    </div>
  );
}
