-- SubFlow schema migration 002: project media files + ASR merged chunks
-- Idempotent (IF NOT EXISTS) for safety.

BEGIN;

-- Stage 1 (audio_preprocess) output, previously stored in stage1.json
ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS media_files JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Stage 3 (asr) merged chunks, previously stored in asr_merged_chunks.json
CREATE TABLE IF NOT EXISTS asr_merged_chunks (
  id            BIGSERIAL PRIMARY KEY,
  project_id    VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  region_id     INTEGER NOT NULL,
  chunk_id      INTEGER NOT NULL,
  start_time    DOUBLE PRECISION NOT NULL,
  end_time      DOUBLE PRECISION NOT NULL,
  segment_ids   INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
  text          TEXT NOT NULL DEFAULT '',
  UNIQUE (project_id, region_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_asr_merged_chunks_project_id ON asr_merged_chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_asr_merged_chunks_project_time ON asr_merged_chunks(project_id, start_time, end_time);

COMMIT;

