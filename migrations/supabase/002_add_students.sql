-- Migration 002: Adicionar tabelas students e face_embeddings
-- Supabase (PostgreSQL)

-- Tabela de alunos
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL,
    room_id TEXT,
    full_name TEXT,
    external_ref TEXT,  -- Futuro mapeamento com LXP
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para students
CREATE INDEX IF NOT EXISTS idx_students_school_id ON students(school_id);
CREATE INDEX IF NOT EXISTS idx_students_room_id ON students(room_id);
CREATE INDEX IF NOT EXISTS idx_students_is_active ON students(is_active);
CREATE INDEX IF NOT EXISTS idx_students_external_ref ON students(external_ref);

-- Tabela de embeddings faciais
CREATE TABLE IF NOT EXISTS face_embeddings (
    id BIGSERIAL PRIMARY KEY,
    student_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    room_id TEXT,
    embedding_vector JSONB NOT NULL,  -- Array de floats como JSONB
    embedding_dim INTEGER DEFAULT 128,
    model_name TEXT DEFAULT 'facenet',
    model_version TEXT,
    quality_score DECIMAL(5,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_face_embeddings_student FOREIGN KEY (student_id) 
        REFERENCES students(student_id) ON DELETE CASCADE
);

-- Índices para face_embeddings
CREATE INDEX IF NOT EXISTS idx_face_embeddings_student_id ON face_embeddings(student_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_school_id ON face_embeddings(school_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_room_id ON face_embeddings(room_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_device_id ON face_embeddings(device_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_active ON face_embeddings(student_id, device_id, school_id);

-- Trigger para atualizar updated_at em students
CREATE OR REPLACE FUNCTION update_students_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_students_updated_at
    BEFORE UPDATE ON students
    FOR EACH ROW
    EXECUTE FUNCTION update_students_updated_at();
