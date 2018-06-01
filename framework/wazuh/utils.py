#!/usr/bin/env python

# Created by Wazuh, Inc. <info@wazuh.com>.
# This program is a free software; you can redistribute it and/or modify it under the terms of GPLv2

from wazuh.exception import WazuhException
from wazuh import common
from tempfile import mkstemp
from subprocess import call, CalledProcessError
from os import remove, chmod, chown, path, listdir, close, mkdir, curdir
from datetime import datetime, timedelta
import hashlib
import json
import stat
import re
import errno
from itertools import groupby, chain
from xml.etree.ElementTree import fromstring
from operator import itemgetter

try:
    from subprocess import check_output
except ImportError:
    def check_output(arguments, stdin=None, stderr=None, shell=False):
        temp_f = mkstemp()
        returncode = call(arguments, stdin=stdin, stdout=temp_f[0], stderr=stderr, shell=shell)
        close(temp_f[0])
        file_o = open(temp_f[1], 'r')
        cmd_output = file_o.read()
        file_o.close()
        remove(temp_f[1])

        if returncode != 0:
            error_cmd = CalledProcessError(returncode, arguments[0])
            error_cmd.output = cmd_output
            raise error_cmd
        else:
            return cmd_output


def previous_month(n=1):
    """
    Returns the first date of the previous n month.

    :param n: Number of months.
    :return: First date of the previous n month.
    """

    date = datetime.today().replace(day=1)  # First day of current month

    for i in range(0, int(n)):
        date = (date - timedelta(days=1)).replace(day=1)  # (first_day - 1) = previous month

    return date.replace(hour=00, minute=00, second=00, microsecond=00)


def execute(command):
    """
    Executes a command. It is used to execute ossec commands.

    :param command: Command as list.
    :return: If output.error !=0 returns output.data, otherwise launches a WazuhException with output.error as error code and output.message as description.
    """

    try:
        output = check_output(command)
    except CalledProcessError as error:
        output = error.output
    except Exception as e:
        raise WazuhException(1002, "{0}: {1}".format(command, e))  # Error executing command

    try:
        output_json = json.loads(output)
    except Exception as e:
        raise WazuhException(1003, command)  # Command output not in json

    keys = output_json.keys()  # error and (data or message)
    if 'error' not in keys or ('data' not in keys and 'message' not in keys):
        raise WazuhException(1004, command)  # Malformed command output

    if output_json['error'] != 0:
        raise WazuhException(output_json['error'], output_json['message'], True)
    else:
        return output_json['data']


def cut_array(array, offset, limit):
    """
    Returns a part of the array: from offset to offset + limit.
    :param array: Array to cut.
    :param offset: First element to return.
    :param limit: Maximum number of elements to return. 0 means no cut array.
    :return: cut array.
    """

    if not array or limit == 0 or limit == None:
        return array

    offset = int(offset)
    limit = int(limit)

    if offset < 0:
        raise WazuhException(1400)
    elif limit < 1:
        raise WazuhException(1401)
    else:
        return array[offset:offset + limit]


def sort_array(array, sort_by=None, order='asc', allowed_sort_fields=None):
    """
    Sorts an array.

    :param array: Array to sort.
    :param sort_by: Array of fields.
    :param order: asc or desc.
    :param allowed_sort_fields: Check sort_by with allowed_sort_fields (array).
    :return: sorted array.
    """
    def check_sort_fields(allowed_sort_fields, sort_by):
        # Check if every element in sort['fields'] is in allowed_sort_fields
        if not sort_by.issubset(allowed_sort_fields):
            uncorrect_fields = map(lambda x: str(x), sort_by - allowed_sort_fields)
            raise WazuhException(1403, 'Allowed sort fields: {0}. Fields: {1}'.format(list(allowed_sort_fields), uncorrect_fields))

    if not array:
        return array

    if order.lower() == 'desc':
        order_desc = True
    elif order.lower() == 'asc':
        order_desc = False
    else:
        raise WazuhException(1402)

    if allowed_sort_fields:
        check_sort_fields(set(allowed_sort_fields), set(sort_by))

    if sort_by:  # array should be a dictionary or a Class
        if type(array[0]) is dict:
            check_sort_fields(set(array[0].keys()), set(sort_by))

            return sorted(array, key=lambda o: tuple(o.get(a) for a in sort_by), reverse=order_desc)
        else:
            return sorted(array, key=lambda o: tuple(getattr(o, a) for a in sort_by), reverse=order_desc)
    else:
        if type(array) is set or (type(array[0]) is not dict and 'class \'wazuh' not in str(type(array[0]))):
            return sorted(array, reverse=order_desc)
        else:
            raise WazuhException(1404)


def get_values(o, fields=None):
    """
    Converts the values of an object to an array of strings.
    :param o: Object.
    :param fields: fields to get values of (only for dictionaries)
    :return: Array of strings.
    """
    strings = []

    try:
        obj = o.to_dict()  # Rule, Decoder, Agent...
    except:
        obj = o

    if type(obj) is list:
        for o in obj:
            strings.extend(get_values(o))
    elif type(obj) is dict:
        for key in obj:
            if not fields or key in fields:
                strings.extend(get_values(obj[key]))
    else:
        strings.append(str(obj).lower())

    return strings


def search_array(array, text, negation=False, fields=None):
    """
    Looks for the string 'text' in the elements of the array.

    :param array: Array.
    :param text: Text to search.
    :param negation: the text must not be in the array.
    :param fields: fields of the array to search in
    :return: True or False.
    """

    found = []

    for item in array:

        values = get_values(o=item, fields=fields)

        # print("'{0}' in '{1}'?".format(text, values))

        if not negation:
            for v in values:
                if text.lower() in v:
                    found.append(item)
                    break
        else:
            not_in_values = True
            for v in values:
                if text.lower() in v:
                    not_in_values = False
                    break
            if not_in_values:
                found.append(item)

    return found

_filemode_table = (
    ((stat.S_IFLNK, "l"),
     (stat.S_IFREG, "-"),
     (stat.S_IFBLK, "b"),
     (stat.S_IFDIR, "d"),
     (stat.S_IFCHR, "c"),
     (stat.S_IFIFO, "p")),

    ((stat.S_IRUSR, "r"),),
    ((stat.S_IWUSR, "w"),),
    ((stat.S_IXUSR | stat.S_ISUID, "s"),
     (stat.S_ISUID, "S"),
     (stat.S_IXUSR, "x")),

    ((stat.S_IRGRP, "r"),),
    ((stat.S_IWGRP, "w"),),
    ((stat.S_IXGRP | stat.S_ISGID, "s"),
     (stat.S_ISGID, "S"),
     (stat.S_IXGRP, "x")),

    ((stat.S_IROTH, "r"),),
    ((stat.S_IWOTH, "w"),),
    ((stat.S_IXOTH | stat.S_ISVTX, "t"),
     (stat.S_ISVTX, "T"),
     (stat.S_IXOTH, "x"))
)


def filemode(mode):
    """
    Convert a file's mode to a string of the form '-rwxrwxrwx'.
    :param mode: Mode.
    :return: String.
    """

    perm = []
    for table in _filemode_table:
        for bit, char in table:
            if mode & bit == bit:
                perm.append(char)
                break
        else:
            perm.append("-")
    return "".join(perm)


def tail(filename, n=20):
    """
    Returns last 'n' lines of the file 'filename'.
    :param filename: Path to the file.
    :param n: number of lines.
    :return: Array of last lines.
    """
    f = open(filename, 'rb')
    total_lines_wanted = n

    BLOCK_SIZE = 1024
    f.seek(0, 2)
    block_end_byte = f.tell()
    lines_to_go = total_lines_wanted
    block_number = -1
    blocks = [] # blocks of size BLOCK_SIZE, in reverse order starting from the end of the file
    while lines_to_go > 0 and block_end_byte > 0:
        if (block_end_byte - BLOCK_SIZE > 0):
            # read the last block we haven't yet read
            f.seek(block_number*BLOCK_SIZE, 2)
            blocks.append(f.read(BLOCK_SIZE).decode())
        else:
            # file too small, start from beginning
            f.seek(0,0)
            # only read what was not read
            blocks.append(f.read(block_end_byte).decode())
        lines_found = blocks[-1].count('\n')
        lines_to_go -= lines_found
        block_end_byte -= BLOCK_SIZE
        block_number -= 1
    all_read_text = ''.join(reversed(blocks))

    f.close()
    #return '\n'.join(all_read_text.splitlines()[-total_lines_wanted:])
    return all_read_text.splitlines()[-total_lines_wanted:]


def chmod_r(filepath, mode):
    """
    Recursive chmod.
    :param filepath: Path to the file.
    :param mode: file mode in octal.
    """

    chmod(filepath, mode)

    if path.isdir(filepath):
        for item in listdir(filepath):
            itempath = path.join(filepath, item)
            if path.isfile(itempath):
                chmod(itempath, mode)
            elif path.isdir(itempath):
                chmod_r(itempath, mode)


def chown_r(filepath, uid, gid):
    """
    Recursive chmod.
    :param filepath: Path to the file.
    :param uid: user ID.
    :param gid: group ID.
    """

    chown(filepath, uid, gid)

    if path.isdir(filepath):
        for item in listdir(filepath):
            itempath = path.join(filepath, item)
            if path.isfile(itempath):
                chown(itempath, uid, gid)
            elif path.isdir(itempath):
                chown_r(itempath, uid, gid)


def mkdir_with_mode(name, mode=0o770):
    """
    Creates a directory with specified permissions.

    :param directory: directory path
    :param mode: permissions to set to the directory
    """
    head, tail = path.split(name)
    if not tail:
        head, tail = path.split(head)
    if head and tail and not path.exists(head):
        try:
            mkdir_with_mode(head, mode)
        except OSError as e:
            # be happy if someone already created the path
            if e.errno != errno.EEXIST:
                raise
        if tail == curdir:           # xxx/newdir/. exists if xxx/newdir exists
            return
    mkdir(name, mode)
    chmod(name, mode)


def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_fields_to_nest(fields, force_fields=[]):
    nest = {k:set(filter(lambda x: x != k, chain.from_iterable(g)))
             for k,g in groupby(map(lambda x: x.split('_'), sorted(fields)),
             key=lambda x:x[0])}
    nested = filter(lambda x: len(x[1]) > 1 or x[0] in force_fields, nest.items())
    nested = [(field,{(subfield, '_'.join([field,subfield])) for subfield in subfields}) for field, subfields in nested]
    non_nested = set(filter(lambda x: x.split('_')[0] not in map(itemgetter(0), nested), fields))
    return nested, non_nested


def plain_dict_to_nested_dict(data, nested=None, non_nested=None, force_fields=[]):
    """
    Turns an input dictionary with "nested" fields in form
                field_subfield
    into a real nested dictionary in form
                field {subfield}
    For example, the following input dictionary
    data = {
       "ram_free": "1669524",
       "board_serial": "BSS-0123456789",
       "cpu_name": "Intel(R) Core(TM) i7-4700MQ CPU @ 2.40GHz",
       "cpu_cores": "4",
       "ram_total": "2045956",
       "cpu_mhz": "2394.464"
    }
    will output this way:
    data = {
      "ram": {
         "total": "2045956",
         "free": "1669524"
      },
      "cpu": {
         "cores": "4",
         "mhz": "2394.464",
         "name": "Intel(R) Core(TM) i7-4700MQ CPU @ 2.40GHz"
      },
      "board_serial": "BSS-0123456789"
    }
    :param data: dictionary to nest
    :param nested: fields to nest
    :param force_fields: fields to force nesting in
    """
    # separate fields and subfields:
    # nested = {'board': ['serial'], 'cpu': ['cores', 'mhz', 'name'], 'ram': ['free', 'total']}
    nested = {k:list(filter(lambda x: x != k, chain.from_iterable(g)))
             for k,g in groupby(map(lambda x: x.split('_'), sorted(data.keys())),
             key=lambda x:x[0])}

    # create a nested dictionary with those fields that have subfields
    # (board_serial won't be added because it only has one subfield)
    #  nested_dict = {
    #       'cpu': {
    #           'cores': '4',
    #           'mhz': '2394.464',
    #           'name': 'Intel(R) Core(TM) i7-4700MQ CPU @ 2.40GHz'
    #       },
    #       'ram': {
    #           'free': '1669524',
    #           'total': '2045956'
    #       }
    #    }
    nested_dict = {f:{sf:data['{0}_{1}'.format(f,sf)] for sf in sfl} for f,sfl
                  in nested.items() if len(sfl) > 1 or f in force_fields}

    # create a dictionary with the non nested fields
    # non_nested_dict = {'board_serial': 'BSS-0123456789'}
    non_nested_dict = {f:data[f] for f in data.keys() if f.split('_')[0]
                       not in nested_dict.keys()}

    # append both dictonaries
    nested_dict.update(non_nested_dict)

    return nested_dict


def load_wazuh_xml(xml_path):
    with open(xml_path) as f:
        data = f.read()

    # -- characters are not allowed in XML comments
    xml_comment = re.compile(r"(<!--(.*?)-->)", flags=re.MULTILINE | re.DOTALL)
    for comment in xml_comment.finditer(data):
        good_comment = comment.group(2).replace('--','..')
        data = data.replace(comment.group(2), good_comment)

    # < characters should be scaped as &lt; unless < is starting a <tag> or a comment
    data = re.sub(r"<(?!/?\w+.+>|!--)", "&lt;", data)

    # & characters should be scaped if they don't represent an &entity;
    data = re.sub(r"&(?!\w+;)", "&amp;", data)

    return fromstring('<root_tag>' + data + '</root_tag>')


class WazuhVersion:

    def __init__(self, version):

        pattern = "v?(\d)\.(\d)\.(\d)\-?(alpha|beta|rc)?(\d*)"
        m = re.match(pattern, version)

        if m:
            self.__mayor = m.group(1)
            self.__minor = m.group(2)
            self.__patch = m.group(3)
            self.__dev = m.group(4)
            self.__dev_ver = m.group(5)
        else:
            raise ValueError("Invalid version format.")

    def to_array(self):
        array = [self.__mayor]
        array.extend(self.__minor)
        array.extend(self.__patch)
        if self.__dev:
            array.append(self.__dev)
        if self.__dev_ver:
            array.append(self.__dev_ver)
        return array

    def __to_string(self):
        ver_string = "{0}.{1}.{2}".format(self.__mayor, self.__minor, self.__patch)
        if self.__dev:
            ver_string = "{0}-{1}{2}".format(ver_string, self.__dev, self.__dev_ver)
        return ver_string

    def __str__(self):
        return self.__to_string()

    def __eq__(self, new_version):
        return (self.__to_string() == new_version.__to_string())

    def __ne__(self, new_version):
        return (self.__to_string() != new_version.__to_string())

    def __ge__(self, new_version):
        if self.__mayor < new_version.__mayor:
            return False
        elif self.__minor < new_version.__minor:
            return False
        elif self.__patch < new_version.__patch:
            return False
        elif (self.__dev) and not (new_version.__dev):
            return False
        elif (self.__dev) and (new_version.__dev):
            if ord(self.__dev[0]) < ord(new_version.__dev[0]):
                return False
            elif ord(self.__dev[0]) == ord(new_version.__dev[0]) and self.__dev_ver < new_version.__dev_ver:
                return False
            else:
                return True
        else:
            return True

    def __lt__(self, new_version):
        return not (self >= new_version)

    def __gt__(self, new_version):
        return (self >= new_version and self != new_version)

    def __le__(self, new_version):
        return (not (self < new_version) or self == new_version)
