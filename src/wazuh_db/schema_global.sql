/*
 * SQL Schema for global database
 * Copyright 2016 Wazuh, Inc. <info@wazuh.com>
 * June 30, 2016.
 * This program is a free software, you can redistribute it
 * and/or modify it under the terms of GPLv2.
 */

CREATE TABLE IF NOT EXISTS agent (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ip TEXT,
    key TEXT,
    os_name TEXT,
    os_version TEXT,
    os_major TEXT,
    os_minor TEXT,
    os_codename TEXT,
    os_build TEXT,
    os_platform TEXT,
    os_uname TEXT,
    os_arch TEXT,
    version TEXT,
    config_sum TEXT,
    merged_sum TEXT,
    manager_host TEXT,
    node_name TEXT DEFAULT 'unknown',
    date_add TEXT NOT NULL,
    last_keepalive TEXT,
    status TEXT NOT NULL CHECK (status IN ('empty', 'pending', 'updated')) DEFAULT 'empty',
    fim_offset INTEGER NOT NULL DEFAULT 0,
    reg_offset INTEGER NOT NULL DEFAULT 0,
    `group` TEXT DEFAULT 'default'
);

CREATE INDEX IF NOT EXISTS agent_name ON agent (name);
CREATE INDEX IF NOT EXISTS agent_ip ON agent (ip);

INSERT INTO agent (id, name, date_add, last_keepalive, `group`) VALUES (0, 'localhost', datetime(CURRENT_TIMESTAMP, 'localtime'), '9999-12-31 23:59:59', NULL);

CREATE TABLE IF NOT EXISTS info (
    key TEXT PRIMARY KEY,
    value TEXT
);

PRAGMA journal_mode=WAL;
