#!/usr/bin/env python

# Created by Wazuh, Inc. <info@wazuh.com>.
# This program is a free software; you can redistribute it and/or modify it under the terms of GPLv2

from os.path import dirname, basename
from sys import argv, exit, path
from itertools import chain
import argparse
import logging
import signal

def signal_handler(signal, frame):
    print ("Interrupted")
    exit(1)
signal.signal(signal.SIGINT, signal_handler)

# Import framework
try:
    # Search path
    path.append(dirname(argv[0]) + '/../framework')

    # Import Wazuh and Initialize
    from wazuh import Wazuh
    from wazuh.exception import WazuhException

    myWazuh = Wazuh(get_init=True)

    # Import cluster
    from wazuh.cluster.cluster import read_config, check_cluster_config, get_status_json
    from wazuh.cluster.control import check_cluster_status, get_nodes, get_healthcheck, get_agents, sync, get_files

except Exception as e:
    print("Error importing 'Wazuh' package.\n\n{0}\n".format(e))
    exit()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def get_parser(type):
    if type == "master":
        class WazuhHelpFormatter(argparse.ArgumentParser):
            def format_help(self):
                msg = """Wazuh cluster control - Master node

Syntax: {0} --help | --health [more] [-fn Node1 NodeN] [--debug] | --list-agents [-fs Status] [-fn Node1 NodeN] [--debug] | --list-nodes [-fn Node1 NodeN] [--debug]

Usage:
\t-h, --help                                  # Show this help message
\t-i, --health [more]                         # Show cluster health
\t-a, --list-agents                           # List agents
\t-l, --list-nodes                            # List nodes

Filters:
\t-fn, --filter-node                          # Filter by node
\t-fs, --filter-agent-status                  # Filter by agent status (Active, Disconnected, NeverConnected, Pending)

Others:
\t-d, --debug                                # Show debug information

""".format(basename(argv[0]))
                #\t-s, --sync                                 # Force the nodes to initiate the synchronization process
                #\t-l, --list-files                           # List the file status for every node
                #\t-f, --filter-file                          # Filter by file
                return msg
            def error(self, message):
                print("Wrong arguments: {0}".format(message))
                self.print_help()
                exit(1)

        parser=WazuhHelpFormatter(usage='custom usage')
        parser._positionals.title = 'Wazuh Cluster control interface'

        parser.add_argument('-fn', '--filter-node', dest='filter_node', nargs='*', type=str, help="Node")
        #parser.add_argument('-f', '--filter-file', dest='filter_file', nargs='*', type=str, help="File")
        parser.add_argument('-fs', '--filter-agent-status', dest='filter_status', action = 'store', type=str, help="Agents status")
        parser.add_argument('-d', '--debug', action='store_const', const='debug', help="Enable debug mode")

        exclusive = parser.add_mutually_exclusive_group()
        #exclusive.add_argument('-s', '--sync', const='sync', action='store_const', help="Force the nodes to initiate the synchronization process")
        #exclusive.add_argument('-l', '--list-files', const='list_files', action='store_const', help="List the file status for every node")
        exclusive.add_argument('-a', '--list-agents', const='list_agents', action='store_const', help="List agents")
        exclusive.add_argument('-l', '--list-nodes', const='list_nodes', action='store_const', help="List nodes")
        exclusive.add_argument('-i', '--health', const='health', action='store', nargs='?', help="Show cluster health")

        return parser
    else:
        class WazuhHelpFormatter(argparse.ArgumentParser):
            def format_help(self):
                msg = """Wazuh cluster control - Client node

Syntax: {0} --help | --health [more] [-fn Node1 NodeN] [--debug] | --list-nodes [-fn Node1 NodeN] [--debug]

Usage:
\t-h, --help                                  # Show this help message
\t-i, --health [more]                         # Show cluster health
\t-l, --list-nodes                            # List nodes

Filters:
\t-fn, --filter-node                          # Filter by node

Others:
\t-d, --debug                                # Show debug information

""".format(basename(argv[0]))
                #\t-l, --list-files                            # List the status of his own files
                #\t -f, --filter-file                          # Filter by file
                return msg
            def error(self, message):
                print("Wrong arguments: {0}".format(message))
                self.print_help()
                exit(1)

        parser=WazuhHelpFormatter(usage='custom usage')
        parser._positionals.title = 'Wazuh Cluster control interface'

        parser.add_argument('-fn', '--filter-node', dest='filter_node', nargs='*', type=str, help="Node")
        #parser.add_argument('-f', '--filter-file', dest='filter_file', nargs='*', type=str, help="File")
        parser.add_argument('-fs', '--filter-agent-status', dest='filter_status', action = 'store', type=str, help="Agents status")
        parser.add_argument('-d', '--debug', action='store_const', const='debug', help="Enable debug mode")

        exclusive = parser.add_mutually_exclusive_group()
        #exclusive.add_argument('-l', '--list-files', const='list_files', action='store_const', help="List the file status for every node")
        exclusive.add_argument('-a', '--list-agents', const='list_agents', action='store_const', help="List agents")
        exclusive.add_argument('-l', '--list-nodes', const='list_nodes', action='store_const', help="List nodes")
        exclusive.add_argument('-i', '--health', const='health', action='store', nargs='?', help="Show cluster health")
        return parser




def __execute(my_function, my_args=()):
    response = {}
    try:
        response = my_function(*my_args)
        if response.get("err"):
            print("Error: {}".format(response['err']))
            exit(1)
    except Exception as e:
        if response:
            print ("Error: {}".format(response))
        else:
            print ("{}".format(e))
        exit(1)

    return response

#
# Format
#

def __print_table(data, headers, show_header=False):
    """
    Pretty print list of lists
    """
    def get_max_size_cols(l):
        """
        For each column of the table, return the size of the biggest element
        """
        return list(map(lambda x: max(map(lambda y: len(y)+2, x)), map(list, zip(*l))))

    if show_header:
        table = list(chain.from_iterable([[headers], data]))
    else:
        table = data

    sizes = get_max_size_cols(table)

    header_str = "{0}\n".format("-"*(sum(sizes)-2))
    table_str = header_str
    for row in table:
        for col, max_size in zip(row, sizes):
            table_str += "{0}{1}".format(col, " "*(max_size-len(col)))
        table_str += "\n"
        if show_header and row[0] == headers[0]:
            table_str += header_str
    table_str += header_str

    print (table_str)

#
# Get
#

### Get files
def print_file_status_master(filter_file_list, filter_node_list):
    files = __execute(my_function=get_files, my_args=(filter_file_list, filter_node_list,))
    headers = ["Node", "File name", "Modification time", "MD5"]

    node_error = {}

    data = []
    # Convert JSON data to table format
    for node_name in sorted(files.keys()):

        if not files[node_name]:
            continue
        if not isinstance(files[node_name], dict):
            node_error[node_name] = files[node_name]
            continue

        for file_name in sorted(files[node_name].keys()):
            my_file = [node_name, file_name, files[node_name][file_name]['mod_time'].split('.', 1)[0], files[node_name][file_name]['md5']]
            data.append(my_file)

    __print_table(data, headers, True)

    if len(node_error) > 0:
        print ("Error:")
        for node, error in node_error.items():
            print (" - {}: {}".format(node, error))


def print_file_status_client(filter_file_list, node_name):
    my_files = __execute(my_function=get_files, my_args=(filter_file_list, node_name,))
    headers = ["Node", "File name", "Modification time", "MD5"]
    data = []
    for file_name in sorted(my_files.keys()):
            my_file = [node_name, file_name, my_files[file_name]['mod_time'].split('.', 1)[0], my_files[file_name]['md5']]
            data.append(my_file)

    __print_table(data, headers, True)
    print ("(*) Clients only show their own files.")


### Get nodes
def print_nodes_status(filter_node=None):
    response = __execute(my_function=get_nodes, my_args=(filter_node,))

    nodes = response["items"]
    headers = ["Name", "Address", "Type", "Version"]
    data = [[nodes[node_name]['name'], nodes[node_name]['ip'], nodes[node_name]['type'], nodes[node_name]['version']] for node_name in sorted(nodes.keys())]
    __print_table(data, headers, True)

    if len(response["node_error"]):
        print ("The following nodes could not be found: {}.".format(' ,'.join(response["node_error"])))


### Sync
def sync_master(filter_node):
    node_response = __execute(my_function=sync, my_args=(filter_node,))
    headers = ["Node", "Response"]
    data = [[node, response] for node, response in node_response.items()]
    __print_table(data, headers, True)


### Get agents
def print_agents(filter_status=None, filter_node=None):
    agents = __execute(my_function=get_agents, my_args=(filter_status, filter_node,))
    data = [[agent['id'], agent['ip'], agent['name'], agent['status'],agent['node_name']] for agent in agents['items']]
    headers = ["ID", "Address", "Name", "Status", "Node"]
    __print_table(data, headers, True)
    if filter_status:
        print ("Found {} agent(s) with status '{}'.".format(len(agents['items']), "".join(filter_status)))
    else:
        print ("Listing {} agent(s).".format(len(agents['items'])))

### Get healthchech
def print_healthcheck(conf, more=False, filter_node=None):
    node_response = __execute(my_function=get_healthcheck, my_args=(filter_node,))

    msg1 = ""
    msg2 = ""

    msg1 += "Cluster name: {}\n\n".format(conf['name'])

    if not more:
        msg1 += "Last completed synchronization for connected nodes ({}):\n".format(node_response["n_connected_nodes"])
    else:
        msg1 += "Connected nodes ({}):".format(node_response["n_connected_nodes"])

    for node, node_info in sorted(node_response["nodes"].items()):

        msg2 += "\n    {} ({})\n".format(node, node_info['info']['ip'])
        msg2 += "        Version: {}\n".format(node_info['info']['version'])
        msg2 += "        Type: {}\n".format(node_info['info']['type'])
        msg2 += "        Active agents: {}\n".format(node_info['info']['n_active_agents'])

        if node_info['info']['type'] != "master":

            if not more:
                msg1 += "    {} ({}): Integrity: {} | Agents-info: {} | Agent-groups: {}.\n".format(node, node_info['info']['ip'], node_info['status']['last_sync_integrity']['date_end_master'], node_info['status']['last_sync_agentinfo']['date_end_master'], node_info['status']['last_sync_agentgroups']['date_end_master']
                    )

            msg2 += "        Status:\n"

            # Integrity
            msg2 += "            Integrity\n"
            msg2 += "                Last synchronization: {0} - {1}.\n".format(node_info['status']['last_sync_integrity']['date_start_master'], node_info['status']['last_sync_integrity']['date_end_master'])


            n_shared = str(node_info['status']['last_sync_integrity']['total_files']["shared"])
            n_missing = str(node_info['status']['last_sync_integrity']['total_files']["missing"])
            n_extra = str(node_info['status']['last_sync_integrity']['total_files']["extra"])
            n_extra_valid = str(node_info['status']['last_sync_integrity']['total_files']["extra_valid"])

            msg2 += "                Synchronized files: Shared: {} | Missing: {} | Extra: {} | Extra valid: {}.\n".format(n_shared, n_missing, n_extra, n_extra_valid)
            msg2 += "                Permission to synchronize: {}.\n".format(str(node_info['status']['sync_integrity_free']))

            # Agent info
            msg2 += "            Agents-info\n"
            msg2 += "                Last synchronization: {0} - {1}.\n".format(node_info['status']['last_sync_agentinfo']['date_start_master'], node_info['status']['last_sync_agentinfo']['date_end_master'])
            msg2 += "                Synchronized files: {}.\n".format(str(node_info['status']['last_sync_agentinfo']['total_agentinfo']))
            msg2 += "                Permission to synchronize: {}.\n".format(str(node_info['status']['sync_agentinfo_free']))

            # Agent groups
            msg2 += "            Agents-group\n"
            msg2 += "                Last synchronization: {0} - {1}.\n".format(node_info['status']['last_sync_agentgroups']['date_start_master'], node_info['status']['last_sync_agentgroups']['date_end_master'])
            msg2 += "                Synchronized files: {}.\n".format(str(node_info['status']['last_sync_agentgroups']['total_agentgroups']))
            msg2 += "                Permission to synchronize: {}.\n".format(str(node_info['status']['sync_extravalid_free']))


    print(msg1)

    if more:
        print(msg2)

#
# Main
#
if __name__ == '__main__':

    # Validate cluster config
    cluster_config = None
    try:
        cluster_config = read_config()
        if 'node_type' not in cluster_config or (cluster_config['node_type'] != 'master' and cluster_config['node_type'] != 'client'):
            raise WazuhException(3004, 'Invalid node type {0}. Correct values are master and client'.format(cluster_config['node_type']))
    except WazuhException as e:
        print( "Invalid configuration: '{0}'".format(str(e)))
        exit(1)

    # Get cluster config
    is_master = cluster_config['node_type'] == "master"
    # get arguments
    parser = get_parser(cluster_config['node_type'])
    args = parser.parse_args()

    if args.debug:
        logging.getLogger('').setLevel(logging.DEBUG) #10

    try:
        if args.filter_status and not args.list_agents:
            print ("Wrong arguments.")
            parser.print_help()
        elif args.list_agents:
            if is_master:
                print_agents(args.filter_status, args.filter_node)
            else:
                print ("Wrong arguments. To use this command you need to be a master node.")
                parser.print_help()

        elif args.list_nodes:
            print_nodes_status(args.filter_node)
        elif args.health:
            more = False
            if args.health.lower() == 'more':
                more = True
            print_healthcheck(conf=cluster_config, more=more, filter_node=args.filter_node)
        else:
            parser.print_help()
            exit()

        #elif args.list_files is not None:
        #    print_file_status_master(args.filter_file, args.filter_node) if is_master else print_file_status_client(args.filter_file, cluster_config['node_name'])
        #elif is_master and args.sync is not None:
        #    sync_master(args.filter_node)
        #elif args.list_files is not None:
        #    print_file_status_master(args.filter_file, args.filter_node) if is_master else print_file_status_client(args.filter_file, cluster_config['node_name'])

    except Exception as e:
        logging.error(str(e))
        if args.debug:
            raise
        exit(1)
