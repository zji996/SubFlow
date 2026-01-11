-- SubFlow PostgreSQL-first schema (Phase 1)
-- Note: this is an initial, idempotent schema (CREATE TABLE IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS projects (
  id            VARCHAR PRIMARY KEY,
  name          TEXT NOT NULL,
  media_url     TEXT NOT NULL,
  source_language TEXT NULL,
  target_language TEXT NOT NULL,
  auto_workflow BOOLEAN NOT NULL DEFAULT TRUE,
  status        TEXT NOT NULL,
  current_stage INTEGER NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  created_at    TIMESTAMPTZ NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_runs (
  project_id    VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  stage         TEXT NOT NULL,
  status        TEXT NOT NULL,
  started_at    TIMESTAMPTZ NULL,
  completed_at  TIMESTAMPTZ NULL,
  error_message TEXT NULL,
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (project_id, stage)
);

CREATE TABLE IF NOT EXISTS vad_segments (
  project_id    VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  segment_index INTEGER NOT NULL,
  start_time    DOUBLE PRECISION NOT NULL,
  end_time      DOUBLE PRECISION NOT NULL,
  region_id     INTEGER NULL,
  PRIMARY KEY (project_id, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_vad_segments_project_id ON vad_segments(project_id);
CREATE INDEX IF NOT EXISTS idx_vad_segments_project_time ON vad_segments(project_id, start_time, end_time);

CREATE TABLE IF NOT EXISTS asr_segments (
  project_id      VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  segment_index   INTEGER NOT NULL,
  start_time      DOUBLE PRECISION NOT NULL,
  end_time        DOUBLE PRECISION NOT NULL,
  text            TEXT NOT NULL,
  corrected_text  TEXT NULL,
  language        TEXT NULL,
  confidence      DOUBLE PRECISION NULL,
  PRIMARY KEY (project_id, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_asr_segments_project_id ON asr_segments(project_id);
CREATE INDEX IF NOT EXISTS idx_asr_segments_project_time ON asr_segments(project_id, start_time, end_time);

CREATE TABLE IF NOT EXISTS global_contexts (
  project_id         VARCHAR PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  topic              TEXT NULL,
  domain             TEXT NULL,
  style              TEXT NULL,
  glossary           JSONB NOT NULL DEFAULT '{}'::jsonb,
  translation_notes  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
);

CREATE TABLE IF NOT EXISTS semantic_chunks (
  id             BIGSERIAL PRIMARY KEY,
  project_id     VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  chunk_index    INTEGER NOT NULL,
  text           TEXT NOT NULL,
  translation    TEXT NULL,
  asr_segment_ids INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
  UNIQUE (project_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_semantic_chunks_project_id ON semantic_chunks(project_id);

CREATE TABLE IF NOT EXISTS translation_chunks (
  id               BIGSERIAL PRIMARY KEY,
  semantic_chunk_id BIGINT NOT NULL REFERENCES semantic_chunks(id) ON DELETE CASCADE,
  chunk_order      INTEGER NOT NULL,
  text             TEXT NOT NULL,
  segment_ids      INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
  UNIQUE (semantic_chunk_id, chunk_order)
);
CREATE INDEX IF NOT EXISTS idx_translation_chunks_semantic_chunk_id ON translation_chunks(semantic_chunk_id);

CREATE TABLE IF NOT EXISTS subtitle_exports (
  id           VARCHAR PRIMARY KEY,
  project_id   VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  created_at   TIMESTAMPTZ NOT NULL,
  format       TEXT NOT NULL,
  content_mode TEXT NOT NULL,
  source       TEXT NOT NULL,
  config_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
  storage_key  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subtitle_exports_project_id ON subtitle_exports(project_id);

COMMIT;

