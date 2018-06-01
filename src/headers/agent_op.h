/* Copyright (C) 2009 Trend Micro Inc.
 * All rights reserved.
 *
 * This program is a free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation
 */

#ifndef __AGENT_OP_H
#define __AGENT_OP_H

/* Check if syscheck is to be executed/restarted
 * Returns 1 on success or 0 on failure (shouldn't be executed now)
 */
int os_check_restart_syscheck(void);

/* Set syscheck to be restarted
 * Returns 1 on success or 0 on failure
 */
int os_set_restart_syscheck(void);

/* Read the agent name for the current agent
 * Returns NULL on error
 */
char *os_read_agent_name(void);

/* Read the agent IP for the current agent
 * Returns NULL on error
 */
char *os_read_agent_ip(void);

/* Read the agent ID for the current agent
 * Returns NULL on error
 */
char *os_read_agent_id(void);

/* Read the agent profile name for the current agent
 * Returns NULL on error
 */
char *os_read_agent_profile(void);

/* Write the agent info inside the queue, for the other processes to read
 * Returns 1 on success or <= 0 on failure
 */
int os_write_agent_info(const char *agent_name, const char *agent_ip, const char *agent_id,
                        const char *cfg_profile_name) __attribute__((nonnull(1, 3)));

/* Read agent group. Returns 0 on success or -1 on failure. */
int get_agent_group(const char *id, char *group, size_t size);

/* Set agent group. Returns 0 on success or -1 on failure. */
int set_agent_group(const char * id, const char * group);

/*
 * Parse manager hostname from agent-info file.
 * If no such file, returns NULL.
 */

char* hostname_parse(const char *path);

#endif /* __AGENT_OP_H */
