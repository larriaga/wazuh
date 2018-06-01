/* Copyright (C) 2009 Trend Micro Inc.
 * All right reserved.
 *
 * This program is a free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation
 */

#include "shared.h"
#include "execd.h"

char ** wcom_ca_store;

/* Read the config file */
int ExecdConfig(const char *cfgfile)
{
    int is_disabled = 0;

    const char *(xmlf[]) = {"ossec_config", "active-response", "disabled", NULL};
    const char *(blocks[]) = {"ossec_config", "active-response", "repeated_offenders", NULL};
    const char *(castore[]) = {"ossec_config", "active-response", "ca_store", NULL};
    char *disable_entry;
    char *repeated_t;
    char **repeated_a;
    int i;

    OS_XML xml;

    /* Read XML file */
    if (OS_ReadXML(cfgfile, &xml) < 0) {
        merror_exit(XML_ERROR, cfgfile, xml.err, xml.err_line);
    }

    /* We do not validate the xml in here. It is done by other processes. */
    disable_entry = OS_GetOneContentforElement(&xml, xmlf);
    if (disable_entry) {
        if (strcmp(disable_entry, "yes") == 0) {
            is_disabled = 1;
        } else if (strcmp(disable_entry, "no") == 0) {
            is_disabled = 0;
        } else {
            merror(XML_VALUEERR, "disabled", disable_entry);
            free(disable_entry);
            return (-1);
        }

        free(disable_entry);
    }

    repeated_t = OS_GetOneContentforElement(&xml, blocks);
    if (repeated_t) {
        int i = 0;
        int j = 0;
        repeated_a = OS_StrBreak(',', repeated_t, 5);
        if (!repeated_a) {
            merror(XML_VALUEERR, "repeated_offenders", repeated_t);
            free(repeated_t);
            return (-1);
        }

        while (repeated_a[i] != NULL) {
            char *tmpt = repeated_a[i];
            while (*tmpt != '\0') {
                if (*tmpt == ' ' || *tmpt == '\t') {
                    tmpt++;
                } else {
                    break;
                }
            }

            if (*tmpt == '\0') {
                i++;
                continue;
            }

            repeated_offenders_timeout[j] = atoi(tmpt);
            minfo("Adding offenders timeout: %d (for #%d)",
                    repeated_offenders_timeout[j], j + 1);
            j++;
            repeated_offenders_timeout[j] = 0;
            if (j >= 6) {
                break;
            }
            i++;
        }

        free(repeated_t);

        for (i = 0; repeated_a[i]; i++) {
            free(repeated_a[i]);
        }

        free(repeated_a);
    }

    if (wcom_ca_store = OS_GetContents(&xml, castore), wcom_ca_store) {
        for (i = 0; wcom_ca_store[i]; i++) {
            mdebug1("Added CA store '%s'.", wcom_ca_store[i]);
        }
    } else {
        mdebug1("No CA store defined.");
    }

    OS_ClearXML(&xml);

    return (is_disabled);
}
