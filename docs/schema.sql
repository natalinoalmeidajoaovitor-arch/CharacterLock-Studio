CREATE TABLE IF NOT EXISTS characters (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 prompt TEXT NOT NULL DEFAULT '', consent_confirmed INTEGER NOT NULL CHECK(consent_confirmed=1),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id), category TEXT NOT NULL,
 filename TEXT NOT NULL, media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
 relative_path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assets_character ON assets(character_id, created_at);
CREATE TABLE IF NOT EXISTS presets (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id), name TEXT NOT NULL,
 parameters TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, module TEXT NOT NULL, workflow TEXT NOT NULL,
 mapping TEXT NOT NULL, inspection TEXT NOT NULL, validation TEXT,
 original_path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, module TEXT NOT NULL, character_id TEXT NOT NULL REFERENCES characters(id),
 workflow_id TEXT NOT NULL REFERENCES workflows(id), status TEXT NOT NULL,
 parameters TEXT NOT NULL, asset_inputs TEXT NOT NULL, prompt_id TEXT,
 client_id TEXT NOT NULL, progress TEXT, error TEXT, output_assets TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS job_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
 status TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_characters (
 character_id TEXT PRIMARY KEY REFERENCES characters(id), active_revision_id TEXT,
 principal_asset_id TEXT REFERENCES assets(id), default_outfit_asset_id TEXT REFERENCES assets(id)
);
CREATE TABLE IF NOT EXISTS lab_revisions (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id),
 sheet_asset_id TEXT NOT NULL REFERENCES assets(id), created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lab_revision_character ON lab_revisions(character_id,created_at);
CREATE TABLE IF NOT EXISTS lab_assets (
 asset_id TEXT PRIMARY KEY REFERENCES assets(id), character_id TEXT NOT NULL REFERENCES characters(id),
 stage TEXT NOT NULL, category TEXT NOT NULL, approval TEXT NOT NULL DEFAULT 'pending',
 priority INTEGER NOT NULL DEFAULT 0, revision_id TEXT REFERENCES lab_revisions(id),
 legacy INTEGER NOT NULL DEFAULT 0, outfit_name TEXT, job_id TEXT REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS lab_asset_character ON lab_assets(character_id,stage,revision_id);
CREATE TABLE IF NOT EXISTS lab_workflows (
 workflow_id TEXT PRIMARY KEY REFERENCES workflows(id), stage TEXT NOT NULL,
 config TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_jobs (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), character_id TEXT NOT NULL REFERENCES characters(id),
 stage TEXT NOT NULL, revision_id TEXT REFERENCES lab_revisions(id), context TEXT NOT NULL,
 created_at TEXT NOT NULL
);
