##############################################################################
# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

import os

from litp.core.execution_manager import CallbackExecutionException
from sanapi.sanapiexception import SanApiException
from litp.core.litp_logging import LitpLogger

log = LitpLogger()


def task_match_callback_in_module(task, callback_name, callback_module):
    """check if the callback of the task is the given in a module"""
    if 'function_name' in task.kwargs:
        return task.kwargs['function_name'] == callback_name and \
               task.kwargs['module_name'] == callback_module
    return False


def cmp_values(value1, value2):
    """
    Compares size values that can be in a numeric form or a value with a
    quotient (e.g. 3gb).
    TODO: Rename this function and all calls of it. cmp_values indeed.

    :param value1: First value to compare.
    :type value1: :class:`str` or :class:`int`
    :param value2: Second value to compare.
    :type value2: :class:`str` or :class:`int`
    :returns: 0 if values are equal, -1 or 1 if not equal.
    :rtype: :class:`int`
    """
    try:
        ivalue1 = normalise_to_megabytes(value1)
        ivalue2 = normalise_to_megabytes(value2)
        return cmp(ivalue1, ivalue2)
    except ValueError:
        return cmp(value1, value2)


def values_are_equal(value1, value2):
    """
    Compares size values and returns true if they are equal.
    TODO: Rename this function and all calls of it.
    values_are_equal indeed.

    :param value1: First value to compare.
    :type value1: :class:`str` or :class:`int`
    :param value2: Second value to compare.
    :type value2: :class:`str` or :class:`int`
    :returns: True if values are equal, otherwise False.
    :rtype: :class:`boolean`.
    """

    return cmp_values(value1, value2) == 0


def normalise_to_megabytes(size):
    """
    Normalises a size value to megabytes.

    :param size: Size, as integer or integer with quotient.
    :type size: :class:`str` or :class:`int`.
    :returns: size in megabytes.
    :rtype: class:`str`.

    Example:

    .. code-block:: python

        normalise_to_megabytes('23G')

    """
    size_value = int(size[:len(size) - 1])
    size_magnitude = size[-1]
    if size_magnitude == 'M':
        multiplier = 1
    elif size_magnitude == 'G':
        multiplier = 1024
    elif size_magnitude == 'T':
        multiplier = 1024 * 1024
    else:
        # assume size is in megabytes with no specifier
        multiplier = 1
        if size_magnitude in '0123456789':
            size_value = int(size)
    return str(size_value * multiplier)


def get_san_password(context, user, passwd_key):
    """
    Decrypts the san_password stored in the LITPCrypt keyring
    database.

    :param context: Plugin API context.
    :type context: :class:`PluginApiContext`
    :returns: Decrypted password.
    :rtype:
    """

    return context.get_password(passwd_key, user)


def saninit(san, spa_ip, spb_ip, user, passwd, login_scope):
    """
    Initialise a SanApi instance with connection details.

    :param san: SanApi object to initialise (Vnx1Api or Vnx2Api).
    :type san: :class:`SanApi`
    :param spa_ip: IP address of Storage Processor A.
    :type spa_ip: :class:`str`
    :param spb_ip:  IP address of Storage Processor B.
    :type spb_ip: :class:`str`
    :param user: Username.
    :type user: :class:`str`
    :param passwd: Password.
    :type passwd: :class:`str`
    :param login_scope: Login scope, 'Global' or 'Local'.
    :type login_scope: :class:`str`
    """

    log.event.info("ERIClitpsan: saninit - Initialising connection to SAN")
    # filters non-filled ips
    sp_ips = tuple(ip for ip in (spa_ip, spb_ip) if ip is not None)
    try:
        san.initialise(sp_ips, user, passwd, login_scope,
                       True, False, True)
    except SanApiException, e:
        msg = "Connection to SAN failed with these parameters " + \
              "IPA \"{0}\" IPB \"{1}\" User \"{2}\"" \
              .format(spa_ip, spb_ip, user)
        log.trace.exception(msg + str(e))
        raise CallbackExecutionException(msg + str(e))
    except:
        raise
    return


def getpoolinfo(san, lun_container):
    """
    Get Storage Pool information from SAN via SAN PSL.

    :param san: SanApi object.
    :type san: :class:`SanApi`
    :param lun_container: Name of storage pool.
    :type lun_container: :class:`str`
    :returns: StoragePoolInfo object.
    :rtype: :class:`StoragePoolInfo`
    """

    try:
        poolinfo = san.get_storage_pool(sp_name=lun_container)
    except SanApiException, e:
        msg = "Failed to get Pool Info for pool \"" + lun_container + "\""
        log.trace.exception(msg)
        raise CallbackExecutionException(msg + str(e))
    except:
        raise
    return poolinfo


def get_lun_names_for_bg(model_luns, bg):
    """
    Takes a list of LITP model LUNs and a balancing group and return
    a list of lun_names belonging to that balancing group.

    :param model_luns: List of LITP lun-disks.
    :type model_luns: :class:`list` of
                  :class:`litp.core.model_manager.QueryItem`
    :param bg: Name of balancing group.
    :type bg: :class:`str`
    :returns: List of LUN names.
    :rtype: :class:`str`
    """

    luns = []
    for lun in model_luns:
        if get_bg(lun) == bg:
            luns.append(lun.lun_name)

    # uniqify list (to remove shared LUN duplicates)
    luns = list(set(luns))
    return luns


def get_balancing_sp(model_luns):
    """
    Takes a list of LITP model LUNs and returns a dictionary of balancing
    group keys from the LUNs with values alternating 'A' or 'B'.

    :param model_luns: List of LITP lun-disks
    :type model_luns: :class:`list` of
                  :class:`litp.core.model_manager.QueryItem`
    :returns: Dictionary of balancing group keys with alternating 'A' and 'B'
     values.
    :rtype: :class:`dict`
    """

    balancing_sp = {}

    def initial_sp():
        while True:
            yield 'A'
            yield 'B'

    sp_generator = initial_sp()
    for lun in model_luns:
        if get_bg(lun) not in balancing_sp:
            # if self._get_bg(lun) == None:
            #     balancing_sp[None] = 'auto'
            #     break
            balancing_sp[get_bg(lun)] = sp_generator.next()
    return balancing_sp


def get_bg(lun):
    """
    Returns the balancing group of a lun-disk LITP item.

    :param lun: LITP lun-disk
    :type lun: :class:`litp.core.model_manager.QueryItem`
    :returns: Balancing group for LUN.
    :rtype: :class:`str` or :class:`None`
    """

    if hasattr(lun, 'balancing_group'):
        return lun.balancing_group
    else:
        return None


def toggle_sp(current):
    """
    Switches an SP value of A to B and vice versa. If auto then there is no
    toggle and auto is returned.

    :param current: Current SP: A, B or auto.
    :type current: :class:`str`
    :returns: New SP value.
    :rtype: :class:`str`
    """

    if current == "auto":
        return "auto"
    new = 'A' if current == 'B' else 'B'
    return new


def hba_port_list(hbas):
    """
    Returns a list of hba ports from a list of hba LITP items.

    :param hbas: LITP hba list.
    :type hbas: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    :returns: HBA list.
    :rtype: :class:`list` of class:`str`
    """

    hba_ports = []
    for hba in hbas:
        if hba.hba_porta_wwn:
            hba_ports.append(hba.hba_porta_wwn)
        if hba.hba_portb_wwn:
            hba_ports.append(hba.hba_portb_wwn)
    return hba_ports


def get_initial_items(items):
    """
    Return a list of items in initial state from the supplied list.

    :param items: LITP item list.
    :type items: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    :returns: LITP item list of items in initial state.
    :rtype: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    """

    return [i for i in items if i.is_initial()]


def get_applied_items(items):
    """
    Return a list of items in applied state from the supplied list.

    :param items: LITP item list.
    :type items: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    :returns: LITP item list of items in applied state.
    :rtype: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    """

    return [i for i in items if i.is_applied()]


def get_updated_items(items):
    """
    Return a list of items in updated state from the supplied list.

    :param items: LITP item list.
    :type items: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    :returns: LITP item list of items in updated state.
    :rtype: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    """

    return [i for i in items if i.is_updated()]


def get_removal_items(items):
    """
    Return a list of items in for_removal state from the supplied list.

    :param items: LITP item list.
    :type items: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    :returns: LITP item list of items in for_removal state.
    :rtype: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    """

    return [i for i in items if i.is_for_removal()]


def get_san_luns(san, luns):
    """
    Return a list of LUNs belonging only to the storage containers belonging
    to the 'san' parameter.

    :param san: LITP SAN item.
    :type san: :class:`litp.core.model_manager.QueryItem`
    :param luns: LITP lun-disk item list.
    :type luns: :class:`litp.core.model_manager.QueryItem`
    :returns: LITP  lun-disk item list.
    :rtype: :class:`list` of :class:`litp.core.model_manager.QueryItem`
    """

    san_luns = []
    for cont in san.storage_containers:
        san_luns += [l for l in luns if l.storage_container == cont.name]
    return san_luns


def get_san_from_lun(lun, plugin_api_context):
    """
    Returns the SAN associated with the given LUN.

    :param lun: LITP lun-disk item.
    :type lun: :class:`litp.core.model_manager.QueryItem`
    :param plugin_api_context: API context of LITP model.
    :type plugin_api_context: :class:`PluginApiContext`
    :returns: LITP SAN item.
    :rtype: :class:`litp.core.model_manager.QueryItem` or :class:`None`
    """

    for san in plugin_api_context.query('san-emc'):
        for cont in san.storage_containers:
            if lun.storage_container == cont.name:
                return san
    return None


def get_ip_for_node(node, network_name):
    """
    Return a node's IP address for a given network.

    :param node: LITP node item.
    :type node: :class:`litp.core.model_manager.QueryItem`
    :param network_name: Name of network.

    :type network_name :class:`str`
    :returns: IP address
    :rtype: :class:`str`
    """

    for node_interface in node.network_interfaces:
        if node_interface.network_name:
            if network_name == node_interface.network_name:
                return node_interface.ipaddress
    return None


def get_sgname(node, san, api):
    """
    Return Storage Group Name built up from names in the model, site id,
    deployment id, cluster id, node id.

    :param node: LITP node item.
    :type node: :class:`litp.core.model_manager.QueryItem`
    :param san: LITP SAN item.
    :type san: :class:`litp.core.model_manager.QueryItem`
    :param api: API context of LITP model.
    :type api: :class:`PluginApiContext`
    :returns: Name of Storage Group.
    :rtype: :class:`str`
    """

    return san.storage_site_id + '-' + get_deployment_id(node, api) + '-' + \
        get_cluster_id(node, api) + '-' + node.item_id


def get_deployment_id(node, apicontext):
    """
    Return deployment id for a give node.

    :param node: LITP node item.
    :type node: :class:`litp.core.model_manager.QueryItem`
    :param apicontext: API context of LITP model.
    :type apicontext: :class:`PluginApiContext`
    :returns: Deployment ID.
    :rtype: :class:`str`
    """

    node_dep = None
    deployments = apicontext.query('deployment')
    for d in deployments:
        nodes = d.query('node')
        for n in nodes:
            if n.hostname == node.hostname:
                node_dep = d
                break
    if node_dep:
        return node_dep.item_id
    else:
        msg = "Failed to determine deployment name " + \
              "belonging to node: " + node.hostname
        log.trace.debug(msg)
        raise CallbackExecutionException(msg)


def get_cluster_id(node, apicontext):
    """
    Return cluster id for a give node.

    :param node: LITP node item.
    :type node: :class:`litp.core.model_manager.QueryItem`
    :param apicontext: API context of LITP model.
    :type apicontext: :class:`PluginApiContext`
    :returns: Cluster ID.
    :rtype: :class:`str`
    """

    clusters = apicontext.query('cluster')
    node_cluster = None
    for c in clusters:
        nodes = c.query('node')
        for n in nodes:
            if n.hostname == node.hostname:
                node_cluster = c
                break
    if node_cluster:
        return node_cluster.item_id
    else:
        msg = "Failed to determine cluster name " + \
              "belonging to node: " + node.hostname
        log.trace.debug(msg)
        raise CallbackExecutionException(msg)


def using_thin_luns():
    thin_luns_enabled = False
    thin_lun_file = "/etc/san_luns.cfg"

    if os.path.isfile(thin_lun_file):
        try:
            handle = open(thin_lun_file, "r")
            contents = handle.readlines()
            handle.close()

            for line in contents:
                if not "#" in line:
                    normalised_line = line.lower()
                    normalised_line = normalised_line.replace(" ", "")
                    normalised_line = normalised_line.strip('\n')
                    keyval = normalised_line.split("=")
                    if keyval[0] == 'lun':
                        if keyval[1] == 'thin':
                            thin_luns_enabled = True
                        elif keyval[1] == 'thick':
                            thin_luns_enabled = False
        except IOError:
            pass
        except IndexError:
            pass
    return thin_luns_enabled


def get_model_item_for_lun(lun):
    """
    For a given lun, return the model item to use.
    If the lun is under a cluster, then the cluster model item is returned.
    If the lun is not in a cluster, then the lun model item is returned.
    """
    cluster = lun.get_cluster()
    if cluster is not None:
        return cluster
    return lun
