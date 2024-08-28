# import os
from litp.core.task import CallbackTask
from litp.plan_types.deployment_plan import deployment_plan_tags
from san_plugin.san_utils import log
from san_plugin.san_utils import get_initial_items
from san_plugin.san_utils import get_applied_items
from san_plugin.san_utils import get_updated_items
from san_plugin.san_utils import task_match_callback_in_module
from san_plugin.san_utils import saninit
from san_plugin.san_utils import get_san_password
from san_plugin.san_utils import get_model_item_for_lun
from sanapi.sanapi import api_builder
from sanapi.sanapiexception import SanApiException

from litp.core.execution_manager import CallbackExecutionException

from san_plugin.node_storage_mco_api import NodeStorageMcoApi

UPDATE_LUN_PROPERTY = 7
TASK_REG_LUN_LUNNAME = 4
TASK_REG_LUN_CONTAINER = 5
TASK_SCSI_SCAN_HOSTNAME = 0


def generate_node_tasks_after_expanding_luns(plugin, plugin_api_context,
    lun_updated_tasks):
    """
    Generate all node storage tasks

    :param plugin: a reference to the san plugin itself
    :type plugin: :class:`san_plugin.sanplugin.SanPlugin`
    :param plugin_api_context: API context of LITP model.
    :type plugin_api_context: :class:`litp.core.PluginApiContext`
    :param lun_updated_tasks: List of tasks for updating the luns
    :type lun_updated_tasks: list of litp.core.task.CallbackTask

    :returns: a list of tasks needed to be performed in nodes due to the
        expansion lun tasks in lun_updated_tasks
    :rtype: list of litp.core.task.CallbackTask
    """
    tasks = []
    if lun_updated_tasks:
        tasks += _get_expand_lun_tasks(plugin, plugin_api_context,
            lun_updated_tasks)
    return tasks


def generate_multipath_editing_tasks(plugin, plugin_api_context, scsi_tasks):
    """
    TODO ...
    :param plugin_api_context: API context of LITP model.
    :type plugin_api_context: :class:`PluginApiContext`
    :returns: A list of tasks to be executed.
    :rtype: :class:`list` of :class:`CallbackTask`
    """

    log.event.info("ERIClitpsan: generate_multipath_editing_tasks")

    # preamble='SAN.create_configuration: generate_multipath_editing_tasks'
    tasks = []
    nodes = get_applied_items(plugin_api_context.query('node'))

    vcs_clusters = get_applied_items(plugin_api_context.query(
        'vcs-cluster'))

    for cluster in [c for c in vcs_clusters if c.cluster_type == 'vcs']:
        nodes = get_applied_items(cluster.query('node'))
        for node in nodes:
            luns = get_initial_items(node.query('lun-disk'))
            for lun in luns:
                log.event.info("Creating multipath task for LUN %s" %
                    lun.lun_name)
                future_uuid_path = lun.get_vpath()
                task = CallbackTask(node.system.get_source(),
                         "Configuring multipath for LUN \"{0}\""
                         .format(lun.lun_name),
                         plugin.callback_function,
                         node.hostname, future_uuid_path, lun.lun_name,
                         function_name="edit_mpath_cb_task",
                         module_name=__name__)

                for scsi_task in scsi_tasks:
                    if task_match_callback_in_module(scsi_task,
                        'scsi_scan_hosts_cb_task', __name__):
                        if scsi_task.args[TASK_SCSI_SCAN_HOSTNAME] == \
                                                        node.hostname:
                            task.requires.add(scsi_task)

                task.model_items.add(lun)
                tasks.append(task)
    log.event.info("SAN multipath task generation complete")
    return tasks


def generate_scsi_scan_hosts_tasks(plugin, plugin_api_context, lun_tasks):
    """
    TODO ...
    :param plugin_api_context: API context of LITP model.
    :type plugin_api_context: :class:`PluginApiContext`
    :returns: A list of tasks to be executed.
    :rtype: :class:`list` of :class:`CallbackTask`
    """

    log.event.info("ERIClitpsan: generate_scsi_scan_hosts_tasks")

    preamble = 'SAN.create_configuration: '
    tasks = []
    applied_nodes = get_applied_items(plugin_api_context.query('node'))
    updated_nodes = get_updated_items(plugin_api_context.query('node'))
    nodes = applied_nodes + updated_nodes

    for node in nodes:
        msg = "Querying node \"{0}\" for LUNs".format(node.hostname)
        log.trace.debug(preamble + msg)

        node_luns = get_initial_items(node.system.disks.query('lun-disk'))
        if len(node_luns) > 0:
            # then we need task for scsi scan.
            log.event.info("Creating multipath task for node")
            task = CallbackTask(node.system.get_source(),
                    "Scanning SCSI Hosts for Node \"{0}\""
                    .format(node.hostname),
                    plugin.callback_function,
                    node.hostname,
                    function_name="scsi_scan_hosts_cb_task",
                    module_name=__name__)
            for lun in node_luns:
                #task.requires.add(lun)
                task.model_items.add(lun)

                for ltask in lun_tasks:
                    if ltask.callback == plugin.create_reglun_cb_task and \
                        ltask.args[TASK_REG_LUN_LUNNAME] == lun.lun_name \
                            and ltask.args[TASK_REG_LUN_CONTAINER] == \
                                lun.storage_container:
                        task.requires.add(ltask)

            tasks.append(task)
    log.event.info("SAN SCSI scan task generation complete")
    return tasks


def scan_scsi_device_mpath_task(callbackapi, hostname, future_uuid, lun_name):
    """
    TODO: CHANGE LOGGING AND DESC NOW FUNCTION HAS CHANGED
    Task for running a scsi scan on multipath controlled node

    :param callbackapi: LITP callback api object
    :type callbackapi: CallbackApi
    :param hostname: the name of the node to be scsi scanned
    :type hostname: string

    :returns: True if successful
    :rtype: boolean

    :throws: CallbackExecutionException if any mco error
    """
    # Stupid line to avoid pylint
    if not callbackapi:
        log.trace.debug("wtf")

    preamble = 'SAN.scan_scsi_mpath: "{h}"'.format(h=hostname)
    uuid = callbackapi.query_by_vpath(future_uuid).uuid
    log.event.info(preamble + \
        " about to scan scsi mpath dor lun \"{l}\" using uuid \"{u}\""
            .format(l=lun_name, u=uuid))

    mco = _getNodeStorageMcoApi(hostname)
    try:
        mco.node_scan_scsi_device_mpath(uuid)
    except Exception, err:
        msg = "\"{0}\"".format(err)
        log.trace.exception(preamble + "Failed to scan scsi node {h}".format(
            h=hostname))
        log.trace.exception(preamble + msg)
        raise CallbackExecutionException(msg)
    log.event.info(preamble + "scan scsi of node: {h} successfull !".format(
        h=hostname))
    return True


def scsi_scan_hosts_cb_task(callbackapi, hostname):
    """
    TODO Create Storage Group

    :param api_context: API context of LITP model.
    :type api_context: :class:`PluginApiContext`
    :type passwd_key: :class:`str`
    :param hostname: Hostname of node to run MCO command on.
    :type hostname: :class:`str`
    :
    :
    :returns: True. just returns true? No raising of exceptions?
    :rtype: :class:`boolean`
    """
    # Stupid line to avoid pylint
    if not callbackapi:
        log.trace.debug("wtf")

    preamble = "SAN.scsi_scan_hosts_cb_task: \"" + hostname + "\" : "
    log.event.info(preamble + "about to try SCSI scan hosts2")

    mco = _getNodeStorageMcoApi(hostname)
    try:
        mco.scan_scsi_hosts()
    except Exception, err:
        log.trace.exception(preamble + "Failed to scan SCSI hosts")
        log.trace.exception(preamble + err)
        raise CallbackExecutionException(err)
    log.event.info(preamble + "SCSI hosts scanned successfully")
    return True


def _getNodeStorageMcoApi(hostname):
    return NodeStorageMcoApi(hostname)


def edit_mpath_cb_task(callbackapi, hostname, future_uuid, lun_name):
    """

    :param api_context: API context of LITP model.
    :type api_context: :class:`PluginApiContext`
    :type passwd_key: :class:`str`
    :param hostname: Hostname of node to run MCO command on.
    :type hostname: :class:`str`
    :
    :
    :returns: True. just returns true? No raising of exceptions?
    :rtype: :class:`boolean`
    """
    preamble = "SAN.edit_mpath_cb_task: \"" + hostname + "\" : "
    log.event.info(preamble + " about to EDIT mpath")

    uuid = callbackapi.query_by_vpath(future_uuid).uuid
    log.event.info(preamble + "Adding UUID %s to multipath %s" % (
        uuid, lun_name))

    mco = _getNodeStorageMcoApi(hostname)
    try:
        mco.edit_multipath(uuid)
    except Exception, err:
        msg = "\"{0}\"".format(err)
        log.trace.exception(preamble + "Failed to edit multipath")
        log.trace.exception(preamble + msg)
        raise CallbackExecutionException(msg)
    log.event.info(preamble + "Multipath edited successfully")
    return True


def scan_scsi_device_dmp_task(callbackapi, hostname, lun_name, san_type,
                                    ipa, ipb, user, pass_key, scope):
    """
    TODO: CHANGE DESC & DEBUG FOR NEW FN CHANGES
    Task for running a scsi scan on dmp controlled node

    :param callbackapi: LITP callback api object
    :type callbackapi: CallbackApi
    :param hostname: the name of the node to be scsi scanned
    :type hostname: string

    :returns: True if successful
    :rtype: boolean

    :throws: CallbackExecutionException if any mco error
    """
    # Stupid line to avoid pylint
    if not callbackapi:
        log.trace.debug("wtf")

    preamble = 'SAN.scan_scsi_dmp: "{h}"'.format(h=hostname)
    log.event.info(preamble + " about to scan scsi dmp")

    try:
        san = api_builder(san_type, log.trace)
        password = get_san_password(callbackapi, user, pass_key)
        saninit(san, ipa, ipb, user, password, scope)
        luninfo = san.get_lun(lun_name=lun_name, logmsg=False)
    except SanApiException, e:
        msg = "Failed to get LUN information for SCSI scan \"" + \
                                                lun_name + "\" "
        log.trace.exception(msg)
        raise CallbackExecutionException(msg + str(e))

    lun_id = luninfo.id
    mco = _getNodeStorageMcoApi(hostname)
    try:
        mco.node_scan_scsi_device_dmp(lun_id)
    except Exception, err:
        msg = "\"{0}\"".format(err)
        log.trace.exception(preamble + "Failed to scan scsi node {h}".format(
            h=hostname))
        log.trace.exception(preamble + msg)
        raise CallbackExecutionException(msg)
    log.event.info(preamble + "scan scsi of node: {h} successfull !".format(
        h=hostname))
    return True


def _filter_lun_expand_tasks(plugin, lun_updated_tasks):
    """
    given a list of tasks, filter only the tasks for expanding a lun
    """
    return [task for task in lun_updated_tasks if \
                 task.callback == plugin.update_lun_task and \
                 task.args[UPDATE_LUN_PROPERTY] == "size"]


def _get_expand_lun_tasks(plugin, context, lun_updated_tasks):
    """
    Generate the needed tasks in the node because some contained luns has
    been expanded
    """

    emc_sans = context.query('san-emc')
    nodes = context.query('node')
    vcs_node_types = _get_node_types(context)

    lun_expand_tasks = _filter_lun_expand_tasks(plugin, lun_updated_tasks)

    lun_tasks_dict = {}
    for lun_expand_task in lun_expand_tasks:
        lun_tasks_dict[lun_expand_task.model_item.vpath] = lun_expand_task
        for model_item in lun_expand_task.model_items:
            lun_tasks_dict[model_item.vpath] = lun_expand_task

    all_tasks = []
    for san in emc_sans:
        for storage_container in san.storage_containers:
            poolname = storage_container.name
            for node in nodes:
                if node.vpath in vcs_node_types:
                   # node should be in a vcs-cluster, otherwise is ignored
                    #node_required_tasks = []
                    luns = node.system.disks.query('lun-disk',
                        storage_container=poolname)
                    for lun in luns:
                        if lun.is_updated():
                            if lun.size != lun.applied_properties["size"]:
                                scan_task = _gen_scan_scsi_device_tasks(plugin,
                                                    san, node, lun,
                                                    vcs_node_types[node.vpath])
                                req_task = lun_tasks_dict[lun.vpath]
                                scan_task.requires.add(req_task)
                                all_tasks += [scan_task]
                #else:
                #    log.trace.debug(
                #        "node {n} 'cause is not in a vcs-cluster".format(
                #            n=node.hostname))
    return all_tasks


def _get_node_types(context):
    """
    Get the cluster type of all nodes contained in vcs-clusters

    :returns: a dictionary where each key is the node.vpath string, and the
        value is the cluster.type value ( vcs or sfha )
    :rtype: dictionary
    """
    nodes = {}
    clusters = context.query('vcs-cluster')
    for cluster in clusters:
        for node in cluster.query('node'):
            nodes[node.vpath] = cluster.cluster_type
    return nodes


def _gen_scan_scsi_device_tasks(plugin, san, node, lun, node_type):
    """return the corresponding node scan scsi task, depending on the type
    of the cluster where the node lives in
    """
    tasks = []
    if node_type == "vcs":
        future_uuid_path = lun.get_vpath()
        task_model_item = get_model_item_for_lun(lun)
        task = CallbackTask(task_model_item,
            "mpath scsi scan for expanded LUN {l}".format(l=lun.lun_name),
            plugin.callback_function,
            node.hostname, future_uuid_path, lun.lun_name,
            function_name='scan_scsi_device_mpath_task',
            module_name=__name__)
        if task_model_item.item_type_id != "lun-disk":
            task.tag_name = deployment_plan_tags.PRE_NODE_CLUSTER_TAG
            task.model_items.add(lun)
        tasks.append(task)
    elif node_type == "sfha":
        task_model_item = get_model_item_for_lun(lun)
        task = CallbackTask(task_model_item,
            "dmp scsi scan for expanded LUN {l}".format(l=lun.lun_name),
            plugin.callback_function,
            node.hostname, lun.lun_name, san.san_type,
            san.ip_a, san.ip_b, san.username, san.password_key,
            san.login_scope, function_name='scan_scsi_device_dmp_task',
            module_name=__name__)
        if task_model_item.item_type_id != "lun-disk":
            task.tag_name = deployment_plan_tags.PRE_NODE_CLUSTER_TAG
            task.model_items.add(lun)
        tasks.append(task)
    else:
        # ignore the node
        task = None
    return task
