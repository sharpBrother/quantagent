-- Dagster 1.13.22 / dagster-postgres 0.29.22 的当前表形。
-- 运行存储放在 ops。不走自建表：自建会执行 alembic，其中包含 ALTER。
-- 实例配置必须 should_autocreate_tables: false，并且 search_path=ops。
-- 升级 Dagster 若改了表形，不要改本文件；已应用迁移的 checksum 对不上会停。

CREATE TABLE ops.asset_check_executions (
	id BIGSERIAL NOT NULL, 
	asset_key TEXT, 
	check_name TEXT, 
	partition TEXT, 
	run_id VARCHAR(255), 
	execution_status VARCHAR(255), 
	evaluation_event TEXT, 
	evaluation_event_timestamp TIMESTAMP WITHOUT TIME ZONE, 
	evaluation_event_storage_id BIGINT, 
	materialization_event_storage_id BIGINT, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_asset_check_executions ON ops.asset_check_executions (asset_key, check_name, materialization_event_storage_id, partition);

CREATE UNIQUE INDEX idx_asset_check_executions_unique ON ops.asset_check_executions (asset_key, check_name, run_id, partition);

CREATE TABLE ops.asset_daemon_asset_evaluations (
	id BIGSERIAL NOT NULL, 
	evaluation_id BIGINT, 
	asset_key TEXT, 
	asset_evaluation_body TEXT, 
	num_requested INTEGER, 
	num_skipped INTEGER, 
	num_discarded INTEGER, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX idx_asset_daemon_asset_evaluations_asset_key_evaluation_id ON ops.asset_daemon_asset_evaluations (asset_key, evaluation_id);

CREATE INDEX ix_ops_asset_daemon_asset_evaluations_evaluation_id ON ops.asset_daemon_asset_evaluations (evaluation_id);

CREATE TABLE ops.asset_event_tags (
	id BIGSERIAL NOT NULL, 
	event_id BIGINT, 
	asset_key TEXT NOT NULL, 
	key TEXT NOT NULL, 
	value TEXT, 
	event_timestamp TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_asset_event_tags ON ops.asset_event_tags (asset_key, key, value);

CREATE INDEX idx_asset_event_tags_event_id ON ops.asset_event_tags (event_id);

CREATE TABLE ops.asset_keys (
	id BIGSERIAL NOT NULL, 
	asset_key VARCHAR(512), 
	last_materialization TEXT, 
	last_run_id VARCHAR(255), 
	asset_details TEXT, 
	wipe_timestamp TIMESTAMP WITHOUT TIME ZONE, 
	last_materialization_timestamp TIMESTAMP WITHOUT TIME ZONE, 
	tags TEXT, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	cached_status_data TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (asset_key)
);

CREATE TABLE ops.backfill_tags (
	id BIGSERIAL NOT NULL, 
	backfill_id VARCHAR(255), 
	key TEXT, 
	value TEXT, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_backfill_tags_backfill_id ON ops.backfill_tags (backfill_id, id);

CREATE TABLE ops.bulk_actions (
	id BIGSERIAL NOT NULL, 
	key VARCHAR(32) NOT NULL, 
	status VARCHAR(255) NOT NULL, 
	timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	body TEXT, 
	action_type VARCHAR(32), 
	selector_id TEXT, 
	job_name TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (key)
);

CREATE INDEX idx_bulk_actions ON ops.bulk_actions (key);

CREATE INDEX idx_bulk_actions_action_type ON ops.bulk_actions (action_type);

CREATE INDEX idx_bulk_actions_selector_id ON ops.bulk_actions (selector_id);

CREATE INDEX idx_bulk_actions_status ON ops.bulk_actions (status);

CREATE TABLE ops.concurrency_limits (
	id BIGSERIAL NOT NULL, 
	concurrency_key VARCHAR(512) NOT NULL, 
	"limit" INTEGER NOT NULL, 
	using_default_limit BOOLEAN DEFAULT false NOT NULL, 
	update_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (concurrency_key)
);

CREATE TABLE ops.concurrency_slots (
	id BIGSERIAL NOT NULL, 
	concurrency_key TEXT NOT NULL, 
	run_id TEXT, 
	step_key TEXT, 
	deleted BOOLEAN NOT NULL, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE ops.daemon_heartbeats (
	id BIGSERIAL NOT NULL, 
	daemon_type VARCHAR(255) NOT NULL, 
	daemon_id VARCHAR(255), 
	timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	body TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (daemon_type)
);

CREATE TABLE ops.dynamic_partitions (
	id BIGSERIAL NOT NULL, 
	partitions_def_name TEXT NOT NULL, 
	partition TEXT NOT NULL, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX idx_dynamic_partitions ON ops.dynamic_partitions (partitions_def_name, partition);

CREATE TABLE ops.event_logs (
	id BIGSERIAL NOT NULL, 
	run_id VARCHAR(255), 
	event TEXT NOT NULL, 
	dagster_event_type TEXT, 
	timestamp TIMESTAMP WITHOUT TIME ZONE, 
	step_key TEXT, 
	asset_key TEXT, 
	partition TEXT, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_event_type ON ops.event_logs (dagster_event_type, id);

CREATE INDEX idx_events_by_asset ON ops.event_logs (asset_key, dagster_event_type, id) WHERE asset_key IS NOT NULL;

CREATE INDEX idx_events_by_asset_partition ON ops.event_logs (asset_key, dagster_event_type, partition, id) WHERE asset_key IS NOT NULL AND partition IS NOT NULL;

CREATE INDEX idx_events_by_run_id ON ops.event_logs (run_id, id);

CREATE INDEX idx_step_key ON ops.event_logs (step_key);

CREATE TABLE ops.instance_info (
	id BIGSERIAL NOT NULL, 
	run_storage_id TEXT, 
	PRIMARY KEY (id)
);

CREATE TABLE ops.instigators (
	id BIGSERIAL NOT NULL, 
	selector_id VARCHAR(255), 
	repository_selector_id VARCHAR(255), 
	status VARCHAR(63), 
	instigator_type VARCHAR(63), 
	instigator_body TEXT, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	update_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (selector_id)
);

CREATE INDEX ix_ops_instigators_instigator_type ON ops.instigators (instigator_type);

CREATE TABLE ops.job_ticks (
	id BIGSERIAL NOT NULL, 
	job_origin_id VARCHAR(255), 
	selector_id VARCHAR(255), 
	status VARCHAR(63), 
	type VARCHAR(63), 
	timestamp TIMESTAMP WITHOUT TIME ZONE, 
	tick_body TEXT, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	update_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_job_tick_status ON ops.job_ticks (job_origin_id, status);

CREATE INDEX idx_job_tick_timestamp ON ops.job_ticks (job_origin_id, timestamp);

CREATE INDEX idx_tick_selector_timestamp ON ops.job_ticks (selector_id, timestamp);

CREATE INDEX ix_ops_job_ticks_job_origin_id ON ops.job_ticks (job_origin_id);

CREATE TABLE ops.jobs (
	id BIGSERIAL NOT NULL, 
	job_origin_id VARCHAR(255), 
	selector_id VARCHAR(255), 
	repository_origin_id VARCHAR(255), 
	status VARCHAR(63), 
	job_type VARCHAR(63), 
	job_body TEXT, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	update_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (job_origin_id)
);

CREATE INDEX ix_ops_jobs_job_type ON ops.jobs (job_type);

CREATE TABLE ops.kvs (
	id BIGSERIAL NOT NULL, 
	key TEXT NOT NULL, 
	value TEXT, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX idx_kvs_keys_unique ON ops.kvs (key);

CREATE TABLE ops.pending_steps (
	id BIGSERIAL NOT NULL, 
	concurrency_key TEXT NOT NULL, 
	run_id TEXT, 
	step_key TEXT, 
	priority INTEGER, 
	assigned_timestamp TIMESTAMP WITHOUT TIME ZONE, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX idx_pending_steps ON ops.pending_steps (concurrency_key, run_id, step_key);

CREATE TABLE ops.secondary_indexes (
	id BIGSERIAL NOT NULL, 
	name VARCHAR(512), 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	migration_completed TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE ops.snapshots (
	id BIGSERIAL NOT NULL, 
	snapshot_id VARCHAR(255) NOT NULL, 
	snapshot_body BYTEA NOT NULL, 
	snapshot_type VARCHAR(63) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (snapshot_id)
);

CREATE TABLE ops.runs (
	id BIGSERIAL NOT NULL, 
	run_id VARCHAR(255), 
	snapshot_id VARCHAR(255), 
	pipeline_name TEXT, 
	mode TEXT, 
	status VARCHAR(63), 
	run_body TEXT, 
	partition TEXT, 
	partition_set TEXT, 
	create_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	update_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	start_time FLOAT, 
	end_time FLOAT, 
	backfill_id VARCHAR(255), 
	PRIMARY KEY (id), 
	UNIQUE (run_id), 
	CONSTRAINT fk_runs_snapshot_id_snapshots_snapshot_id FOREIGN KEY(snapshot_id) REFERENCES ops.snapshots (snapshot_id)
);

CREATE INDEX idx_run_partitions ON ops.runs (partition_set, partition);

CREATE INDEX idx_run_range ON ops.runs (status, update_timestamp, create_timestamp);

CREATE INDEX idx_run_status ON ops.runs (status);

CREATE INDEX idx_runs_by_backfill_id ON ops.runs (backfill_id, id);

CREATE INDEX idx_runs_by_job ON ops.runs (pipeline_name, id);

CREATE TABLE ops.run_tags (
	id BIGSERIAL NOT NULL, 
	run_id VARCHAR(255), 
	key TEXT, 
	value TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES ops.runs (run_id) ON DELETE CASCADE
);

CREATE INDEX idx_run_tags ON ops.run_tags (key, value);

CREATE INDEX idx_run_tags_run_idx ON ops.run_tags (run_id, id);
