-- Schema SQL para Supabase Staging
-- Projeto separado para edge vision (não mexe no banco do LXP)

-- Tabela raw de eventos (recebe tudo)
CREATE TABLE IF NOT EXISTS edge_events_raw (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,  -- UUID do evento (idempotência)
    event_type TEXT NOT NULL,
    device_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    room_id TEXT,
    payload JSONB NOT NULL,  -- Payload completo do evento
    ts BIGINT NOT NULL,  -- Timestamp do evento
    inserted_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Índices
    CONSTRAINT edge_events_raw_event_id_key UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_edge_events_raw_event_type ON edge_events_raw(event_type);
CREATE INDEX IF NOT EXISTS idx_edge_events_raw_device_id ON edge_events_raw(device_id);
CREATE INDEX IF NOT EXISTS idx_edge_events_raw_ts ON edge_events_raw(ts);
CREATE INDEX IF NOT EXISTS idx_edge_events_raw_inserted_at ON edge_events_raw(inserted_at);

-- Tabela normalizada de check-ins de presença
CREATE TABLE IF NOT EXISTS attendance_checkins (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,  -- Referência ao event_id original
    student_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    confidence DECIMAL(5,2) NOT NULL,
    model_version TEXT,
    template_version TEXT,
    face_quality TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT attendance_checkins_event_id_key UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_attendance_checkins_student_id ON attendance_checkins(student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_checkins_room_id ON attendance_checkins(room_id);
CREATE INDEX IF NOT EXISTS idx_attendance_checkins_timestamp ON attendance_checkins(timestamp);
CREATE INDEX IF NOT EXISTS idx_attendance_checkins_school_id ON attendance_checkins(school_id);

-- Tabela normalizada de janelas de engajamento
CREATE TABLE IF NOT EXISTS engagement_windows (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,  -- Referência ao event_id original
    school_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    ts_start BIGINT NOT NULL,
    ts_end BIGINT NOT NULL,
    faces_detected_avg DECIMAL(5,2),
    engagement_index_avg DECIMAL(5,2),
    states_distribution JSONB,  -- {attentive, neutral, distracted}
    model_version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT engagement_windows_event_id_key UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_engagement_windows_room_id ON engagement_windows(room_id);
CREATE INDEX IF NOT EXISTS idx_engagement_windows_ts_start ON engagement_windows(ts_start);
CREATE INDEX IF NOT EXISTS idx_engagement_windows_school_id ON engagement_windows(school_id);

-- Tabela de dispositivos (opcional, para tracking)
CREATE TABLE IF NOT EXISTS edge_devices (
    device_id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL,
    last_seen TIMESTAMPTZ,
    version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Função helper para verificar idempotência
CREATE OR REPLACE FUNCTION check_event_exists(p_event_id TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM edge_events_raw WHERE event_id = p_event_id
    );
END;
$$ LANGUAGE plpgsql;
