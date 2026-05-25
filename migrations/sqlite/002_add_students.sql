-- Migration 002: Adicionar tabelas students e face_embeddings
-- SQLite

-- Tabela de alunos
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL,
    room_id TEXT,
    full_name TEXT,
    external_ref TEXT,  -- Futuro mapeamento com LXP
    is_active INTEGER DEFAULT 1,  -- SQLite usa INTEGER para boolean
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Índices para students
CREATE INDEX IF NOT EXISTS idx_students_school_id ON students(school_id);
CREATE INDEX IF NOT EXISTS idx_students_room_id ON students(room_id);
CREATE INDEX IF NOT EXISTS idx_students_is_active ON students(is_active);
CREATE INDEX IF NOT EXISTS idx_students_external_ref ON students(external_ref);

-- Tabela de embeddings faciais
CREATE TABLE IF NOT EXISTS face_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    room_id TEXT,
    embedding_vector TEXT NOT NULL,  -- JSON array de floats
    embedding_dim INTEGER DEFAULT 128,
    model_name TEXT DEFAULT 'facenet',
    model_version TEXT,
    quality_score REAL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
);

-- Índices para face_embeddings
CREATE INDEX IF NOT EXISTS idx_face_embeddings_student_id ON face_embeddings(student_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_school_id ON face_embeddings(school_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_room_id ON face_embeddings(room_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_device_id ON face_embeddings(device_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_active ON face_embeddings(student_id, device_id, school_id);

-- Trigger para atualizar updated_at em students
CREATE TRIGGER IF NOT EXISTS update_students_updated_at 
AFTER UPDATE ON students
BEGIN
    UPDATE students SET updated_at = datetime('now') WHERE student_id = NEW.student_id;
END;
