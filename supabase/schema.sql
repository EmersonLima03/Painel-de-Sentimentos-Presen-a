-- Schema SQL para Supabase
-- Tabelas para receber eventos do edge device

-- Tabela de eventos de presença (check-in)
CREATE TABLE IF NOT EXISTS attendance_events_raw (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,  -- UUID do evento (idempotência)
    student_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    confidence DECIMAL(5,2) NOT NULL,
    model_version TEXT,
    template_version TEXT,
    face_quality TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attendance_student_id ON attendance_events_raw(student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_room_id ON attendance_events_raw(room_id);
CREATE INDEX IF NOT EXISTS idx_attendance_timestamp ON attendance_events_raw(timestamp);
CREATE INDEX IF NOT EXISTS idx_attendance_event_id ON attendance_events_raw(event_id);

-- Tabela de janelas de engajamento
CREATE TABLE IF NOT EXISTS engagement_windows (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,  -- UUID do evento (idempotência)
    school_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    ts_start BIGINT NOT NULL,
    ts_end BIGINT NOT NULL,
    faces_detected_avg DECIMAL(5,2),
    engagement_index_avg DECIMAL(5,2),
    states_distribution JSONB,  -- {attentive, neutral, distracted}
    model_version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_engagement_room_id ON engagement_windows(room_id);
CREATE INDEX IF NOT EXISTS idx_engagement_ts_start ON engagement_windows(ts_start);
CREATE INDEX IF NOT EXISTS idx_engagement_event_id ON engagement_windows(event_id);

-- Tabela de dispositivos (opcional, para tracking)
CREATE TABLE IF NOT EXISTS edge_devices (
    device_id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL,
    last_seen TIMESTAMPTZ,
    version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Função para garantir idempotência (usar em triggers ou na edge function)
CREATE OR REPLACE FUNCTION check_event_idempotency(
    p_event_id TEXT,
    p_event_type TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    exists_count INTEGER;
BEGIN
    IF p_event_type = 'attendance_checkin' THEN
        SELECT COUNT(*) INTO exists_count
        FROM attendance_events_raw
        WHERE event_id = p_event_id;
    ELSIF p_event_type = 'engagement_window' THEN
        SELECT COUNT(*) INTO exists_count
        FROM engagement_windows
        WHERE event_id = p_event_id;
    ELSE
        RETURN FALSE;
    END IF;
    
    RETURN exists_count = 0;
END;
$$ LANGUAGE plpgsql;
