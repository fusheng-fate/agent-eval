ALTER TABLE case_results ADD COLUMN node_id TEXT;
ALTER TABLE case_results ADD COLUMN trace_no VARCHAR(128);



ALTER TABLE cases ADD COLUMN IF NOT EXISTS round_no INTEGER;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS round_size INTEGER;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS total_rounds INTEGER;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS done_rounds INTEGER DEFAULT 0;

-- 2026-09-16 · v1.8：被测 Agent 并发上限与流程模板绑定
ALTER TABLE flow_templates ADD COLUMN IF NOT EXISTS target_concurrency INTEGER NOT NULL DEFAULT 3;

ALTER TABLE runs ALTER COLUMN overall_score TYPE NUMERIC(6, 3);
ALTER TABLE case_results ALTER COLUMN overall_score TYPE NUMERIC(6, 3);

-- 2026-09-17 · v1.9
-- node_id 为 nodeId 列表，长度不可预知，VARCHAR(128) → TEXT
ALTER TABLE case_results ALTER COLUMN node_id TYPE TEXT;

-- 2026-09-17 · v2.0：单条用例执行阶段的起止时刻（调被测 Agent 的起止）
ALTER TABLE case_results ADD COLUMN IF NOT EXISTS exec_started_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE case_results ADD COLUMN IF NOT EXISTS exec_finished_at TIMESTAMP WITH TIME ZONE;