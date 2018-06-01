/* Copyright (C) 2009 Trend Micro Inc.
 * All right reserved.
 *
 * This program is a free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation
 */

#include "shared.h"
#include "localfile-config.h"
#include "config.h"

int Read_Localfile(XML_NODE node, void *d1, __attribute__((unused)) void *d2)
{
    unsigned int pl = 0;
    unsigned int pl_base = 0;
    unsigned int i = 0;
    unsigned int glob_set = 0;
#ifndef WIN32
    int glob_offset = 0;
#endif

    /* XML Definitions */
    const char *xml_localfile_location = "location";
    const char *xml_localfile_command = "command";
    const char *xml_localfile_logformat = "log_format";
    const char *xml_localfile_frequency = "frequency";
    const char *xml_localfile_alias = "alias";
    const char *xml_localfile_future = "only-future-events";
    const char *xml_localfile_query = "query";
    const char *xml_localfile_label = "label";

    logreader *logf;
    logreader_config *log_config;
    size_t labels_z=0;

    log_config = (logreader_config *)d1;

    /* If config is not set, create it */
    if (!log_config->config) {
        os_calloc(2, sizeof(logreader), log_config->config);
        logf = log_config->config;
        logf[0].file = NULL;
        logf[0].command = NULL;
        logf[0].alias = NULL;
        logf[0].logformat = NULL;
        logf[0].future = 0;
        logf[0].query = NULL;
        logf[1].file = NULL;
        logf[1].command = NULL;
        logf[1].alias = NULL;
        logf[1].logformat = NULL;
        logf[1].future = 0;
        logf[1].query = NULL;
    } else {
        logf = log_config->config;
        while (logf[pl].file != NULL) {
            pl++;
        }

        pl_base = pl;

        /* Allocate more memory */
        os_realloc(logf, (pl + 2)*sizeof(logreader), log_config->config);
        logf = log_config->config;
        logf[pl + 1].file = NULL;
        logf[pl + 1].command = NULL;
        logf[pl + 1].alias = NULL;
        logf[pl + 1].logformat = NULL;
        logf[pl + 1].future = 0;
        logf[pl + 1].query = NULL;
        logf[pl + 1].linecount = 0;
    }

    logf[pl].file = NULL;
    logf[pl].command = NULL;
    logf[pl].alias = NULL;
    logf[pl].logformat = NULL;
    logf[pl].future = 0;
    logf[pl].query = NULL;
    os_calloc(1, sizeof(wlabel_t), logf[pl].labels);
    logf[pl].fp = NULL;
    logf[pl].ffile = NULL;
    logf[pl].djb_program_name = NULL;
    logf[pl].ign = 360;
    logf[pl].linecount = 0;


    /* Search for entries related to files */
    i = 0;
    while (node[i]) {
        if (!node[i]->element) {
            merror(XML_ELEMNULL);
            return (OS_INVALID);
        } else if (!node[i]->content) {
            merror(XML_VALUENULL, node[i]->element);
            return (OS_INVALID);
        } else if (strcmp(node[i]->element, xml_localfile_future) == 0) {
            if (strcmp(node[i]->content, "yes") == 0) {
                logf[pl].future = 1;
            }
        } else if (strcmp(node[i]->element, xml_localfile_query) == 0) {
            os_strdup(node[i]->content, logf[pl].query);
        } else if (strcmp(node[i]->element, xml_localfile_label) == 0) {
            char *key_value = 0;
            int j;
            for (j = 0; node[i]->attributes && node[i]->attributes[j]; j++) {
                if (strcmp(node[i]->attributes[j], "key") == 0) {
                    if (strlen(node[i]->values[j]) > 0) {
                        key_value = node[i]->values[j];
                    } else {
                        merror("Label with empty key.");
                        return (OS_INVALID);
                    }
                }
            }
            if (!key_value) {
                merror("Expected 'key' attribute for label.");
                return (OS_INVALID);
            }

            logf[pl_base].labels = labels_add(logf[pl_base].labels, &labels_z, key_value, node[i]->content, 0, 1);
        } else if (strcmp(node[i]->element, xml_localfile_command) == 0) {
            /* We don't accept remote commands from the manager - just in case */
            if (log_config->agent_cfg == 1 && log_config->accept_remote == 0) {
                merror("Remote commands are not accepted from the manager. "
                       "Ignoring it on the agent.conf");

                logf[pl].file = NULL;
                logf[pl].ffile = NULL;
                logf[pl].command = NULL;
                logf[pl].alias = NULL;
                logf[pl].logformat = NULL;
                logf[pl].fp = NULL;
                labels_free(logf[pl].labels);
                return 0;
            }

            os_strdup(node[i]->content, logf[pl].file);
            logf[pl].command = logf[pl].file;
        } else if (strcmp(node[i]->element, xml_localfile_frequency) == 0) {

            if(strcmp(node[i]->content,  "hourly") == 0)
            {
                logf[pl].ign = 3600;
            }
            else if(strcmp(node[i]->content,  "daily") == 0)
            {
                logf[pl].ign = 86400;
            }
            else
            {

                if (!OS_StrIsNum(node[i]->content)) {
                    merror(XML_VALUEERR, node[i]->element, node[i]->content);
                    return (OS_INVALID);
                }

                logf[pl].ign = atoi(node[i]->content);
            }
        } else if (strcmp(node[i]->element, xml_localfile_location) == 0) {
        #ifdef WIN32
            /* Expand variables on Windows */
            if (strchr(node[i]->content, '%')) {
                int expandreturn = 0;
                char newfile[OS_MAXSTR + 1];

                newfile[OS_MAXSTR] = '\0';
                expandreturn = ExpandEnvironmentStrings(node[i]->content,
                                                        newfile, OS_MAXSTR);

                if ((expandreturn > 0) && (expandreturn < OS_MAXSTR)) {
                    free(node[i]->content);

                    os_strdup(newfile, node[i]->content);
                }
            }
        #endif

            /* This is a glob*
             * We will call this file multiple times until
             * there is no one else available.
             */
#ifndef WIN32 /* No windows support for glob */
            if (strchr(node[i]->content, '*') ||
                    strchr(node[i]->content, '?') ||
                    strchr(node[i]->content, '[')) {
                glob_t g;

                /* Setting to the first entry of the glob */
                if (glob_set == 0) {
                    glob_set = pl + 1;
                }

                if (glob(node[i]->content, 0, NULL, &g) != 0) {
                    merror(GLOB_ERROR, node[i]->content);
                    os_strdup(node[i]->content, logf[pl].file);
                    i++;
                    continue;
                }

                /* Check for the last entry */
                if ((g.gl_pathv[glob_offset]) == NULL) {
                    /* Check when nothing is found */
                    if (glob_offset == 0) {
                        merror(GLOB_NFOUND, node[i]->content);
                        return (OS_INVALID);
                    }
                    i++;
                    continue;
                }


                while(g.gl_pathv[glob_offset] != NULL)
                {
                    /* Check for strftime on globs too */
                    if (strchr(g.gl_pathv[glob_offset], '%')) {
                        struct tm *p;
                        time_t l_time = time(0);
                        char lfile[OS_FLSIZE + 1];
                        size_t ret;

                        p = localtime(&l_time);

                        lfile[OS_FLSIZE] = '\0';
                        ret = strftime(lfile, OS_FLSIZE, g.gl_pathv[glob_offset], p);
                        if (ret == 0) {
                            merror(PARSE_ERROR, g.gl_pathv[glob_offset]);
                            return (OS_INVALID);
                        }

                        os_strdup(g.gl_pathv[glob_offset], logf[pl].ffile);
                        os_strdup(g.gl_pathv[glob_offset], logf[pl].file);
                    } else {
                        os_strdup(g.gl_pathv[glob_offset], logf[pl].file);
                    }

                    glob_offset++;

                    /* Now we need to create another file entry */
                    pl++;
                    os_realloc(logf, (pl +2)*sizeof(logreader), log_config->config);
                    logf = log_config->config;

                    logf[pl].file = NULL;
                    logf[pl].alias = NULL;
                    logf[pl].logformat = NULL;
                    logf[pl].fp = NULL;
                    logf[pl].ffile = NULL;
                    logf[pl].djb_program_name = NULL;
                    logf[pl].labels = NULL;
                    logf[pl].query = NULL;

                    logf[pl +1].file = NULL;
                    logf[pl +1].alias = NULL;
                    logf[pl +1].logformat = NULL;
                    logf[pl +1].fp = NULL;
                    logf[pl +1].ffile = NULL;
                    logf[pl +1].djb_program_name = NULL;
                    logf[pl +1].labels = NULL;
                    logf[pl +1].query = NULL;
                }


                globfree(&g);
            } else if (strchr(node[i]->content, '%'))
            #else
            if (strchr(node[i]->content, '%'))
            #endif /* WIN32 */

            /* We need the format file (based on date) */
            {
                struct tm *p;
                time_t l_time = time(0);
                char lfile[OS_FLSIZE + 1];
                size_t ret;

                p = localtime(&l_time);

                lfile[OS_FLSIZE] = '\0';
                ret = strftime(lfile, OS_FLSIZE, node[i]->content, p);
                if (ret != 0) {
                    os_strdup(node[i]->content, logf[pl].ffile);
                }

                os_strdup(node[i]->content, logf[pl].file);
            }

            /* Normal file */
            else {
                os_strdup(node[i]->content, logf[pl].file);
            }
        }

        /* Get log format */
        else if (strcasecmp(node[i]->element, xml_localfile_logformat) == 0) {
            os_strdup(node[i]->content, logf[pl].logformat);

            if (strcmp(logf[pl].logformat, "syslog") == 0) {
            } else if (strcmp(logf[pl].logformat, "generic") == 0) {
            } else if (strcmp(logf[pl].logformat, "json") == 0) {
            } else if (strcmp(logf[pl].logformat, "snort-full") == 0) {
            } else if (strcmp(logf[pl].logformat, "snort-fast") == 0) {
            } else if (strcmp(logf[pl].logformat, "apache") == 0) {
            } else if (strcmp(logf[pl].logformat, "iis") == 0) {
            } else if (strcmp(logf[pl].logformat, "squid") == 0) {
            } else if (strcmp(logf[pl].logformat, "nmapg") == 0) {
            } else if (strcmp(logf[pl].logformat, "mysql_log") == 0) {
            } else if (strcmp(logf[pl].logformat, "ossecalert") == 0) {
            } else if (strcmp(logf[pl].logformat, "mssql_log") == 0) {
            } else if (strcmp(logf[pl].logformat, "postgresql_log") == 0) {
            } else if (strcmp(logf[pl].logformat, "djb-multilog") == 0) {
            } else if (strcmp(logf[pl].logformat, "syslog-pipe") == 0) {
            } else if (strcmp(logf[pl].logformat, "command") == 0) {
            } else if (strcmp(logf[pl].logformat, "full_command") == 0) {
            } else if (strcmp(logf[pl].logformat, "audit") == 0) {
            } else if (strncmp(logf[pl].logformat, "multi-line", 10) == 0) {

                char *p_lf = logf[pl].logformat;
                p_lf += 10;

                while (p_lf[0] == ' ') {
                    p_lf++;
                }

                if (*p_lf != ':') {
                    merror(XML_VALUEERR, node[i]->element, node[i]->content);
                    return (OS_INVALID);
                }
                p_lf++;

                char *end;

                if (logf[pl].linecount = strtol(p_lf, &end, 10), end == p_lf || logf[pl].linecount < 1 ) {
                    merror(XML_VALUEERR, node[i]->element, node[i]->content);
                    return (OS_INVALID);
                }

            } else if (strcmp(logf[pl].logformat, EVENTLOG) == 0) {
            } else if (strcmp(logf[pl].logformat, EVENTCHANNEL) == 0) {
            } else {
                merror(XML_VALUEERR, node[i]->element, node[i]->content);
                return (OS_INVALID);
            }
        } else if (strcasecmp(node[i]->element, xml_localfile_alias) == 0) {
            os_strdup(node[i]->content, logf[pl].alias);
        } else {
            merror(XML_INVELEM, node[i]->element);
            return (OS_INVALID);
        }

        i++;
    }

    /* Validate glob entries */
    if (glob_set) {
        char *format;
        wlabel_t *labels;

        /* Get log format */
        if (logf[pl].logformat) {
            format = logf[pl].logformat;
        } else if (logf[glob_set - 1].logformat) {
            format = logf[glob_set - 1].logformat;
        } else {
            merror(MISS_LOG_FORMAT);
            return (OS_INVALID);
        }

        /* Get labels */
        if (logf[pl_base].labels) {
            labels = logf[pl_base].labels;
        } else if (logf[glob_set - 1].labels) {
            labels = logf[glob_set - 1].labels;
        } else {
            merror(MISS_LOG_FORMAT);
            return (OS_INVALID);
        }

        /* The last entry is always null on glob */
        pl--;

        /* Set format for all entries */
        for (i = (glob_set - 1); i <= pl; i++) {
            /* Every entry must be valid */
            if (!logf[i].file) {
                merror(MISS_FILE);
                return (OS_INVALID);
            }

            if (logf[i].logformat == NULL) {
                logf[i].logformat = format;
            }
            if (logf[i].labels == NULL) {
                logf[i].labels = labels;
            }

        }
    }

    /* Missing log format */
    if (!logf[pl].logformat) {
        merror(MISS_LOG_FORMAT);
        return (OS_INVALID);
    }

    /* Missing file */
    if (!logf[pl].file) {
        merror(MISS_FILE);
        return (OS_INVALID);
    }

    /* Verify a valid event log config */
    if (strcmp(logf[pl].logformat, EVENTLOG) == 0) {
        if ((strcmp(logf[pl].file, "Application") != 0) &&
                (strcmp(logf[pl].file, "System") != 0) &&
                (strcmp(logf[pl].file, "Security") != 0)) {
            /* Invalid event log */
            minfo(NSTD_EVTLOG, logf[pl].file);
            return (0);
        }
    }

    if ((strcmp(logf[pl].logformat, "command") == 0) ||
            (strcmp(logf[pl].logformat, "full_command") == 0)) {
        if (!logf[pl].command) {
            merror("Missing 'command' argument. "
                   "This option will be ignored.");
        }
    }

    return (0);
}

int Test_Localfile(const char * path){
    int fail = 0;
    logreader_config test_localfile = { .agent_cfg = 0 };

    if (ReadConfig(CAGENT_CONFIG | CLOCALFILE, path, &test_localfile, NULL) < 0) {
		merror(RCONFIG_ERROR,"Localfile", path);
		fail = 1;
	}

    Free_Localfile(&test_localfile);

    if (fail) {
        return -1;
    } else {
        return 0;
    }
}

void Free_Localfile(logreader_config * config){
    if (config) {
        if (config->config) {
            int i;
            char *last_logformat = NULL;
            wlabel_t *last_labels = NULL;

            for (i = 0; config->config[i].file; i++) {
                free(config->config[i].ffile);
                free(config->config[i].file);
                if (config->config[i].logformat != last_logformat) {
                    last_logformat = config->config[i].logformat;
                    free(config->config[i].logformat);
                }
                free(config->config[i].djb_program_name);
                free(config->config[i].alias);
                free(config->config[i].query);
                if (config->config[i].labels != last_labels) {
                    last_labels = config->config[i].labels;
                    labels_free(config->config[i].labels);
                }
                if (config->config[i].fp) {
                    fclose(config->config[i].fp);
                }
            }

            free(config->config);
        }
    }
}
