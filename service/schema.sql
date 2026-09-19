-- schema.sql
-- 由 scripts/dump_schema.py 从 ORM (app/models) 自动生成，请勿手工编辑。
-- 导入：psql -U <user> -d <db> -f schema.sql

CREATE TABLE configs (
	id UUID NOT NULL, 
	config_key VARCHAR(128) NOT NULL, 
	config_value JSONB NOT NULL, 
	scope VARCHAR(16) NOT NULL, 
	editable_by VARCHAR(16) NOT NULL, 
	description VARCHAR(255), 
	updated_by UUID, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (config_key)
);


CREATE TABLE datasets (
	id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	case_count INTEGER NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	column_mapping JSONB, 
	owner_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_datasets_owner_id ON datasets (owner_id);


CREATE TABLE evaluators (
	id UUID NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	description TEXT, 
	is_standard BOOLEAN NOT NULL, 
	created_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);


CREATE TABLE flow_templates (
	id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	chain_json JSONB NOT NULL, 
	target_concurrency INTEGER NOT NULL, 
	created_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);


CREATE TABLE metrics (
	id UUID NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	category VARCHAR(16) NOT NULL, 
	industry VARCHAR(64), 
	description TEXT, 
	skill_md TEXT NOT NULL, 
	is_builtin BOOLEAN NOT NULL, 
	created_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);


CREATE TABLE reports (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	task_name VARCHAR(255) NOT NULL, 
	owner_id UUID NOT NULL, 
	summary JSONB NOT NULL, 
	standard_metric_averages JSONB, 
	extra_metric_averages JSONB, 
	dimension_summary JSONB, 
	case_details JSONB, 
	failure_root_causes JSONB, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_reports_run_id ON reports (run_id);

CREATE INDEX ix_reports_owner_id ON reports (owner_id);


CREATE TABLE runs (
	id UUID NOT NULL, 
	task_name VARCHAR(255) NOT NULL, 
	owner_id UUID NOT NULL, 
	evaluator_id UUID NOT NULL, 
	dataset_id UUID NOT NULL, 
	flow_template_id UUID, 
	mode VARCHAR(16) NOT NULL, 
	extra_metric_ids UUID[] NOT NULL, 
	overrides JSONB, 
	status VARCHAR(16) NOT NULL, 
	total_cases INTEGER NOT NULL, 
	done_cases INTEGER NOT NULL, 
	passed_cases INTEGER NOT NULL, 
	failed_cases INTEGER NOT NULL, 
	overall_score NUMERIC(6, 3), 
	model_concurrency INTEGER NOT NULL, 
	target_concurrency INTEGER NOT NULL, 
	round_size INTEGER, 
	total_rounds INTEGER, 
	done_rounds INTEGER, 
	exec_sec NUMERIC(10, 2), 
	score_sec NUMERIC(10, 2), 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_runs_status ON runs (status);

CREATE INDEX ix_runs_owner_id ON runs (owner_id);


CREATE TABLE user_configs (
	user_id UUID NOT NULL, 
	config_key VARCHAR(128) NOT NULL, 
	config_value JSONB NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id, config_key)
);


CREATE TABLE users (
	id UUID NOT NULL, 
	username VARCHAR(64) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	display_name VARCHAR(128), 
	role VARCHAR(16) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_username ON users (username);


CREATE TABLE cases (
	id UUID NOT NULL, 
	dataset_id UUID NOT NULL, 
	case_no VARCHAR(128) NOT NULL, 
	user_input TEXT NOT NULL, 
	expected_gt TEXT NOT NULL, 
	dimension_l1 VARCHAR(128), 
	dimension_l2 VARCHAR(128), 
	preset TEXT, 
	steps TEXT, 
	tags JSONB, 
	extra JSONB, 
	sort_order INTEGER NOT NULL, 
	round_no INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (id)
);

CREATE INDEX ix_cases_dataset_id ON cases (dataset_id);


CREATE TABLE evaluator_metrics (
	evaluator_id UUID NOT NULL, 
	metric_id UUID NOT NULL, 
	weight NUMERIC(5, 4) NOT NULL, 
	sort_order INTEGER NOT NULL, 
	PRIMARY KEY (evaluator_id, metric_id), 
	FOREIGN KEY(evaluator_id) REFERENCES evaluators (id), 
	FOREIGN KEY(metric_id) REFERENCES metrics (id)
);


CREATE TABLE flow_template_param_perms (
	template_id UUID NOT NULL, 
	param_path VARCHAR(255) NOT NULL, 
	user_editable BOOLEAN NOT NULL, 
	PRIMARY KEY (template_id, param_path), 
	FOREIGN KEY(template_id) REFERENCES flow_templates (id)
);


CREATE TABLE run_logs (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	level VARCHAR(16) NOT NULL, 
	message TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id)
);

CREATE INDEX ix_run_logs_run_id ON run_logs (run_id);


CREATE TABLE case_results (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	overall_score NUMERIC(6, 3), 
	standard_metrics JSONB, 
	extra_metrics JSONB, 
	brief_comment TEXT, 
	agent_output TEXT, 
	token_usage INTEGER, 
	latency_sec NUMERIC(8, 2), 
	error_msg TEXT, 
	raw_llm JSONB, 
	failure_attribution JSONB, 
	target_trace JSONB, 
	node_id TEXT, 
	trace_no VARCHAR(128), 
	attempt INTEGER NOT NULL, 
	exec_started_at TIMESTAMP WITH TIME ZONE, 
	exec_finished_at TIMESTAMP WITH TIME ZONE, 
	locked_by VARCHAR(64), 
	locked_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id), 
	FOREIGN KEY(case_id) REFERENCES cases (id)
);

CREATE INDEX ix_case_results_run_id ON case_results (run_id);

CREATE INDEX ix_case_results_status ON case_results (status);
