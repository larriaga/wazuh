#!/usr/bin/env python

# Created by Wazuh, Inc. <info@wazuh.com>.
# This program is a free software; you can redistribute it and/or modify it under the terms of GPLv2

import ast
import fcntl
import fnmatch
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from operator import itemgetter

from wazuh import common, WazuhException
from wazuh.agent import Agent
from wazuh.cluster import __version__
from wazuh.cluster.cluster import get_cluster_items, _update_file, \
    decompress_files, get_files_status, \
    compress_files, compare_files, get_agents_status, \
    read_config, unmerge_agent_info, merge_agent_info, get_cluster_items_master_intervals
from wazuh.cluster.communication import ProcessFiles, Server, ServerHandler, \
    InternalSocketHandler, ClusterThread
from wazuh.utils import mkdir_with_mode


logger = logging.getLogger(__name__)

#
# Master Handler
# There is a MasterManagerHandler for each connected client
#
class MasterManagerHandler(ServerHandler):

    def __init__(self, sock, server, asyncore_map, addr=None):
        ServerHandler.__init__(self, sock, server, asyncore_map, addr)
        self.manager = server

    # Overridden methods
    def process_request(self, command, data):
        logger.debug("[Master] [{0}] [Request-R]: '{1}'.".format(self.name, command))


        if command == 'echo-c':  # Echo
            return 'ok-c ', data.decode()
        elif command == 'sync_i_c_m_p':
            result = self.manager.get_client_status(client_id=self.name, key='sync_integrity_free')
            return 'ack', str(result)
        elif command == 'sync_ai_c_mp':
            return 'ack', str(self.manager.get_client_status(client_id=self.name, key='sync_agentinfo_free'))
        elif command == 'sync_ev_c_mp':
            return 'ack', str(self.manager.get_client_status(client_id=self.name, key='sync_extravalid_free'))
        elif command == 'sync_i_c_m':  # Client syncs integrity
            data = data.decode()
            pci_thread = ProcessClientIntegrity(manager=self.manager, manager_handler=self, filename=data, stopper=self.stopper)
            pci_thread.start()
            # data will contain the filename
            return 'ack', self.set_worker(command, pci_thread, data)
        elif command == 'sync_ai_c_m':
            data = data.decode()
            mcf_thread = ProcessClientFiles(manager_handler=self, filename=data, stopper=self.stopper)
            mcf_thread.start()
            # data will contain the filename
            return 'ack', self.set_worker(command, mcf_thread, data)
        elif command == 'sync_ev_c_m':
            data = data.decode()
            mcf_thread = ProcessExtraValidFiles(manager_handler=self, filename=data, stopper=self.stopper)
            mcf_thread.start()
            return 'ack', self.set_worker(command, mcf_thread, data)
        elif command == 'get_nodes':
            data = data.decode()
            response = {name:data['info'] for name,data in self.server.get_connected_clients().items()}
            cluster_config = read_config()
            response.update({cluster_config['node_name']:{"name": cluster_config['node_name'], "ip": cluster_config['nodes'][0],  "type": "master",  "version": __version__}})
            serialized_response = ['ok', json.dumps(response)]
            return serialized_response
        elif command == 'get_health':
            filter_nodes = data.decode()
            response = self.manager.get_healthcheck(filter_nodes)
            serialized_response = ['ok', json.dumps(response)]
            return serialized_response
        elif command == 'get_agents':
            data = data.decode()
            split_data = data.split('%--%', 5)
            filter_status = split_data[0] if split_data[0] != 'None' else None
            filter_nodes = split_data[1] if split_data[1] != 'None' else None
            offset = split_data[2] if split_data[2] != 'None' else None
            limit = split_data[3] if split_data[3] != 'None' else None
            sort = split_data[4] if split_data[4] != 'None' else None
            search = split_data[5] if split_data[5] != 'None' else None
            response = get_agents_status(filter_status, filter_nodes, offset, limit, sort, search)
            serialized_response = ['ok', json.dumps(response)]
            return serialized_response
        else:  # Non-master requests
            return ServerHandler.process_request(self, command, data)


    def process_response(self, response):
        # FixMe: Move this line to communications
        answer, payload = self.split_data(response)

        logger.debug("[Master] [{0}] [Response-R]: '{1}'.".format(self.name, answer))

        if answer == 'ok-m':  # test
            response_data = '[response_only_for_master] Client answered: {}.'.format(payload)
        else:
            response_data = ServerHandler.process_response(self, response)

        return response_data


    # Private methods
    def _update_client_files_in_master(self, json_file, zip_dir_path, client_name, cluster_control_key, cluster_control_subkey, tag):
        def update_file(n_errors, name, data, file_time=None, content=None, agents=None):
            # Full path
            full_path = common.ossec_path + name
            error_updating_file = False

            # Cluster items information: write mode and umask
            w_mode = cluster_items[data['cluster_item_key']]['write_mode']
            umask = cluster_items[data['cluster_item_key']]['umask']

            if content is None:
                zip_path = "{}/{}".format(zip_dir_path, name)
                with open(zip_path, 'rb') as f:
                    content = f.read()

            lock_full_path = "{}/queue/cluster/lockdir/{}.lock".format(common.ossec_path, os.path.basename(full_path))
            lock_file = open(lock_full_path, 'a+')
            try:
                fcntl.lockf(lock_file, fcntl.LOCK_EX)
                _update_file(file_path=name, new_content=content,
                             umask_int=umask, mtime=file_time, w_mode=w_mode,
                             tmp_dir=tmp_path, whoami='master', agents=agents)

            except WazuhException as e:
                logger.debug2("{}: Warning updating file '{}': {}".format(tag, name, e))
                error_tag = 'warnings'
                error_updating_file = True
            except Exception as e:
                logger.debug2("{}: Error updating file '{}': {}".format(tag, name, e))
                error_tag = 'errors'
                error_updating_file = True

            if error_updating_file:
                n_errors[error_tag][data['cluster_item_key']] = 1 if not n_errors[error_tag].get(data['cluster_item_key']) \
                                                                  else n_errors[error_tag][data['cluster_item_key']] + 1

            fcntl.lockf(lock_file, fcntl.LOCK_UN)
            lock_file.close()

            return n_errors, error_updating_file


        # tmp path
        tmp_path = "/queue/cluster/{}/tmp_files".format(client_name)
        cluster_items = get_cluster_items()['files']
        n_merged_files = 0
        n_errors = {'errors': {}, 'warnings': {}}

        # create temporary directory for lock files
        lock_directory = "{}/queue/cluster/lockdir".format(common.ossec_path)
        if not os.path.exists(lock_directory):
            mkdir_with_mode(lock_directory)

        try:
            agents = Agent.get_agents_overview(select={'fields':['name']}, limit=None)['items']
            agent_names = set(map(itemgetter('name'), agents))
            agent_ids = set(map(itemgetter('id'), agents))
        except Exception as e:
            logger.debug2("{}: Error getting agent ids and names: {}".format(tag, e))
            agent_names, agent_ids = {}, {}

        before = time.time()
        try:
            for filename, data in json_file.items():
                if data['merged']:
                    for file_path, file_data, file_time in unmerge_agent_info(data['merge_type'], zip_dir_path, data['merge_name']):
                        n_errors, error_updating_file = update_file(n_errors, file_path, data, file_time, file_data, (agent_names, agent_ids))
                        if not error_updating_file:
                            n_merged_files += 1

                        if self.stopper.is_set():
                            break
                else:
                    n_errors, _ = update_file(n_errors, filename, data)

        except Exception as e:
            logger.error("{}: Error updating client files: '{}'.".format(tag, e))
            raise e

        after = time.time()
        logger.debug("{0}: Time updating client files: {1:.2f}s. Total of updated client files: {2}.".format(tag, after - before, n_merged_files))

        if sum(n_errors['errors'].values()) > 0:
            logging.error("{}: Errors updating client files: {}".format(tag,
                ' | '.join(['{}: {}'.format(key, value) for key, value in n_errors['errors'].items()])
            ))
        if sum(n_errors['warnings'].values()) > 0:
            for key, value in n_errors['warnings'].items():
                if key == '/queue/agent-info/':
                    logger.warning("Received {} agent statuses for non-existent agents. Skipping.".format(value))
                elif key == '/queue/agent-groups/':
                    logger.warning("Received {} group assignments for non-existent agents. Skipping.".format(value))

        # Save info for healthcheck
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey=cluster_control_subkey, status=n_merged_files)


    # New methods
    def process_files_from_client(self, client_name, data_received, cluster_control_key, cluster_control_subkey, tag=None):
        sync_result = False

        # Save info for healthcheck
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey="date_start_master", status=datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-4])
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey="date_end_master", status="In progress")
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey=cluster_control_subkey, status="In progress")
        # ---

        if not tag:
            tag = "[Master] [process_files_from_client]"

        # Extract received data
        logger.info("{0}: Analyzing received files: Start.".format(tag))

        try:
            json_file, zip_dir_path = decompress_files(data_received)
        except Exception as e:
            logger.error("{0}: Error decompressing data: {1}.".format(tag, str(e)))
            raise e

        if json_file:
            client_files_json = json_file['client_files']
        else:
            raise Exception("cluster_control.json not included in received zip file")

        logger.info("{0}: Analyzing received files: End.".format(tag))

        logger.info("{0}: Updating master files: Start.".format(tag))

        # Update files
        self._update_client_files_in_master(client_files_json, zip_dir_path, client_name,
                                            cluster_control_key, cluster_control_subkey,
                                            tag)

        # Remove tmp directory created when zip file was received
        shutil.rmtree(zip_dir_path)

        logger.info("{0}: Updating master files: End.".format(tag))

        sync_result = True

        # Save info for healthcheck
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey="date_end_master", status=datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-4])

        return sync_result


    def process_integrity_from_client(self, client_name, data_received, cluster_control_key, cluster_control_subkey, tag=None):
        if not tag:
            tag = "[Master] [process_integrity_from_client]"

        # Extract received data
        logger.info("{0}: Analyzing client integrity: Start.".format(tag))

        try:
            json_file, zip_dir_path = decompress_files(data_received)
        except Exception as e:
            logger.error("{0}: Error decompressing data: {1}".format(tag, str(e)))
            raise e

        if json_file:
            master_files_from_client = json_file['master_files']
        else:
            raise Exception("cluster_control.json not included in received zip file")

        logger.info("{0}: Analyzing client integrity: Received {1} files to check.".format(tag, len(master_files_from_client)))

        logger.info("{0}: Analyzing client integrity: Checking files.".format(tag, len(master_files_from_client)))

        # Get master files
        master_files = self.server.get_integrity_control()

        # Compare
        client_files_ko = compare_files(master_files, master_files_from_client)

        agent_groups_to_merge = {key:fnmatch.filter(values.keys(), '*/agent-groups/*')
                                 for key,values in client_files_ko.items()}
        merged_files = {key:merge_agent_info(merge_type="agent-groups", files=values,
                                         file_type="-"+key, time_limit_seconds=0)
                        for key,values in agent_groups_to_merge.items()}

        for ko, merged in zip(client_files_ko.items(), agent_groups_to_merge.items()):
            ko_type, ko_files = ko
            if ko_type == "extra" or "extra_valid":
                continue
            _, merged_filenames = merged
            for m in merged_filenames:
                del ko_files[m]
            n_files, merged_file = merged_files[ko_type]
            if n_files > 0:
                ko_files[merged_file] = {'cluster_item_key': '/queue/agent-groups/', 'merged': True}

        # Save info for healthcheck
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey=cluster_control_subkey, subsubkey="missing", status=len(client_files_ko['missing']))
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey=cluster_control_subkey, subsubkey="shared", status=len(client_files_ko['shared']))
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey=cluster_control_subkey, subsubkey="extra", status=len(client_files_ko['extra']))
        self.manager.set_client_status(client_id=self.name, key=cluster_control_key, subkey=cluster_control_subkey, subsubkey="extra_valid", status=len(client_files_ko['extra_valid']))
        # ---

        # Remove tmp directory created when zip file was received
        shutil.rmtree(zip_dir_path)

        # Step 3: KO files
        if len(list(filter(lambda x: x == {}, client_files_ko.values()))) == len(client_files_ko):
            logger.info("{0}: Analyzing client integrity: Files checked. There are no KO files.".format(tag))

            ko_files = False
            data_for_client = None

        else:
            logger.info("{0}: Analyzing client integrity: Files checked. There are KO files.".format(tag))

            # Compress data: master files (only KO shared and missing)
            logger.debug("{0} Analyzing client integrity: Files checked. Compressing KO files.".format(tag))

            master_files_paths = [item for item in client_files_ko['shared']]
            master_files_paths.extend([item for item in client_files_ko['missing']])

            compressed_data = compress_files(client_name, master_files_paths, client_files_ko)

            logger.debug("{0} Analyzing client integrity: Files checked. KO files compressed.".format(tag))

            ko_files = True
            data_for_client = compressed_data

        logger.info("{0}: Analyzing client integrity: End.".format(tag))

        return ko_files, data_for_client


#
# Threads (workers) created by MasterManagerHandler
#


class ProcessClient(ProcessFiles):

    def __init__(self, manager_handler, filename, stopper):
        ProcessFiles.__init__(self, manager_handler, filename,
                              manager_handler.get_client(),
                              stopper)

    def check_connection(self):
        return True


    def lock_status(self, status):
        # status_type is used to indicate whether a lock is free or not.
        # if the lock is True, the status should be False because it is not free
        self.manager_handler.manager.set_client_status(self.name, self.status_type, not status)


    def process_file(self):
        return self.function(self.name, self.filename, self.cluster_control_key, self.cluster_control_subkey, self.thread_tag)


    def unlock_and_stop(self, reason, send_err_request=None):
        logger.info("{0}: Unlocking '{1}' due to {2}.".format(self.thread_tag, self.status_type, reason))
        ProcessFiles.unlock_and_stop(self, reason, send_err_request)


class ProcessClientIntegrity(ProcessClient):

    def __init__(self, manager, manager_handler, filename, stopper):
        ProcessClient.__init__(self, manager_handler, filename, stopper)
        self.manager = manager
        self.thread_tag = "[Master] [{0}] [Integrity-R  ]".format(self.manager_handler.name)
        self.status_type = "sync_integrity_free"
        self.function = self.manager_handler.process_integrity_from_client
        self.cluster_control_key = "last_sync_integrity"
        self.cluster_control_subkey = "total_files"

    # Overridden methods
    def process_file(self):
        # Save info for healthcheck
        self.manager.set_client_status(client_id=self.name, key=self.cluster_control_key, subkey="date_start_master", status=datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-4])
        self.manager.set_client_status(client_id=self.name, key=self.cluster_control_key, subkey="date_end_master", status="In progress")
        self.manager.set_client_status(client_id=self.name, key=self.cluster_control_key, subkey=self.cluster_control_subkey, subsubkey="missing", status="In progress")
        self.manager.set_client_status(client_id=self.name, key=self.cluster_control_key, subkey=self.cluster_control_subkey, subsubkey="shared", status="In progress")
        self.manager.set_client_status(client_id=self.name, key=self.cluster_control_key, subkey=self.cluster_control_subkey, subsubkey="extra", status="In progress")
        self.manager.set_client_status(client_id=self.name, key=self.cluster_control_key, subkey=self.cluster_control_subkey, subsubkey="extra_valid", status="In progress")
        # ---

        sync_result = False

        ko_files, data_for_client = self.function(self.name, self.filename, self.cluster_control_key, self.cluster_control_subkey, self.thread_tag)

        if ko_files:
            logger.info("{0}: Sending Sync-KO to client.".format(self.thread_tag))
            response = self.manager.send_file(self.name, 'sync_m_c', data_for_client, True)
        else:
            logger.info("{0}: Sending Synk-OK to client.".format(self.thread_tag))
            response = self.manager.send_request(self.name, 'sync_m_c_ok')

        processed_response = self.manager_handler.process_response(response)

        if processed_response:
            sync_result = True
            logger.info("{0}: Sync accepted by the client.".format(self.thread_tag))
        else:
            logger.error("{0}: Sync error reported by the client.".format(self.thread_tag))

        # Save info for healthcheck
        self.manager.set_client_status(client_id=self.name, key=self.cluster_control_key, subkey="date_end_master", status=datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-4])

        return sync_result


    def unlock_and_stop(self, reason, send_err_request=True):

        # Send Err
        if send_err_request:
            logger.info("{0}: Sending Sync-Error to client.".format(self.thread_tag))
            response = self.manager.send_request(self.name, 'sync_m_c_err')

            processed_response = self.manager_handler.process_response(response)

            if processed_response:
                logger.info("{0}: Sync accepted by the client.".format(self.thread_tag))
            else:
                logger.error("{0}: Sync error reported by the client.".format(self.thread_tag))

        # Unlock and stop
        ProcessClient.unlock_and_stop(self, reason)


class ProcessClientFiles(ProcessClient):

   def __init__(self, manager_handler, filename, stopper):
        ProcessClient.__init__(self, manager_handler, filename, stopper)
        self.thread_tag = "[Master] [{0}] [AgentInfo-R  ]".format(self.manager_handler.name)
        self.status_type = "sync_agentinfo_free"
        self.function = self.manager_handler.process_files_from_client
        self.cluster_control_key = "last_sync_agentinfo"
        self.cluster_control_subkey = "total_agentinfo"


class ProcessExtraValidFiles(ProcessClient):

    def __init__(self, manager_handler, filename, stopper):
        ProcessClient.__init__(self, manager_handler, filename, stopper)
        self.thread_tag = "[Master] [{0}] [AgentGroup-R ]".format(self.manager_handler.name)
        self.status_type = "sync_extravalid_free"
        self.function = self.manager_handler.process_files_from_client
        self.cluster_control_key = "last_sync_agentgroups"
        self.cluster_control_subkey = "total_agentgroups"


#
# Master
#
class MasterManager(Server):
    Integrity_T = "Integrity_Thread"

    def __init__(self, cluster_config):
        Server.__init__(self, cluster_config['bind_addr'], cluster_config['port'], MasterManagerHandler)

        logger.info("[Master] Listening '{0}:{1}'.".format(cluster_config['bind_addr'], cluster_config['port']))

        # Intervals
        self.interval_recalculate_integrity = get_cluster_items_master_intervals()['recalculate_integrity']

        self.config = cluster_config
        self.handler = MasterManagerHandler
        self._integrity_control = {}
        self._integrity_control_lock = threading.Lock()

        # Threads
        self.stopper = threading.Event()  # Event to stop threads
        self.threads = {}
        self._initiate_master_threads()


    # Overridden methods
    def add_client(self, data, ip, handler):
        client_id = Server.add_client(self, data, ip, handler)
        # create directory in /queue/cluster to store all node's file there
        node_path = "{}/queue/cluster/{}".format(common.ossec_path, client_id)
        if not os.path.exists(node_path):
            mkdir_with_mode(node_path)
        return client_id


    # Private methods
    def _initiate_master_threads(self):
        logger.debug("[Master] Creating threads.")

        self.threads[MasterManager.Integrity_T] = FileStatusUpdateThread(master=self, interval=self.interval_recalculate_integrity, stopper=self.stopper)
        self.threads[MasterManager.Integrity_T].start()

        logger.debug("[Master] Threads created.")

    # New methods
    def set_client_status(self, client_id, key, status, subkey=None, subsubkey=None):
        result = False
        with self._clients_lock:
            if client_id in self._clients:
                if subsubkey:
                    self._clients[client_id]['status'][key][subkey][subsubkey] = status
                elif subkey:
                    self._clients[client_id]['status'][key][subkey] = status
                else:
                    self._clients[client_id]['status'][key] = status
                result = True

        return result


    def get_client_status(self, client_id, key):
        result = False

        with self._clients_lock:
            if client_id in self._clients:
                result = self._clients[client_id]['status'][key]

        return result


    def req_file_status_to_clients(self):
        responses = list(self.send_request_broadcast(command = 'file_status'))
        nodes_file = {node:json.loads(data.split(' ',1)[1]) for node,data in responses}
        return 'ok', json.dumps(nodes_file)


    def get_integrity_control(self):
        with self._integrity_control_lock:
            if len(self._integrity_control) == 0:
                raise Exception("Integrity not calculated yet")
            return self._integrity_control


    def set_integrity_control(self, new_integrity_control):
        with self._integrity_control_lock:
            self._integrity_control = new_integrity_control


    def get_healthcheck(self, filter_nodes=None):
        clients_info = {name:{"info":dict(data['info']), "status":data['status']} for name,data in self.get_connected_clients().items() if not filter_nodes or name in filter_nodes}
        n_connected_nodes = len(self.get_connected_clients().items()) + 1 # clients + master

        cluster_config = read_config()
        if  not filter_nodes or cluster_config['node_name'] in filter_nodes:
            clients_info.update({cluster_config['node_name']:{"info":{"name": cluster_config['node_name'],
                                                                  "ip": cluster_config['nodes'][0], "version": __version__,
                                                                  "type": "master"}}})

        # Get active agents by node
        for node_name in clients_info.keys():
            clients_info[node_name]["info"]["n_active_agents"]=Agent.get_agents_overview(status='Active', node_name=node_name)['totalItems']

        health_info = {"n_connected_nodes":n_connected_nodes, "nodes": clients_info}
        return health_info


    def exit(self):
        logger.debug("[Master] Cleaning threads. Start.")

        # Cleaning master threads
        self.stopper.set()

        for thread in self.threads:
            logger.debug2("[Master] Cleaning threads '{0}'.".format(thread))

            try:
                self.threads[thread].join(timeout=2)
            except Exception as e:
                logger.error("[Master] Cleaning '{0}' thread. Error: '{1}'.".format(thread, str(e)))

            if self.threads[thread].isAlive():
                logger.warning("[Master] Cleaning '{0}' thread. Timeout.".format(thread))
            else:
                logger.debug2("[Master] Cleaning '{0}' thread. Terminated.".format(thread))

        # Cleaning handler threads
        logger.debug("[Master] Cleaning threads generated to handle clients.")
        clients = self.get_connected_clients().copy().keys()
        for client in clients:
            self.remove_client(client_id=client)

        logger.debug("[Master] Cleaning threads. End.")


#
# Master threads
#
class FileStatusUpdateThread(ClusterThread):
    def __init__(self, master, interval, stopper):
        ClusterThread.__init__(self, stopper)
        self.master = master
        self.interval = interval


    def run(self):
        while not self.stopper.is_set() and self.running:
            logger.debug("[Master] [IntegrityControl] Calculating.")
            try:
                tmp_integrity_control = get_files_status('master')
                self.master.set_integrity_control(tmp_integrity_control)
            except Exception as e:
                logger.error("[Master] [IntegrityControl] Error: {}".format(str(e)))

            logger.debug("[Master] [IntegrityControl] Calculated.")

            self.sleep(self.interval)


#
# Internal socket
#
class MasterInternalSocketHandler(InternalSocketHandler):
    def __init__(self, sock, manager, asyncore_map):
        InternalSocketHandler.__init__(self, sock=sock, manager=manager, asyncore_map=asyncore_map)

    def process_request(self, command, data):
        logger.debug("[Transport-I] Forwarding request to master of cluster '{0}' - '{1}'".format(command, data))
        serialized_response = ""
        data = data.decode()

        if command == 'get_files':
            split_data = data.split('%--%', 2)
            node_list = ast.literal_eval(split_data[1]) if split_data[1] else None
            get_my_files = False

            response = {}

            if node_list and len(node_list) > 0: #Selected nodes
                for node in node_list:
                    if node == read_config()['node_name']:
                        get_my_files = True
                        continue
                    node_file = self.manager.send_request(client_name=node, command='file_status', data='')

                    if node_file.split(' ', 1)[0] == 'err': # Error response
                        response.update({node:node_file.split(' ', 1)[1]})
                    else:
                        response.update({node:json.loads(node_file.split(' ',1)[1])})
            else: # Broadcast
                get_my_files = True

                node_file = list(self.manager.send_request_broadcast(command = 'file_status'))

                for node,data in node_file:
                    try:
                        response.update({node:json.loads(data.split(' ',1)[1])})
                    except ValueError: # json.loads will raise a ValueError
                        response.update({node:data.split(' ',1)[1]})

            if get_my_files:
                my_files = get_files_status('master', get_md5=True)
                my_files.update(get_files_status('client', get_md5=True))
                response.update({read_config()['node_name']:my_files})

            # Filter files
            if node_list and len(response):
                response = {node: response.get(node) for node in node_list}

            serialized_response = ['ok',  json.dumps(response)]
            return serialized_response

        elif command == 'get_nodes':
            response = {name:data['info'] for name,data in self.manager.get_connected_clients().items()}
            cluster_config = read_config()
            response.update({cluster_config['node_name']:{"name": cluster_config['node_name'], "ip": cluster_config['nodes'][0],  "type": "master", "version":__version__}})

            serialized_response = ['ok', json.dumps(response)]
            return serialized_response

        elif command == 'get_agents':
            split_data = data.split('%--%', 5)
            filter_status = split_data[0] if split_data[0] != 'None' else None
            filter_nodes = split_data[1] if split_data[1] != 'None' else None
            offset = split_data[2] if split_data[2] != 'None' else None
            limit = split_data[3] if split_data[3] != 'None' else None
            sort = split_data[4] if split_data[4] != 'None' else None
            search = split_data[5] if split_data[5] != 'None' else None
            response = get_agents_status(filter_status, filter_nodes, offset, limit, sort, search)
            serialized_response = ['ok',  json.dumps(response)]
            return serialized_response

        elif command == 'get_health':
            node_list = data if data != 'None' else None
            response = self.manager.get_healthcheck(node_list)
            serialized_response = ['ok',  json.dumps(response)]
            return serialized_response

        elif command == 'sync':
            command = "req_sync_m_c"
            split_data = data.split(' ', 1)
            node_list = ast.literal_eval(split_data[0]) if split_data[0] else None

            if node_list:
                for node in node_list:
                    response = {node:self.manager.send_request(client_name=node, command=command, data="")}
                serialized_response = ['ok', json.dumps(response)]
            else:
                response = list(self.manager.send_request_broadcast(command=command, data=data))
                serialized_response = ['ok', json.dumps({node:data for node,data in response})]
            return serialized_response

        else:
            return ['err', json.dumps({'err': "Received an unknown command '{}'".format(command)})]
