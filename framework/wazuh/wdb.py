#!/usr/bin/env python

# Created by Wazuh, Inc. <info@wazuh.com>.
# This program is a free software; you can redistribute it and/or modify it under the terms of GPLv2

from wazuh import common
from wazuh.exception import WazuhException
from os.path import isfile
from os import strerror
import socket
from operator import or_, itemgetter
import re
import json

class WazuhDBConnection():
    """
    Represents a connection to the wdb socket
    """

    def __init__(self, socket_path=common.wdb_socket_path, request_slice=20, max_size=6144):
        """
        Constructor
        """
        self.socket_path = socket_path
        self.request_slice = request_slice
        self.max_size = max_size
        self.__conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.__conn.connect(self.socket_path)
        except socket.error as e:
            raise WazuhException(2005, strerror(e[0]))


    def __query_input_validation(self, query):
        """
        Checks input queries have the correct format
        """
        query_elements = query.split(" ")
        sql_first_index = 2 if query_elements[0] == 'agent' else 1

        input_val_errors = [
            (query_elements[sql_first_index] == 'sql', "Incorrect WDB request type."),
            (query_elements[0] == 'agent' or query_elements[0] == 'global', "The {} database is not valid".format(query_elements[0])),
            (query_elements[1].isdigit() if query_elements[0] == 'agent' else True, "Incorrect agent ID {}".format(query_elements[1])),
            (query_elements[sql_first_index+1] == 'select', "The API can only send select requests to WDB"),
            (not ';' in query, "Found a not valid symbol in database query: ;")
        ]

        for check, error_text in input_val_errors:
            if not check:
                raise WazuhException(2004, error_text)


    def __send(self, msg):
        """
        Sends a message to the wdb socket
        """

        self.__conn.send(msg)
        # Wazuh db can't send more than 6KB of data
        data = self.__conn.recv(self.max_size).split(" ", 1)

        if data[0] == "err":
            raise WazuhException(2003, data[1])
        else:
            return json.loads(unicode(data[1], errors='ignore'))


    def __query_lower(self, query):
        """
        Convert a query to lower except the words between ""
        """

        to_lower = True
        new_query = ""

        for i in query:
            if to_lower and i != "'":
                new_query += i.lower()
            elif to_lower and i == "'":
                new_query += i
                to_lower = False
            elif not to_lower and i != "'":
                new_query += i
            elif not to_lower and i == "'":
                new_query += i
                to_lower = True

        return new_query



    def execute(self, query, count=False):
        """
        Sends a sql query to wdb socket
        """
        query_lower = self.__query_lower(query)

        self.__query_input_validation(query_lower)

        # if the query has already a parameter limit / offset, divide using it
        offset = 0
        if 'offset' in query_lower:
            offset = int(re.compile(r".* offset (\d+)").match(query_lower).group(1))
            query_lower = query_lower.replace(" offset {}".format(offset), "")

        if 'count' not in query_lower:
            lim = 0
            if 'limit' in query_lower:
                lim  = int(re.compile(r".* limit (\d+)").match(query_lower).group(1))
                query_lower = query_lower.replace(" limit {}".format(lim), "")

            regex  = re.compile(r"\w+ \d+? sql select ([a-z0-9,*_ ]+) from")
            select = regex.match(query_lower).group(1)
            countq = query_lower.replace(select, "count(*)", 1)
            total  = self.__send(countq)[0].values()[0]

            limit = lim if lim != 0 else total

            response = []
            step = limit if limit < self.request_slice and limit > 0  else self.request_slice
            for off in range(offset, limit+offset, step):
                request = "{} limit {} offset {}".format(query_lower, step, off)
                response.extend(self.__send(request))

            if count:
                return response, total
            else:
                return response
        else:
            return self.__send(query_lower)[0].values()[0]
