##############################################################################
# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

import time
import traceback

from litp.core.execution_manager import CallbackExecutionException, PluginError
from sanapi.sanapiexception import SanApiEntityNotFoundException
# from litp.core.task import CallbackTask as OriginalCallbackTask
# from litp.core.execution_manager import CallbackTask
from litp.core.task import CallbackTask
from sanapi.sanapi import api_builder

from litp.plan_types.create_snapshot import create_snapshot_tags
from litp.plan_types.remove_snapshot import remove_snapshot_tags
from litp.plan_types.restore_snapshot import restore_snapshot_tags

from san_plugin.san_utils import log
from san_plugin.san_utils import normalise_to_megabytes
from san_plugin.san_utils import get_san_password
from san_plugin.san_utils import saninit
from san_plugin.san_utils import getpoolinfo
from san_plugin.san_utils import using_thin_luns

from sanapi.sanapiexception import SanApiException


LITP_UPG_SNAP_NAME = "snapshot"
SAN_TIMEOUT = 20
# class CallbackTask(OriginalCallbackTask):
#     """
#     Helper class to make easier debugging
#     """
#     def __repr__(self):
#         return OriginalCallbackTask.__repr__(self)+"({0})".format(
#             self.description)


class SnapshotTask(object):
    """
    Helper class to model a snapshot task object.

    Attributes:
    :ivar SnapshotTask.task: The :class:`CallbackTask` to be executed.
    :vartype SnapshotTask.task: :class:`CallbackTask`
    :ivar lun: The LUN the task is associated with.
    :vartype SnapshotTask.lun: :class:`str`
    :ivar SnapshotTask.san: The SAN the task is associated with.
    :vartype SnapshotTask.san: :class:`str`
    :ivar SnapshotTask.action: The snapshot action. It could any of "create",
        "remove", "restore".
    :vartype SnapshotTask.action: :class:`str`
    :ivar SnapshotTask.snap_name: The snapshot name.
    :vartype SnapshotTask.snap_name: :class:`str`
    """

    def __init__(self, plugin=None, action="", snap_name="", task=None,
        lun=None, node=None, san=None, container=None):
        """
        :param plugin: The plugin.
        :type plugin: :class:`str` Default; None
        :param action: The action.
        :type action: :class:`str` Default; ""
        :param snap_name: The name of the snap.
        :type snap_name: :class:`str` Default; ""
        :param task: The snap task.
        :type task: :class:`str` Default; None
        :param lun: The LUN.
        :type lun: :class:`str` Default; None
        :param node: The node.
        :type node: :class:Node Default; None
        :param san: The SAN.
        :type san: :class:`str` Default; None
        :param container: The container
        :type container: :class:`str` Default; None
        """

        self.plugin = plugin
        self.lun = lun
        self.node = node
        self.san = san
        self.container = container
        self.snap_name = snap_name
        self.action = action
        if task:
            self.task = task
        else:
            self.task = self._gen_task()

        self.required = []

    def __str__(self):
        return ("<SnapshotTask {path} {action} ( '{nodename}',"
                "'{lunname}')>").format(
                path=self.node.vpath,
                action=self.action,
                nodename=self.node.hostname,
                lunname=self.lun.lun_name)

    def __repr__(self):
        return self.__str__()

    def add_required_task(self, task):
        """
        Add a task to the required lists of Tasks
        """
        self.required.append(task)
        self.task.requires.add(task.task)

    def _gen_task(self):
        """
        TODO Generate the psl task.

        :returns: The PSL task.
        :rtype: :class:`str`
        """

        task = None
        if self.action == 'create':
            task = CallbackTask(self.san, "Creating snapshot for LUN {0}"
                            .format(self.lun.lun_name),
                            self.plugin.callback_function,
                            # self.plugin.create_lun_snapshot_psl_task,
                            self.san.san_type, self.san.ip_a,
                            self.san.ip_b, self.san.username,
                            self.san.password_key,
                            self.san.login_scope, self.lun.lun_name,
                            self.snap_name,
                            function_name='create_lun_snapshot_psl_task',
                            module_name=__name__,
                            tag_name=create_snapshot_tags.SAN_LUN_TAG)
        else:
            if self.action == 'remove':
                task = CallbackTask(self.san,
                            "Removing LUN Snapshot for LUN {0}"
                            .format(self.lun.lun_name),
                            self.plugin.callback_function,
                            # self.plugin.remove_lun_snapshot_psl_task,
                            self.san.san_type,
                            self.san.ip_a, self.san.ip_b,
                            self.san.username, self.san.password_key,
                            self.san.login_scope, self.lun.lun_name,
                            self.snap_name,
                            function_name='remove_lun_snapshot_psl_task',
                            module_name=__name__,
                            tag_name=remove_snapshot_tags.SAN_LUN_TAG)
        return task


class GenericTask(SnapshotTask):
    """
    Helper class to model a verification task object.
    """
    def __init__(self, task, node, action=""):
        """
        Initiates the verify task.
        """

        super(GenericTask, self).__init__(task=task, node=node,
            action=action)

    def __str__(self):
        return "<GenericTask {path} {action} '{nodename}' >".format(
                    path=self.node.vpath,
                    action=self.action,
                    nodename=self.node.hostname)

    def __repr__(self):
        return self.__str__()


def get_tasks(plugin, plugin_api_context, action, snap_name):
    """
    Gets the tasks.

    :param plugin: The plugin.
    :type plugin: :class:`str`
    :param plugin_api_context: The plugin API context.
    :type plugin_api_context: :class:`str`
    :param action: The action.
    :type action: :class:`str`
    :param snap_name: The name of the snap.
    :type snap_name: :class:`str`
    :returns: A list of tasks.
    :rtype: :class:`list`
    :raises PluginError: Raised if the snapshot model missing for
        remove_snapshot action.
    """

    log.event.info("ERIClitpsan: snapshot.get_tasks")
    preamble = "SAN._get_snapshot_tasks "
    log.trace.debug(preamble + "action: \"{0}\"  snap_name: \"{1}\""
                    .format(action, snap_name))
    tasks = []

    # Return if not upgrade snap
    if snap_name != LITP_UPG_SNAP_NAME:
        preamble = "SAN.snapshots.get_tasks "
        log.event.info(preamble + "OMBS snapshot selected: "
                        "SAN plugin will do nothing")
        return tasks

    # Use current model for create, snapped model for restore and delete
    if action == 'create':
        log.event.info(preamble + "Using current model for \"create\"")
        snapshot_api = plugin_api_context
    else:
        log.event.info(preamble + "Using snapshot model for \"{0}\""
                                .format(action))
        snapshot_api = plugin_api_context.snapshot_model()

        if not snapshot_api:  # bug 10581
            msg = 'Snapshot model missing for remove_snapshot action'
            raise PluginError(msg)

    sans = snapshot_api.query('san-emc')
    nodes = snapshot_api.query('node')
    luns_to_be_snapped = set([])
    all_snapshot_tasks = []
    for san in sans:
        log.trace.debug(preamble + "Configuring snap tasks for SAN:"
                        "\"{0}\"".format(san.name))
        for container in [cont for cont in san.storage_containers \
                          if cont.type.lower() == "pool"]:
            container_luns = set([])
            log.trace.debug(preamble + "Configuring snap tasks for "
                            "Pool: \"{0}\"".format(container.name))
            snapshot_tasks = []
            for node in nodes:
                log.trace.debug(preamble + "Configuring snap tasks"
                                "for Node: \"{0}\""
                                .format(node.hostname))
                node_luns = node.system.disks.query('lun-disk',
                                   storage_container=container.name)
                node_luns = [lun for lun in node_luns if
                                 lun.external_snap == "false"]

                log.trace.debug(preamble + "Luns: \"{0}\""
                                .format(len(node_luns)))
                snap_luns = [l for l in node_luns if int(l.snap_size) > 0]

                log.trace.debug(preamble + "Snap Luns: \"{0}\""
                                .format(len(snap_luns)))

                for lun in snap_luns:
                    if not lun in container_luns:
                        container_luns.add(lun)
                        if lun.lun_name not in luns_to_be_snapped:
                            task = SnapshotTask(plugin=plugin, action=action,
                                snap_name=snap_name, lun=lun, node=node,
                                san=san)
                            tasks.append(task)
                            snapshot_tasks.append(task)
                            all_snapshot_tasks.append(task)
                            log.trace.debug(preamble + "Adding task for" \
                                        " lun: \"{0}\""
                                        .format(lun.lun_name))
                            luns_to_be_snapped.add(lun.lun_name)
            if action == "create":
                add_create_prevalidation_tasks(plugin, tasks, snapshot_tasks,
                    san, container, container_luns, snap_name)

    return [task.task for task in tasks]


def add_create_prevalidation_tasks(plugin, tasks, container_tasks, san,
    container, luns, snap_name):
    """
    TODO Add pre-validation tasks to confirm that no plan-breaking exceptions
    may occur during the execution of a snap plan.

    :param plugin: The plugin.
    :type plugin: :class:`str`
    :param tasks: A list of tasks.
    :type tasks: :class:`list`
    :param container_tasks: The container tasks.
    :type container_tasks: :class:`list`
    :param action: The action.
    :type action: :class:`str`
    :param san: The SAN.
    :type san: :class:`str`
    :param container: The container.
    :type container: :class:`str`
    :param luns: A list of LUNs.
    :type luns: :class:`list`
    :param snap_name: The snap name.
    :type snap_name: :class:`str`
    """
    if not container_tasks:
        return
    pool_check_task = gen_pool_size_check_task(plugin, san, container,
            luns)
    san_already_exists_check_task = \
            gen_san_already_exists_check_task(plugin, san, luns, snap_name)
    for task in container_tasks:
        task.task.requires.add(pool_check_task)
        task.task.requires.add(san_already_exists_check_task)
    tasks.insert(0, GenericTask(pool_check_task, container,
        action="pool_check"))
    tasks.insert(0, GenericTask(san_already_exists_check_task,
        container, action="san_exists"))


def add_restore_prevalidation_tasks(plugin, tasks, snaptasks, snap_name):
    for task in snaptasks:
        verify_snapshot_task = gen_verify_snapshot_exists_task(plugin,
                task.san, task.lun, snap_name)

        # move the verify lun staff to restore_snapshot task
        # verify_lun_is_ready = gen_verify_lun_is_ready(plugin,
        #         task.san, task.lun)
        # task.task.requires.add(verify_lun_is_ready)
        task.task.requires.add(verify_snapshot_task)
        tasks.insert(0, GenericTask(verify_snapshot_task,
            task.node, action="verify_snapshot"))
        # tasks.insert(0, GenericTask(verify_lun_is_ready,
        #    task.node, action="lun_ready"))
        log.trace.info('nothing to do')


def gen_pool_size_check_task(plugin, san, container, luns):
    """
    TODO

    :param plugin: The plugin.
    :type plugin: :class:`str`
    :param san: The SAN.
    :type san: :class:`str`
    :param container: The container.
    :type container: :class:`str`
    :param luns: A list of LUNs.
    :type luns: :class:`list`
    :returns: The callback task.
    :rtype: :class:`CallbackTask`
    """
    log.event.info("ERIClitpsan: _gen_poolsizechecktask")
    preamble = "SAN._gen_poolsizechecktask "

    thin_luns = using_thin_luns()
    log.event.info("Thin LUN is set to: %s " % str(thin_luns))

    if thin_luns:
        log.trace.debug(preamble + "luns:" + str(luns))
        log.trace.debug(preamble + "Check there is enough space for thin"
                        " LUN snapshots in Container: \"{0}\""
                        .format(container.name))

        return CallbackTask(san, "Checking Pool reserve and LUN consumed",
                plugin.callback_function,
                san.san_type, san.ip_a,
                san.ip_b, san.username, san.password_key, san.login_scope,
                container.name,
                function_name='pool_size_check_thin_lun_psl_task',
                module_name=__name__,
                tag_name=create_snapshot_tags.VALIDATION_TAG)
    else:
        snap_sizes = [(int(normalise_to_megabytes(l.size)),
                       int(l.snap_size)) for l in luns]

        log.trace.debug(preamble + "luns:" + str(luns))
        log.trace.debug(preamble + "snap_sizes:" + str(snap_sizes))
        snap_reserve = sum([s[0] * s[1] / 100 if s[1] > 0 else 1
                            for s in snap_sizes])
        log.trace.debug(preamble + "Task to check that we have at least "
                        "\"{0}MB\" reserve in Container: \"{1}\""
                        .format(snap_reserve, container.name))
        return CallbackTask(san, "Checking Pool Snapshot Reserve",
                plugin.callback_function,
                san.san_type, san.ip_a,
                san.ip_b, san.username, san.password_key, san.login_scope,
                container.name, snap_reserve,
                function_name='pool_size_check_psl_task',
                module_name=__name__,
                tag_name=create_snapshot_tags.VALIDATION_TAG)


def pool_size_check_psl_task(callbackapi, san_type, ip_a, ip_b, username,
        pkey, login_scope, luncontainer, reserve_size):
    """
    TODO

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type:  The type of SAN.
    :type san_type: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :param luncontainer: The type of LUN container.
    :type luncontainer: :class:`str`
    :param reserve_size: The reserve size.
    :type reserve_size: :class:`str`
    :returns: True if the available pool space is larger than the reserve
        size.
    :rtype: :class:`boolean`
    :raises CallbackExcecution: Raised if unable to create snapshots due to
        insufficient space in the pool.
    """
    log.event.info("ERIClitpsan: poolsizecheck")
    preamble = "SAN.poolsizecheck - "
    api = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    saninit(api, ip_a, ip_b, username, password, login_scope)
    poolinfo = getpoolinfo(api, luncontainer)
    if poolinfo is not None:
        log.trace.debug("Total pool size: " + str(poolinfo.size) +
                        " snap reserve: " + str(reserve_size) +
                        " available space in pool size: " +
                        str(poolinfo.available))
        if int(float(poolinfo.available)) < reserve_size:
            msg = "Cannot create snapshots, Insufficient "\
               "free space in Pool \"{0}\"".format(luncontainer)
            log.trace.error(preamble + msg)
            raise CallbackExecutionException(msg)
    else:
        msg = "Unable to determine free space in pool {0} "\
              .format(luncontainer)
        log.trace.error(preamble + msg)
        raise CallbackExecutionException(msg)

    return int(float(poolinfo.available)) >= reserve_size


def pool_size_check_thin_lun_psl_task(callbackapi, san_type, ip_a, ip_b,
        username, pkey, login_scope, luncontainer):
    """
    TODO

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type:  The type of SAN.
    :type san_type: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :param luncontainer: The type of LUN container.
    :type luncontainer: :class:`str`
    :returns: True if the available pool space is larger than the reserve
        size.
    :rtype: :class:`boolean`
    :raises CallbackExcecution: Raised if unable to create snapshots due to
        insufficient space in the pool.
    """
    log.event.info("ERIClitpsan: poolsizecheckthin")
    preamble = "SAN.poolsizecheckthin - "

    nodes = callbackapi.query('node')
    snap_luns = []

    for node in nodes:
        luns = node.system.disks.query('lun-disk',
                           storage_container=luncontainer)
        luns = [l for l in luns if l.external_snap == "false"]
        luns = [l for l in luns if int(l.snap_size) > 0]

        for lun in luns:
            if not any(l.lun_name == lun.lun_name for l in snap_luns):
                snap_luns.append(lun)

    api = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    saninit(api, ip_a, ip_b, username, password, login_scope)
    poolinfo = getpoolinfo(api, luncontainer)

    if poolinfo is not None:
        try:
            san_luns = api.get_luns()
        except SanApiException, e:
            msg = "Failed to get LUN Info for pool reserve"
            log.trace.exception(msg)
            raise CallbackExecutionException(msg + str(e))
        except:
            raise

        reserve_size = 0
        # REMOVE snap_sizes = []
        for model_lun in snap_luns:
            for san_lun in san_luns:
                if model_lun.lun_name == san_lun.name:
                    name = model_lun.lun_name
                    snap = model_lun.snap_size
                    size = san_lun.consumed
                    log.event.info("Including LUN \"{0}\", consumed \"{1}\","\
                                    " snap \"{2}\"".format(name, size, snap))
                    lun_reserve = int(size) * int(snap) / 100
                    reserve_size += lun_reserve
                    # REMOVE lun_snap = (int(size), int(snap))
                    #REMOVE snap_sizes.append(lun_snap)

        log.trace.debug("Total pool size: " + str(poolinfo.size) +
                        " snap reserve: " + str(reserve_size) +
                        " available space in pool size: " +
                        str(poolinfo.available))

        if int(float(poolinfo.available)) < reserve_size:
            msg = "Cannot create snapshots, Insufficient "\
               "free space in Pool \"{0}\"".format(luncontainer)
            log.trace.error(preamble + msg)
            raise CallbackExecutionException(msg)

    else:
        msg = "Unable to determine free space in pool {0} "\
              .format(luncontainer)
        log.trace.error(preamble + msg)
        raise CallbackExecutionException(msg)
    return int(float(poolinfo.available)) >= reserve_size


def gen_verify_lun_is_ready(plugin, san, lun):
    """
    TODO

    :param plugin: The plugin.
    :type plugin: :class:`str`
    :param san: The SAN.
    :type san: :class:`str`
    :param lun: The LUN.
    :type lun: :class:`str`
    :returns: The callback task.
    :rtype: :class:`CallbackTask`
    """

    log.event.info("ERIClitpsan: gen_verify_lun_is_ready {0}"
        .format(lun.lun_name))
    return CallbackTask(san, "Verify lun is ready",
            plugin.callback_function,
            san.san_type,
            # plugin.verify_lun_is_ready_psl_task, san.san_type,
            san.name, san.ip_a, san.ip_b, lun.lun_name, san.username,
            san.password_key, san.login_scope,
            function_name='verify_lun_is_ready_psl_task',
            module_name=__name__,
            tag_name=restore_snapshot_tags.VALIDATION_TAG)


def san_timeout():
    """
    TODO Retrieves the SAN timeout.

    :returns: The SAN timeout value.
    :rtype: :class:`int`
    """

    return SAN_TIMEOUT


def verify_lun_is_ready_psl_task(callbackapi, san_type, sanname,
        ip_a, ip_b, lunname, username, pkey, login_scope):
    """
    TODO Verifies if the LUN is ready for the PSL task.

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type: The SAN type.
    :type san_type: :class:`str`
    :param sanname: The name of the SAN.
    :type sanname: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param lunname: The LUN name.
    :type lunname: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :returns: True if operation finishes successfully.
    :rtype: :class:`boolean`
    :raises CallbackExecutionException: Raised if the san times out before the
        operation finishes.
    """

    log.event.info("ERIClitpsan: verify_lun_is_ready_psl_task")
    preamble = "SAN.verify_lun_is_ready_psl_task - "
    api = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    saninit(api, ip_a, ip_b, username, password, login_scope)
    log.event.info(preamble + "About to gather all snaps on SAN:"\
                    "\"{0}\"".format(sanname))

    luninfo = api.get_lun(lun_name=lunname)
    # log.event.info("ERIClitpsan luninfo {t}".format(t=luninfo.__class__))
    # for k in luninfo.__dict__:
    #    log.event.info('{k}->{v}'.format(k=k, v=str(luninfo.__dict__[k])))
    # log.event.info("current_op -> {co}".format(co=luninfo._current_op))
    timeout_loop = 0
    while str(luninfo.current_op) != "None" and timeout_loop < san_timeout():
        timeout_loop += 1
        log.trace.info('{pre} waiting operation {op} to finish ({secs}secs)'
            .format(pre=preamble, op=luninfo.current_op, secs=timeout_loop)
        )
        time.sleep(1)
        luninfo = api.get_lun(lun_name=lunname)
    if timeout_loop >= san_timeout():
        msg = "SAN timeout. waiting for operation: {op} to finish".format(
            op=luninfo.current_op)
        log.trace.error("{pre} {msg}".format(pre=preamble, msg=msg))
        raise CallbackExecutionException(msg)
    return True


def gen_san_already_exists_check_task(plugin, san, luns, snap_name):
    """
    TODO

    :param plugin: The plugin.
    :type plugin: :class:`str`
    :param san: The SAN.
    :type san: :class:`str`
    :param luns: The list of LUNs.
    :type luns: :class:`list`
    :param snap_name: The snap name.
    :type snap_name: :class:`str`
    :returns: The callback task.
    :rtype: :class:`CallbackTask`
    """

    # Avoid pylint
    if not snap_name:
        log.trace.debug("snap name not set")

    log.event.info("ERIClitpsan: gen_san_already_exists_check_task")
    snaps = ["L_" + l.lun_name + "_" for l in luns]

    return CallbackTask(san, "Checking for existing snapshots",
            plugin.callback_function,
            san.san_type,
            # plugin.snapshot_already_exists_psl_task, san.san_type,
            san.name, san.ip_a, san.ip_b, san.username, san.password_key,
            san.login_scope, snaps,
            function_name='snapshot_already_exists_psl_task',
            module_name=__name__,
            tag_name=create_snapshot_tags.VALIDATION_TAG)


def snapshot_already_exists_psl_task(callbackapi, san_type, sanname,
        ip_a, ip_b, username, pkey, login_scope, snaps):
    """
    TODO Checks if the snapshot already exists.

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type: The SAN type.
    :type san_type: :class:`str`
    :param sanname: The SAN name.
    :type sanname: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :param snaps: The list of snapshot names.
    :type snaps: :class:`list` of :class:`str`
    :returns: True if snap does not exist. Why???
    :rtype: :class:`boolean`
    """

    log.event.info("ERIClitpsan: snapshot_already_exists_psl_task")
    preamble = "SAN.existingsnapcheck - "
    api = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    saninit(api, ip_a, ip_b, username, password, login_scope)
    log.trace.debug(preamble + "About to gather all snaps on SAN:"\
                    "\"{0}\"".format(sanname))
    existingsnaps = api.get_snapshots()
    sansnaps = [s.snap_name for s in existingsnaps]
    snapsfound = [s for s in sansnaps if s in snaps]
    snapfound = False
    if len(snapsfound) > 0:
        snapfound = True
        snaplist = ", ".join(snapsfound)
        msg = "Cannot create snapshots, name "\
               "pre-existing snapshots found: %s" % snaplist
        log.trace.error(preamble + msg)
        raise CallbackExecutionException(msg)
    return not snapfound


def gen_verify_snapshot_exists_task(plugin, san, lun, snap_name):
    """
    TODO Verify napshots exist?? below

    :param plugin: The plugin.
    :type plugin: :class:`str`
    :param san: The SAN.
    :type san: :class:`str`
    :param lun: The LUN.
    :type lun: :class:`str`
    :param snap_name: The snap name.
    :type snap_name: :class:`str`
    """

    # Avoid pylint
    if not snap_name:
        log.trace.debug("snap name not set")

    log.event.info("ERIClitpsan: _gen_verifyspanexiststask")
    luns = [lun]
    snaps = ["L_" + l.lun_name + "_" for l in luns]

    return CallbackTask(san, "Verify snapshot exists for LUN {0}"
                            .format(lun.lun_name),
            plugin.callback_function,
            san.san_type,
            # plugin.verify_san_exists_psl_task, san.san_type,
            san.name, san.ip_a, san.ip_b, san.username, san.password_key,
            san.login_scope, snaps,
            function_name='verify_san_exists_psl_task',
            module_name=__name__,
            tag_name=restore_snapshot_tags.VALIDATION_TAG)


def verify_san_exists_psl_task(callbackapi, san_type, sanname, ip_a, ip_b,
        username, pkey, login_scope, model_snaps):
    """
    TODO
    Verifies that all the snapshots in the model already exist in the SAN.

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type: The SAN type.
    :type san_type: :class:`str`
    :param sanname: The SAN name.
    :type sanname: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :param model_snaps: The model snaps.
    :type model_snaps: :class:`list`
    :returns: True if snaps exist.
    :rtype: :class:`boolean`
    :raises CalbackExecutionException: Raised if a snap doesn't exist.
    """

    log.event.info("ERIClitpsan: verifyspanexiststask")
    preamble = "SAN.verifysnapexiststask - "
    api = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    saninit(api, ip_a, ip_b, username, password, login_scope)
    log.trace.debug(preamble + "About to gather all snaps on SAN:"\
                    "\"{0}\"".format(sanname))
    existingsnaps = api.get_snapshots()
    sansnaps = [s.snap_name for s in existingsnaps]

    for snap in model_snaps:
        if not snap in sansnaps:
            msg = "Can't find snapshot {snap} in san {san}".format(
                snap=snap, san=sanname)
            log.trace.error(preamble + msg)
            raise CallbackExecutionException(msg)
    return True


def create_lun_snapshot_psl_task(callbackapi, san_type, ip_a, ip_b,
        username, pkey, login_scope, lun_name, snap_id):
    """
    TODO Creates a snapshot of a LUN.

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type: The SAN type.
    :type san_type: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :param lun_name: The name of the LUN.
    :type lun_name: :class:`str`
    :param snap_id: The snap ID.
    :type snap_id: :class:`str`
    :returns: True is LUN snapshot created.
    :rtype: :class:`boolean`
    :raises CallbackExecutionException: Raised if any error occurred while
        creating snapshot.
    """

    # Avoid pylint
    if not snap_id:
        log.trace.debug("snap id not set")

    snap_name = "L_" + lun_name + "_"
    log.event.info("ERIClitpsan: createlunsnap callback creating"  \
                   "snapshot \"{0}\" for LUN: \"{1}\""
                   .format(snap_name, lun_name))
    preamble = "SAN._get_snapshot_tasks "
    log.trace.debug(preamble + "action: \"create\"  snap_name: \"{0}\" " \
                    "lun_name\"{1}\"".format(snap_name, lun_name))
    result = False
    log.trace.debug(preamble + "Creating API instance for san_type " \
                    "\"{0}\"")
    san = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    log.trace.debug(preamble + "Initialising API connection to SP IPs: "
                    "\"{0}\" with user \"{1}\" ")
    saninit(san, ip_a, ip_b, username, password, login_scope)
    log.trace.debug(preamble + "Executing SAN PSL snapshot for lun: "
                    "\"{0}\" snap: \"{1}\" ")
    try:
        snapinfo = san.create_snapshot(lun_name, snap_name)
    except:
        raise CallbackExecutionException
    if snapinfo is not None:
        result = True
    return result


def restore_lun_snapshot_psl_task(callbackapi, san_type, ip_a, ip_b,
        username, pkey, login_scope, lun_name, snap_id):
    """
    TODO Restores a snapshot of a LUN.

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type: The SAN type.
    :type san_type: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :param lun_name: The name of the LUN.
    :type lun_name: :class:`str`
    :param snap_id: The snap ID.
    :type snap_id: :class:`str`
    :returns: True is LUN snapshot restored.
    :rtype: :class:`boolean`
    :raises CallbackExecutionException: Raised if any error occurred while
        restoring snapshot.
    """

    # Avoid pylint
    if not snap_id:
        log.trace.debug("snap id not set")

    snap_name = "L_" + lun_name + "_"
    log.event.info("ERIClitpsan: restorelunsnap callback restoring"  \
                   "snapshot \"{0}\" for LUN: \"{1}\""
                   .format(snap_name, lun_name))
    preamble = "SAN.restorelunsnap "
    log.trace.debug(preamble + "action: \"restore\"  snap_name: \"{0}\" " \
                    "lun_name\"{1}\"".format(snap_name, lun_name))
    log.trace.debug(preamble + "Creating API instance for san_type " \
                    "\"{0}\"".format(san_type))
    san = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    log.trace.debug(preamble + "Initialising API connection to SP IPs: "
                    "\"{0}\" with user \"{1}\" ")
    saninit(san, ip_a, ip_b, username, password, login_scope)
    log.trace.debug(preamble + "Executing SAN PSL snapshot for lun: "
                    "\"{0}\" snap: \"{1}\" ")

    # Verify the lun is ready
    _verify_the_lun_is_ready(san, lun_name, preamble)

    # The lun is ready, so proceed with the restore snapshot
    try:
        san.restore_snapshot(lun_name, snap_name, delete_backupsnap=True)
    except SanApiEntityNotFoundException:
        msg = "Snapshot " + snap_name + \
                        "does not exist on the SAN"
        log.trace.info(msg)
        raise CallbackExecutionException(msg)
    except:
        log.trace.info(traceback.format_exc())
        raise CallbackExecutionException
    return True


def _verify_the_lun_is_ready(san, lun_name, preamble):
    """
    Verify the lun is ready to execute the restore
    """
    luninfo = san.get_lun(lun_name=lun_name)
    timeout_loop = 0
    while str(luninfo.current_op) != "None" and timeout_loop < san_timeout():
        timeout_loop += 1
        log.trace.info('{pre} waiting operation {op} to finish ({secs}secs)'
            .format(pre=preamble, op=luninfo.current_op, secs=timeout_loop)
        )
        time.sleep(1)
        luninfo = san.get_lun(lun_name=lun_name)
    if timeout_loop >= san_timeout():
        msg = "SAN timeout. waiting for operation: {op} to finish".format(
            op=luninfo.current_op)
        log.trace.error("{pre} {msg}".format(pre=preamble, msg=msg))
        raise CallbackExecutionException(msg)


def remove_lun_snapshot_psl_task(callbackapi, san_type, ip_a, ip_b,
        username, pkey, login_scope, lun_name, snap_id):
    """
    TODO Removes a LUN snapshot.

    :param callbackapi: The callback API.
    :type callbackapi: :class:`str`
    :param san_type: The SAN type.
    :type san_type: :class:`str`
    :param ip_a: IP of Storage Processor A.
    :type ip_a: :class:`str`
    :param ip_b: IP of Storage Processor B.
    :type ip_b: :class:`str`
    :param username: The username used to connect.
    :type username: :class:`str`
    :param pkey: The password key.
    :type pkey: :class:`str`
    :param login_scope: The login scope.
    :type login_scope: :class:`str`
    :param lun_name: The name of the LUN.
    :type lun_name: :class:`str`
    :param snap_id: The snap ID.
    :type snap_id: :class:`str`
    :returns: True is LUN snapshot removed.
    :rtype: :class:`boolean`
    :raises CallbackExecutionException: Raised if any error occurred while
        removing snapshot.
    """

    # Avoid pylint
    if not snap_id:
        log.trace.debug("snap id not set")

    snap_name = "L_" + lun_name + "_"

    log.event.info("ERIClitpsan: removelunsnap callback removing"  \
                   "snapshot \"{0}\" for LUN: \"{1}\""
                   .format(snap_name, lun_name))
    preamble = "SAN.removelunsnap "
    log.trace.debug(preamble + "action: \"remove\"  snap_name: \"{0}\" " \
                    "lun_name\"{1}\"".format(snap_name, lun_name))
    log.trace.debug(preamble + "Creating API instance for san_type " \
                    "\"{0}\"".format(san_type))
    san = api_builder(san_type, log.trace)
    password = get_san_password(callbackapi, username, pkey)
    log.trace.debug(preamble + "Initialising API connection to SP IPs: "
                    "\"{0}\" with user \"{1}\" ")
    saninit(san, ip_a, ip_b, username, password, login_scope)
    log.trace.debug(preamble + "Executing SAN PSL snapshot for lun: "
                    "\"{0}\" snap: \"{1}\" ")

    try:
        existingsnaps = san.get_snapshots()
    except:
        raise CallbackExecutionException

    if snap_name in [s.snap_name for s in existingsnaps]:
        try:
            san.delete_snapshot(snap_name)
        except SanApiEntityNotFoundException:
            msg = "Snapshot " + snap_name + \
                            "does not exist on the SAN, this is ok."
            log.trace.info(msg)
        except:
            raise CallbackExecutionException
    else:
        msg = "Snapshot " + snap_name + " does not exist on the SAN."
        log.trace.info(msg)

    return True
