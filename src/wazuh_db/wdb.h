/*
 * Wazuh SQLite integration
 * Copyright (C) 2016 Wazuh Inc.
 * June 06, 2016.
 *
 * This program is a free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation.
 */

#ifndef WDB_H
#define WDB_H

#include <shared.h>
#include <pthread.h>
#include "external/sqlite/sqlite3.h"
#include "syscheck_op.h"
#include "rootcheck_op.h"

#define WDB_AGENT_EMPTY 0
#define WDB_AGENT_PENDING 1
#define WDB_AGENT_UPDATED 2

#define WDB_FILE_TYPE_FILE 0
#define WDB_FILE_TYPE_REGISTRY 1

#define WDB_FIM_NOT_FOUND 0
#define WDB_FIM_ADDED 1
#define WDB_FIM_MODIFIED 2
#define WDB_FIM_READDED 3
#define WDB_FIM_DELETED 4

#define WDB_SYSCHECK 0
#define WDB_SYSCHECK_REGISTRY 1
#define WDB_ROOTCHECK 2
#define WDB_AGENTINFO 3
#define WDB_GROUPS 4
#define WDB_SYSCOLLECTOR 5

#define WDB_STMT_FIM_LOAD 0
#define WDB_STMT_FIM_FIND_ENTRY 1
#define WDB_STMT_FIM_INSERT_ENTRY 2
#define WDB_STMT_FIM_UPDATE_ENTRY 3
#define WDB_STMT_OSINFO_INSERT 4
#define WDB_STMT_OSINFO_DEL 5
#define WDB_STMT_PROGRAM_INSERT 6
#define WDB_STMT_PROGRAM_DEL 7
#define WDB_STMT_HWINFO_INSERT 8
#define WDB_STMT_HWINFO_DEL 9
#define WDB_STMT_PORT_INSERT 10
#define WDB_STMT_PORT_DEL 11
#define WDB_STMT_PROC_INSERT 12
#define WDB_STMT_PROC_DEL 13
#define WDB_STMT_SIZE 14

typedef struct wdb_t {
    sqlite3 * db;
    sqlite3_stmt * stmt[WDB_STMT_SIZE];
    char * agent_id;
    unsigned int refcount;
    unsigned int transaction:1;
    time_t last;
    pthread_mutex_t mutex;
    struct wdb_t * next;
} wdb_t;

typedef struct wdb_config {
    int sock_queue_size;
    int worker_pool_size;
    int commit_time;
    int open_db_limit;
} wdb_config;

/* Global SQLite database */
extern sqlite3 *wdb_global;

extern char *schema_global_sql;
extern char *schema_agents_sql;

extern wdb_config config;
extern pthread_mutex_t pool_mutex;
extern wdb_t * db_pool;
extern int db_pool_size;
extern OSHash * open_dbs;

/* Open global database. Returns 0 on success or -1 on failure. */
int wdb_open_global();

/* Close global database */
void wdb_close_global();

/* Open database for agent */
sqlite3* wdb_open_agent(int id_agent, const char *name);

// Open database for agent and store in DB pool. It returns a locked database or NULL
wdb_t * wdb_open_agent2(int agent_id);

/* Get the file offset. Returns -1 on error or NULL. */
long wdb_get_agent_offset(int id_agent, int type);

/* Set the file offset. Returns number of affected rows, or -1 on failure. */
int wdb_set_agent_offset(int id_agent, int type, long offset);

/* Set agent updating status. Returns WDB_AGENT_*, or -1 on error. */
int wdb_get_agent_status(int id_agent);

/* Set agent updating status. Returns number of affected rows, or -1 on error. */
int wdb_set_agent_status(int id_agent, int status);

/* Get agent name from location string */
char* wdb_agent_loc2name(const char *location);

/* Find file: returns ID, or 0 if it doesn't exists, or -1 on error. */
int wdb_find_file(sqlite3 *db, const char *path, int type);

/* Find file, Returns ID, or -1 on error. */
int wdb_insert_file(sqlite3 *db, const char *path, int type);

/* Get last event from file: returns WDB_FIM_*, or -1 on error. */
int wdb_get_last_fim(sqlite3 *db, const char *path, int type);

/* Insert FIM entry. Returns ID, or -1 on error. */
int wdb_insert_fim(sqlite3 *db, int type, long timestamp, const char *f_name, const char *event, const sk_sum_t *sum);

int wdb_syscheck_load(wdb_t * wdb, const char * file, char * output, size_t size);

int wdb_syscheck_save(wdb_t * wdb, int ftype, char * checksum, const char * file);

// Find file entry: returns 1 if found, 0 if not, or -1 on error.
int wdb_fim_find_entry(wdb_t * wdb, const char * path);

int wdb_fim_insert_entry(wdb_t * wdb, const char * file, int ftype, const sk_sum_t * sum);

int wdb_fim_update_entry(wdb_t * wdb, const char * file, const sk_sum_t * sum);

/* Insert policy monitoring entry. Returns ID on success or -1 on error. */
int wdb_insert_pm(sqlite3 *db, const rk_event_t *event);

/* Update policy monitoring last date. Returns number of affected rows on success or -1 on error. */
int wdb_update_pm(sqlite3 *db, const rk_event_t *event);

/* Insert agent. It opens and closes the DB. Returns 0 on success or -1 on error. */
int wdb_insert_agent(int id, const char *name, const char *ip, const char *key, const char *group);

/* Update agent name. It doesn't rename agent DB file. It opens and closes the DB. Returns 0 on success or -1 on error. */
int wdb_update_agent_name(int id, const char *name);

/* Update agent version. It opens and closes the DB. Returns number of affected rows or -1 on error. */
int wdb_update_agent_version(int id, const char *os_name, const char *os_version, const char *os_major, const char *os_minor, const char *os_codename, const char *os_platform, const char *os_build, const char *os_uname, const char *os_arch, const char *version, const char *config_sum, const char *merged_sum, const char *manager_host, const char *node_name);

/* Update agent's last keepalive. It opens and closes the DB. Returns number of affected rows or -1 on error. */
int wdb_update_agent_keepalive(int id, long keepalive);

/* Update agent group. It opens and closes the DB. Returns number of affected rows or -1 on error. */
int wdb_update_agent_group(int id, const char *group);

/* Delete agent. It opens and closes the DB. Returns 0 on success or -1 on error. */
int wdb_remove_agent(int id);

/* Get name from agent. The string must be freed after using. Returns NULL on error. */
char* wdb_agent_name(int id);

/* Create database for agent from profile. Returns 0 on success or -1 on error. */
int wdb_create_agent_db(int id, const char *name);

int wdb_create_agent_db2(const char * agent_id);

int wdb_fill_metadata(sqlite3 * db);

/* Create database for agent from profile. Returns 0 on success or -1 on error. */
int wdb_remove_agent_db(int id, const char * name);

/* Prepare SQL query with availability waiting */
int wdb_prepare(sqlite3 *db, const char *zSql, int nByte, sqlite3_stmt **stmt, const char **pzTail);

/* Execute statement with availability waiting */
int wdb_step(sqlite3_stmt *stmt);

/* Begin transaction */
int wdb_begin(sqlite3 *db);
int wdb_begin2(wdb_t * wdb);

/* Commit transaction */
int wdb_commit(sqlite3 *db);
int wdb_commit2(wdb_t * wdb);

/* Create global database */
int wdb_create_global(const char *path);

/* Create profile database */
int wdb_create_profile(const char *path);

/* Create new database file from SQL script */
int wdb_create_file(const char *path, const char *source);

/* Get an array containing the ID of every agent (except 0), ended with -1 */
int* wdb_get_all_agents();

/* Find agent by name and address. Returns ID if success or -1 on failure. */
int wdb_find_agent(const char *name, const char *ip);

/* Delete FIM events of an agent. Returns number of affected rows on success or -1 on error. */
int wdb_delete_fim(int id);

/* Delete FIM events of all agents. */
void wdb_delete_fim_all();

/* Delete PM events of an agent. Returns number of affected rows on success or -1 on error. */
int wdb_delete_pm(int id);

/* Delete PM events of all agents */
void wdb_delete_pm_all();

/* Rebuild database. Returns 0 on success or -1 on error. */
int wdb_vacuum(sqlite3 *db);

/* Insert key-value pair into info table */
int wdb_insert_info(const char *key, const char *value);

// Insert OS info tuple. Return 0 on success or -1 on error.
int wdb_osinfo_insert(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * hostname, const char * architecture, const char * os_name, const char * os_version, const char * os_codename, const char * os_major, const char * os_minor, const char * os_build, const char * os_platform, const char * sysname, const char * release, const char * version);

// Save OS info into DB.
int wdb_osinfo_save(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * hostname, const char * architecture, const char * os_name, const char * os_version, const char * os_codename, const char * os_major, const char * os_minor, const char * os_build, const char * os_platform, const char * sysname, const char * release, const char * version);

// Insert HW info tuple. Return 0 on success or -1 on error.
int wdb_hardware_insert(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * serial, const char * cpu_name, int cpu_cores, const char * cpu_mhz, long ram_total, long ram_free);

// Save HW info into DB.
int wdb_hardware_save(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * serial, const char * cpu_name, int cpu_cores, const char * cpu_mhz, long ram_total, long ram_free);

// Insert program info tuple. Return 0 on success or -1 on error.
int wdb_program_insert(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * format, const char * name, const char * vendor, const char * version, const char * architecture, const char * description);

// Save Program info into DB.
int wdb_program_save(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * format, const char * name, const char * vendor, const char * version, const char * architecture, const char * description);

// Delete Program info about previous scan from DB.
int wdb_program_delete(wdb_t * wdb, const char * scan_id);

// Insert program info tuple. Return 0 on success or -1 on error.
int wdb_process_insert(wdb_t * wdb, const char * scan_id, const char * scan_time, int pid, const char * name, const char * state, int ppid, int utime, int stime, const char * cmd, const char * argvs, const char * euser, const char * ruser, const char * suser, const char * egroup, const char * rgroup, const char * sgroup, const char * fgroup, int priority, int nice, int size, int vm_size, int resident, int share, int start_time, int pgrp, int session, int nlwp, int tgid, int tty, int processor);

// Save Program info into DB.
int wdb_process_save(wdb_t * wdb, const char * scan_id, const char * scan_time, int pid, const char * name, const char * state, int ppid, int utime, int stime, const char * cmd, const char * argvs, const char * euser, const char * ruser, const char * suser, const char * egroup, const char * rgroup, const char * sgroup, const char * fgroup, int priority, int nice, int size, int vm_size, int resident, int share, int start_time, int pgrp, int session, int nlwp, int tgid, int tty, int processor);

// Delete Program info about previous scan from DB.
int wdb_process_delete(wdb_t * wdb, const char * scan_id);

// Insert port info tuple. Return 0 on success or -1 on error.
int wdb_port_insert(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * protocol, const char * local_ip, int local_port, const char * remote_ip, int remote_port, int tx_queue, int rx_queue, int inode, const char * state, int pid, const char * process);

// Save port info into DB.
int wdb_port_save(wdb_t * wdb, const char * scan_id, const char * scan_time, const char * protocol, const char * local_ip, int local_port, const char * remote_ip, int remote_port, int tx_queue, int rx_queue, int inode, const char * state, int pid, const char * process);

// Delete port info about previous scan from DB.
int wdb_port_delete(wdb_t * wdb, const char * scan_id);

wdb_t * wdb_init(sqlite3 * db, const char * agent_id);

void wdb_destroy(wdb_t * wdb);

void wdb_pool_append(wdb_t * wdb);

void wdb_pool_remove(wdb_t * wdb);

void wdb_close_all();

void wdb_commit_old();

void wdb_close_old();

cJSON * wdb_exec(sqlite3 * db, const char * sql);

int wdb_close(wdb_t * wdb);

void wdb_leave(wdb_t * wdb);

wdb_t * wdb_pool_find_prev(wdb_t * wdb);

int wdb_stmt_cache(wdb_t * wdb, int index);

int wdb_parse(char * input, char * output);

int wdb_parse_syscheck(wdb_t * wdb, char * input, char * output);

int wdb_parse_osinfo(wdb_t * wdb, char * input, char * output);

int wdb_parse_hardware(wdb_t * wdb, char * input, char * output);

int wdb_parse_programs(wdb_t * wdb, char * input, char * output);

int wdb_parse_ports(wdb_t * wdb, char * input, char * output);

int wdb_parse_processes(wdb_t * wdb, char * input, char * output);

#endif
