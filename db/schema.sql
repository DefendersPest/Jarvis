-- JARVIS central database schema (generated from jarvis/db/models.py)

CREATE TABLE agents (
	id INTEGER NOT NULL IDENTITY, 
	[key] VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description NVARCHAR(max) NULL, 
	enabled BIT NOT NULL, 
	schedule VARCHAR(64) NULL, 
	permissions NVARCHAR(max) NOT NULL, 
	config NVARCHAR(max) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE ([key])
);

CREATE TABLE audit_log (
	id INTEGER NOT NULL IDENTITY, 
	at DATETIMEOFFSET NOT NULL, 
	actor VARCHAR(100) NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	target VARCHAR(300) NULL, 
	detail NVARCHAR(max) NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE companies (
	id INTEGER NOT NULL IDENTITY, 
	slug VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	timezone VARCHAR(64) NOT NULL, 
	workdays VARCHAR(20) NOT NULL, 
	active BIT NOT NULL, 
	acquired_on DATETIME NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
);

CREATE TABLE report_runs (
	id INTEGER NOT NULL IDENTITY, 
	report_type VARCHAR(64) NOT NULL, 
	scope VARCHAR(64) NOT NULL, 
	report_date DATETIME NOT NULL, 
	window_start DATETIME NOT NULL, 
	window_end DATETIME NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	attempts INTEGER NOT NULL, 
	data_source VARCHAR(32) NOT NULL, 
	ai_model VARCHAR(64) NULL, 
	ai_used BIT NOT NULL, 
	facts NVARCHAR(max) NULL, 
	narrative NVARCHAR(max) NULL, 
	rendered_markdown NVARCHAR(max) NULL, 
	destination VARCHAR(200) NULL, 
	delivered_at DATETIMEOFFSET NULL, 
	error NVARCHAR(max) NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (report_type, scope, report_date)
);

CREATE TABLE branches (
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	slug VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	source_office_id VARCHAR(64) NULL, 
	active BIT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, slug), 
	FOREIGN KEY(company_id) REFERENCES companies (id)
);

CREATE TABLE integrations (
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	config NVARCHAR(max) NOT NULL, 
	secret_names NVARCHAR(max) NOT NULL, 
	enabled BIT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, kind), 
	FOREIGN KEY(company_id) REFERENCES companies (id)
);

CREATE TABLE sync_runs (
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	entity VARCHAR(32) NOT NULL, 
	window_start DATETIME NOT NULL, 
	window_end DATETIME NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	records INTEGER NOT NULL, 
	started_at DATETIMEOFFSET NOT NULL, 
	finished_at DATETIMEOFFSET NULL, 
	error NVARCHAR(max) NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id)
);

CREATE INDEX ix_sync_lookup ON sync_runs (company_id, entity, status);

CREATE TABLE agent_findings (
	id INTEGER NOT NULL IDENTITY, 
	agent_key VARCHAR(64) NOT NULL, 
	report_run_id INTEGER NULL, 
	company_id INTEGER NULL, 
	branch_id INTEGER NULL, 
	severity VARCHAR(16) NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	detail NVARCHAR(max) NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(report_run_id) REFERENCES report_runs (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_findings_open ON agent_findings (company_id, status);

CREATE TABLE appointments (
	customer_source_id VARCHAR(64) NULL, 
	subscription_source_id VARCHAR(64) NULL, 
	scheduled_date DATETIME NOT NULL, 
	completed_date DATETIME NULL, 
	status VARCHAR(32) NOT NULL, 
	service_type VARCHAR(100) NULL, 
	technician_source_id VARCHAR(64) NULL, 
	is_initial BIT NOT NULL, 
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	branch_id INTEGER NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	source_updated_at DATETIMEOFFSET NULL, 
	ingested_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, source_system, source_id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_appts_date ON appointments (company_id, scheduled_date);

CREATE INDEX ix_appointments_company_id ON appointments (company_id);

CREATE TABLE customers (
	status VARCHAR(32) NOT NULL, 
	date_added DATETIME NULL, 
	date_cancelled DATETIME NULL, 
	lead_source VARCHAR(100) NULL, 
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	branch_id INTEGER NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	source_updated_at DATETIMEOFFSET NULL, 
	ingested_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, source_system, source_id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_customers_added ON customers (company_id, date_added);

CREATE INDEX ix_customers_cancelled ON customers (company_id, date_cancelled);

CREATE INDEX ix_customers_company_id ON customers (company_id);

CREATE TABLE employees (
	name VARCHAR(200) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	active BIT NOT NULL, 
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	branch_id INTEGER NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	source_updated_at DATETIMEOFFSET NULL, 
	ingested_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, source_system, source_id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_employees_company_id ON employees (company_id);

CREATE TABLE goals (
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	branch_id INTEGER NULL, 
	metric_key VARCHAR(64) NOT NULL, 
	period VARCHAR(16) NOT NULL, 
	period_start DATETIME NULL, 
	target FLOAT NOT NULL, 
	direction VARCHAR(16) NOT NULL, 
	notes VARCHAR(500) NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, branch_id, metric_key, period, period_start), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE TABLE invoices (
	customer_source_id VARCHAR(64) NULL, 
	appointment_source_id VARCHAR(64) NULL, 
	invoice_date DATETIME NOT NULL, 
	subtotal NUMERIC(14, 2) NOT NULL, 
	tax NUMERIC(14, 2) NOT NULL, 
	total NUMERIC(14, 2) NOT NULL, 
	balance NUMERIC(14, 2) NULL, 
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	branch_id INTEGER NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	source_updated_at DATETIMEOFFSET NULL, 
	ingested_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, source_system, source_id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_invoices_company_id ON invoices (company_id);

CREATE INDEX ix_invoices_date ON invoices (company_id, invoice_date);

CREATE TABLE metric_snapshots (
	id INTEGER NOT NULL IDENTITY, 
	report_run_id INTEGER NULL, 
	company_id INTEGER NULL, 
	branch_id INTEGER NULL, 
	metric_key VARCHAR(64) NOT NULL, 
	period_start DATETIME NOT NULL, 
	period_end DATETIME NOT NULL, 
	value FLOAT NULL, 
	status VARCHAR(16) NOT NULL, 
	detail NVARCHAR(max) NULL, 
	computed_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(report_run_id) REFERENCES report_runs (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_metric_lookup ON metric_snapshots (company_id, metric_key, period_end);

CREATE TABLE payments (
	customer_source_id VARCHAR(64) NULL, 
	payment_date DATETIME NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	method VARCHAR(32) NULL, 
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	branch_id INTEGER NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	source_updated_at DATETIMEOFFSET NULL, 
	ingested_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, source_system, source_id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_payments_date ON payments (company_id, payment_date);

CREATE INDEX ix_payments_company_id ON payments (company_id);

CREATE TABLE subscriptions (
	customer_source_id VARCHAR(64) NULL, 
	service_type VARCHAR(100) NULL, 
	status VARCHAR(32) NOT NULL, 
	date_added DATETIME NULL, 
	date_cancelled DATETIME NULL, 
	cancellation_reason VARCHAR(200) NULL, 
	sold_by_source_id VARCHAR(64) NULL, 
	initial_price NUMERIC(14, 2) NULL, 
	recurring_price NUMERIC(14, 2) NULL, 
	annual_value NUMERIC(14, 2) NULL, 
	id INTEGER NOT NULL IDENTITY, 
	company_id INTEGER NOT NULL, 
	branch_id INTEGER NULL, 
	source_system VARCHAR(32) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	source_updated_at DATETIMEOFFSET NULL, 
	ingested_at DATETIMEOFFSET NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_id, source_system, source_id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(branch_id) REFERENCES branches (id)
);

CREATE INDEX ix_subs_added ON subscriptions (company_id, date_added);

CREATE INDEX ix_subscriptions_company_id ON subscriptions (company_id);

CREATE INDEX ix_subs_cancelled ON subscriptions (company_id, date_cancelled);

