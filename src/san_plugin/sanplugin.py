##############################################################################
# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################
import re
import sys
from sanapi.sanapi import api_builder

from sanapi.sanapiexception import SanApiException, \
                                   SanApiEntityNotFoundException

from litp.core.plugin import Plugin
from litp.core.execution_manager import CallbackExecutionException
from litp.core.task import CallbackTask
from litp.plan_types.deployment_plan import deployment_plan_tags
from san_plugin.san_utils import log
from san_plugin.san_utils import using_thin_luns

# This fudge required for bootable LUNs with moore than one partition.
# See http://jira-oss.lmera.ericsson.se/browse/OSS-62390
lunSizeFudgeMegs = 4
RG_CONTAINER_TYPE = "Raid Group"
SP_CONTAINER_TYPE = "Storage Pool"
MAX_FEN_LUN_SIZE = 500
LUN_UPDATABLE_PROPERTIES = ['size']

from san_plugin import san_snapshot
from san_plugin.san_utils import normalise_to_megabytes
from san_plugin.san_utils import get_san_password
from san_plugin.san_utils import saninit
from san_plugin.san_utils import getpoolinfo
from san_plugin.san_utils import values_are_equal
from san_plugin.san_utils import get_balancing_sp
from san_plugin.san_utils import toggle_sp
from san_plugin.san_utils import get_bg
from san_plugin.san_utils import get_lun_names_for_bg
from san_plugin.san_utils import hba_port_list
from san_plugin.san_utils import get_initial_items
from san_plugin.san_utils import get_applied_items
from san_plugin.san_utils import get_san_luns
from san_plugin.san_utils import get_san_from_lun
from san_plugin.san_utils import get_ip_for_node
from san_plugin.san_utils import get_sgname
from san_plugin.san_utils import get_model_item_for_lun
from san_plugin.san_validate import SanPluginValidator
from san_plugin import san_node


class SanPlugin(Plugin):
    """
    LITP SAN plugin class inherits Plugin.

    :param Plugin: The inherited plugin class.
    :type Plugin: :class:`Plugin`
    """

    def validate_model(self, plugin_api_context):
        """
        TODO Validates the LITP model.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        """

        validator = SanPluginValidator()
        return validator.validate_model(plugin_api_context)

    def create_snapshot_plan(self, plugin_api_context):
        """
        TODO Creates the snapshot plan.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed.
        :rtype: :class:`list` of :class:`CallbackTask`
        :raises RuntimeError: Raised if an exception encountered.
        """

        # snapshot task generation temporarily disabled
        log.event.info("ERIClitpsan: create_snapshot_plan")
        try:
            # import pdb
            # pdb.set_trace()
            snap_name = plugin_api_context.snapshot_name()
            action = plugin_api_context.snapshot_action()
        except Exception as e:
            raise RuntimeError(e)
        return san_snapshot.get_tasks(self, plugin_api_context, action,
                                    snap_name)

    def create_configuration(self, plugin_api_context):
        """
        TODO Creates the configuration based on the LITP model.
        Plugin can provide tasks based on the model ...

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed.
        :rtype: :class:`list` of :class:`CallbackTask`

        *Example CLI for this plugin:*

        .. code-block:: python

            TODO Please provide an example CLI snippet for plugin san here

        """
        log.event.info("ERIClitpsan: create_configuration")
        tasks = []

        # Append Create Tasks
        pool_tasks = self._create_storage_pool_tasks(plugin_api_context)
        sg_tasks = self._create_sg_tasks(plugin_api_context)
        lun_tasks = self._create_lun_tasks(plugin_api_context)
        fen_tasks = self._create_fencing_lun_tasks(plugin_api_context)

        # Append Update Tasks
        up_lun_tasks = self._create_updated_luns_tasks(plugin_api_context)
        up_san_tasks = self._create_san_update_tasks(plugin_api_context)

        # Append Remove Tasks
        # TODO
        log.event.info("SAN Task Generation complete")

        # Node Storage Tasks
        scsi_tasks = san_node.generate_scsi_scan_hosts_tasks(self,
                                    plugin_api_context, lun_tasks)

        mpath_tasks = san_node.generate_multipath_editing_tasks(self,
                                    plugin_api_context, scsi_tasks)

        node_tasks = san_node.generate_node_tasks_after_expanding_luns(self,
            plugin_api_context, up_lun_tasks)

        hba_update_tasks = self._create_hba_update_task(plugin_api_context)

        tasks = pool_tasks + sg_tasks + lun_tasks + fen_tasks + up_lun_tasks \
                + up_san_tasks + scsi_tasks + mpath_tasks + node_tasks \
                + hba_update_tasks

        return tasks

    def _create_storage_pool_tasks(self, plugin_api_context):
        """
        Creates the task to create the SAN storage Pool.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed.
        :rtype: :class:`list` of :class:`CallbackTask`
        """
        log.event.info("ERIClitpsan: _create_pool_tasks")
        preamble = 'SAN.create_configuration: '
        tasks = []

        # Search model for enm_deployment_type
        global_prop = [prop for prop
                       in plugin_api_context.query('config-manager-property')
                       if 'enm_deployment_type' in prop.key]
        if global_prop:
            enm_dep_type = global_prop.pop()
            if ((not re.match(r'.*ENM_On_Rack_Servers$',
                              enm_dep_type.value)) or
                ('vLITP_ENM_On_Rack_Servers' == enm_dep_type.value)):
                log.event.info(preamble + 'deployment type is not \"ENM on '
                                          'Rack\". Skipping pool creation.')
                return tasks
        else:
            log.event.info(preamble + 'deployment type is not defined in the '
                                      'model. Skipping pool creation')
            return tasks

        emc_sans = plugin_api_context.query('san-emc')

        for san in emc_sans:
            for storage_container in san.storage_containers:
                if san.is_initial():
                    poolname = storage_container.name
                    number_of_disks = storage_container.number_of_disks
                    pool_raid_level = storage_container.raid_level

                    tasks.append(self._gen_storage_pool_task(san, poolname,
                                                             number_of_disks,
                                                             pool_raid_level))

        return tasks

    def _create_sg_tasks(self, plugin_api_context):
        """
        TODO Creates the storage group tasks.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed.
        :rtype: :class:`list` of :class:`CallbackTask`
        """

        log.event.info("ERIClitpsan: _create_sg_tasks")
        preamble = 'SAN.create_configuration: '
        emc_sans = plugin_api_context.query('san-emc')
        nodes = plugin_api_context.query('node')
        tasks = []

        for san in emc_sans:
            msg = "Querying SAN model items \"{0}\" ".format(san.get_vpath())
            log.trace.debug(preamble + msg)
            for node in nodes:
                msg = "Analysing Node \"{0}\"".format(node.hostname)
                log.trace.debug(preamble + msg)

                sgname = get_sgname(node, san, plugin_api_context)
                luns = get_san_luns(san, node.system.disks.query('lun-disk'))
                register_host = False

                # At least 1 LUN needs to be initial to create SG.
                # If there is any LUNs applied then we don't need to bother
                # as the SG has already been created.
                if len(get_initial_items(luns)) > 0 and \
                   len(get_applied_items(luns)) == 0:
                    msg = "Generating Task: Create Storage Group " + \
                        "for Node \"{0}\"".format(node.hostname)

                    log.trace.info(preamble + msg)
                    tasks.append(self._gen_storagegroup_task(node, san,
                                                                sgname))

                    # creating new SG so need to register host
                    register_host = True
                else:
                    msg = "No need to generate Storage Group Tasks " + \
                        "for Node \"{0}\"".format(node.hostname)
                    log.trace.debug(preamble + msg)

                # If deployed system has new HBA we need to register it
                hbas = node.system.controllers.query("hba")
                if len(get_initial_items(hbas)) > 0 and \
                   len(luns) > 0:
                    register_host = True

                if register_host == True:
                    hba_ports = hba_port_list(hbas)
                    if hba_ports:
                        msg = "Generating Task: Register-HostInit " + \
                                "for Node \"{0}\"".format(node.hostname)
                        log.trace.info(preamble + msg)

                        node_ip = get_ip_for_node(node, san.storage_network)
                        tasks.append(self._gen_registernode_task(node,
                                node_ip, san, hbas, hba_ports, sgname))

        log.event.info("SAN Create Storage Group Task Generation complete")
        return tasks

    def _create_san_update_tasks(self, plugin_api_context):
        """
        Creates the SAN tasks to change the SAN item state to applied
        following an update to any of its properties.
        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed.
        :rtype: :class:`list` of :class:`CallbackTask`
        """

        log.event.info("ERIClitpsan: _create_san_update_tasks")
        preamble = 'SAN.create_configuration: '
        tasks = []
        emc_sans = plugin_api_context.query('san-emc')

        for san in emc_sans:
            msg = "Querying SAN model item \"{0}\" ".format(san.get_vpath())
            log.trace.debug(preamble + msg)

            if san.is_updated():
                msg = "Generating Task: Update SAN properties \"{0}\"" \
                                                        .format(san.name)
                log.trace.info(preamble + msg)
                tasks.append(self._gen_update_san_task(san))
            else:
                msg = "No need to generate update SAN properties task " + \
                                        "for SAN \"{0}\"".format(san.name)
                log.trace.debug(preamble + msg)

        log.event.info("Update SAN properties task generation complete")
        return tasks

    def _create_lun_tasks(self, plugin_api_context):
        """
        TODO Creates the LUN tasks.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed.
        :rtype: :class:`list` of :class:`CallbackTask`
        """

        log.event.info("ERIClitpsan: _create_lun_tasks")

        preamble = 'SAN.create_configuration: '
        s_pool = SP_CONTAINER_TYPE
        nodes = plugin_api_context.query('node')
        tasks = []

        # Get list of initial storage processors for each
        # balancing group defined in the model
        all_luns = plugin_api_context.query('lun-disk')
        balancing_sp = get_balancing_sp(all_luns)

        previous_luns = []
        for node in nodes:
            msg = "Querying node \"{0}\" for LUNs".format(node.hostname)
            log.trace.debug(preamble + msg)

            node_luns = get_initial_items(node.system.disks.query('lun-disk'))
            for lun in node_luns:
                san = get_san_from_lun(lun, plugin_api_context)
                sgname = get_sgname(node, san, plugin_api_context)

                if lun.lun_name not in previous_luns:
                    msg = "Generating Create LUN task for " \
                        + "\"{0}\"".format(lun.lun_name) + " on node " \
                        + "\"{0}\"".format(node.hostname)
                    create = True
                    previous_luns.append(lun.lun_name)

                    # Balancing Group: we determine a default SP
                    # and a list of LUNs in same balancing group.
                    lun_bg = get_bg(lun)
                    bg_luns = get_lun_names_for_bg(all_luns, lun_bg)
                    default_sp = balancing_sp[lun_bg]
                    balancing_sp[lun_bg] = toggle_sp(default_sp)
                else:
                    msg = "Generating update LUN uuid task for " \
                        + "\"{0}\"".format(lun.lun_name) + " on node " \
                        + "\"{0}\"".format(node.hostname)
                    create = False
                    bg_luns = []
                    default_sp = 'A'

                log.event.info(preamble + msg)
                args = (node, lun, s_pool, default_sp, san, create, bg_luns)
                tasks.append(self._gen_lun_task(*args))

                msg = "Generating register LUN task for " \
                    + "\"{0}\"".format(lun.lun_name) + " on node " \
                    + "\"{0}\"".format(node.hostname)
                log.event.info(preamble + msg)
                args = (lun, s_pool, san, sgname)
                tasks.append(self._gen_registerlun_task(*args))

        log.event.info("SAN Create LUN Task Generation complete")
        return tasks

    def _create_updated_luns_tasks(self, plugin_api_context):
        """
        TODO
        Generate all needed tasks for all LUNs that have been modified.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed for updating the LUNs.
        :rtype: :class:`list` of :class:`CallbackTask`
        :raises CallBackExecutionException: Raised if the size of the LUN is
            not properly set.
        """

        log.trace.info('Creating update-lun tasks')
        emc_sans = plugin_api_context.query('san-emc')
        nodes = plugin_api_context.query('node')
        tasks = []
        luns = [lun for lun in plugin_api_context.query('lun-disk')
                               if lun.is_updated()]
        if not luns:
            return []
        # power_off_nodes = []
        # power_on_nodes = []
        for san in emc_sans:
            for storage_container in san.storage_containers:
                poolname = storage_container.name
                for node in nodes:
                    luns = node.system.disks.query('lun-disk',
                        storage_container=poolname)
                    log.trace.info('found {0} luns in san:{2} st:{1}'.format(
                        len(luns), poolname, san.name))
                    for lun in luns:
                        if lun.is_updated():
                            lun_tasks = self._gen_update_lun_tasks(lun, san,
                                    storage_container)
                            if lun_tasks:
                                tasks += lun_tasks
                            # if not node.hostname in power_on_nodes:
                            #     p_on = san_power_control.verify_power_on(
                            #         self, plugin_api_context, node, lun)
                            #     if p_on:
                            #         tasks.append(p_on)
                            #         power_on_nodes.append(node.hostname)
                            # if not node.hostname in power_off_nodes:
                            #     p_off = san_power_control.verify_power_off(
                            #         self, plugin_api_context, node, lun)
                            #     if p_off:
                            #         tasks.append(p_off)
                            #         power_off_nodes.append(node.hostname)

        return tasks

    def _create_fencing_lun_tasks(self, plugin_api_context):
        """
                TODO
        Generate all needed tasks for all fencing LUNs.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of tasks to be executed for updating the LUNs.
        :rtype: :class:`list` of :class:`CallbackTask`
        :raises CallBackExecutionException: Raised if the size of the LUN is
            not properly set.
        """

        tasks = []
        log.trace.debug("Entering _create_fencing_lun_tasks")
        preamble = 'SAN.create_configuration - fencing LUNs: '
        vcs_clusters = plugin_api_context.query('vcs-cluster')

        # Get list of initial storage processors for each
        # balancing group defined in the model
        all_luns = plugin_api_context.query('lun-disk')
        balancing_sp = get_balancing_sp(all_luns)

        for cluster in vcs_clusters:
            nodes = cluster.query('node')
            previousluns = []
            fen_luns = cluster.fencing_disks.query('lun-disk')
            for node in nodes:
                for lun in fen_luns:
                    san = get_san_from_lun(lun, plugin_api_context)
                    for storage_container in san.storage_containers:
                        if storage_container.name == lun.storage_container:
                            if storage_container.type.lower() == "pool":
                                container_type = SP_CONTAINER_TYPE
                            else:
                                container_type = RG_CONTAINER_TYPE

                    sgname = get_sgname(node, san, plugin_api_context)
                    msg = "LUN Name: \"{0}\" Pool: \"{1}\" Size: \"{2}\"" \
                          "Shared: \"{3}\"".format(lun.lun_name,
                                                lun.storage_container,
                                                lun.size, lun.shared)
                    log.trace.debug(preamble + msg)
                    if lun.is_initial():
                        if lun.lun_name not in previousluns:
                            msg = "Generating Task: Fencing LUN \"{0}\" "  \
                                  .format(lun.lun_name)
                            log.trace.debug(preamble + msg)

                            # Balancing Group: we determine a default SP
                            # and a list of LUNs in same balancing group.
                            lun_bg = get_bg(lun)
                            bg_luns = get_lun_names_for_bg(all_luns, lun_bg)
                            default_sp = balancing_sp[lun_bg]
                            balancing_sp[lun_bg] = toggle_sp(default_sp)

                            tasks.append(self._gen_lun_task(node, lun,
                                         container_type, default_sp, san,
                                         True, bg_luns))
                            previousluns.append(lun.lun_name)
                        else:
                            msg = "Generating Task: Configure UUID and " + \
                                  "register previously configured Fencing" + \
                                      "LUN \"{0}\" ".format(lun.lun_name)
                            log.trace.debug(preamble + msg)
                            default_sp = 'A'
                            bg_luns = []

                    if node.is_initial():
                        tasks.append(self._gen_registerlun_task(lun,
                                                                container_type,
                                                                san,
                                                                sgname))
        log.event.info("Fencing LUN Task Generation complete")
        return tasks

    def _get_san_password(self, context, user, passwd_key):
        """
        Gets the SAN password from the LITPCrypt Keyring.

        :param context: The context. API context of LITP model.
        :type context: :class:`str`
        :param user: The user to get the password for.
        :type password: :class:`str`
        :param passwd_key: The password key.
        :type passwd_key: :class:`str`
        """
        return get_san_password(context, user, passwd_key)

    def _get_balanced_sp(self, san, default_sp, bg_luns):
        """
        Determine the appropriate storage processor for a LUN
        to be created on.
        :param san: SAN object for SAN communications.
        :type: san: :class:`SanApi`
        :param default_sp: The default storage processor for the LUN.
        :type: default_sp: :class:`str`
        :param bg_luns: List of model LUN items in same balancing group.
        :type: bg_luns: :class:`list` of
                        :class:`litp.core.model_manager.QueryItem`
        :returns: The storage processor calculated from existing balance of
                  LUNs in same balancing group.
        :rtype: :class:`str`
        :raises Last Exception: Raises the last Exception encountered.
        """
        spa = 0
        spb = 0

        try:
            luns = san.get_luns()
        except SanApiException, e:
            msg = "Failed to get LUN Info for balancing"
            log.trace.exception(msg)
            raise CallbackExecutionException(msg + str(e))
        except:
            raise

        for lun in luns:
            if lun.name in bg_luns:
                if lun.controller == 'A':
                    spa += 1
                elif lun.controller == 'B':
                    spb += 1
        if spa > spb:
            sp = 'B'
        elif spb > spa:
            sp = 'A'
        else:
            sp = default_sp
        return sp

    def _existinglun(self, san, lun_name, lun_size, container_name,
                     lun_container_type):
        """
        Checks for an existing LUN.

        :param san: The SAN to check for the LUN on.
        :type san: :class:`str`
        :param lun_name: The name of the LUN.
        :type lun_name: :class:`str`
        :param lun_size: The size of the LUN.
        :type lun_size: :class:`str`
        :param container_name: The name of the container.
        :type container_name: :class:`str`
        :param lun_container_type: The LUN container type.
        :type lun_container_type: :class:`str`
        :returns: True if the lun name, lun size and container name are the
            same on the found LUN, if found.
        :rtype: :class:`boolean`
        :raises Last Exception: Raises the last Exception encountered.
        """

        try:
            msg = 'Looking for an existing LUN "{0}"'.format(lun_name)
            log.trace.debug(msg)
            if lun_container_type == SP_CONTAINER_TYPE:
                luninfo = san.get_lun(lun_name=lun_name, logmsg=False)
            else:
                luninfo = self._getrglun(san, lun_name, container_name)

            log.trace.debug('Modeled:: container: {0}, LUN: {1}, Size: {2}'.\
                            format(container_name, lun_name, lun_size))
            log.trace.debug('PSL:: container: {0}, LUN: {1}, Size: {2}'.\
                         format(luninfo.container, luninfo.name, luninfo.size))

            return luninfo.name == lun_name and \
                   container_name == luninfo.container

        except SanApiEntityNotFoundException, e:
            log.trace.debug('LUN "' + lun_name + '" not found - this is OK')
            return False

        except SanApiException, e:
            msg = "Failed to get LUN with name \"" + lun_name +               \
                "\" (This is not necessarily a bad thing) "
            log.trace.debug(msg + ":" + str(e))
            # raise CallbackExecutionException(msg + str(e))
            return False
        except:
            raise

    @staticmethod
    def _saninit(san, spa_ip, spb_ip, user, passwd, login_scope):
        """
        Initiates the SAN.

        :param san: The SAN.
        :type san: :class:`str`
        :param spa_ip: The storage processor IP A.
        :type spa_ip: :class:`str`
        :param spb_ip: The storage processor IP B.
        :type spb_ip: :class:`str`
        :param user: The user.
        :type user: :class:`str`
        :param passwd: The password.
        :type passwd: :class:`str`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        """
        return saninit(san, spa_ip, spb_ip, user, passwd, login_scope)

    @staticmethod
    def _createlun(san, lun_name, lun_size, lun_container,
                   lun_container_type, bootable, sp):
        """
        Creates a LUN.

        :param san: The SAN.
        :type san: :class:`str`
        :param lun_name: The name of the LUN to create.
        :type lun_name: :class:`str`
        :param lun_size: The size of the LUN to create.
        :type lun_size: :class:`str`
        :param lun_container: The container of the LUN.
        :type lun_container: :class:`str`
        :param lun_container_type: The type of the LUN container.
        :type lun_container_type: :class:`str`
        :param bootable: A boolean defining whether the LUN is bootable.
        :type bootable: :class:`boolean`
        :param sp: The storage processor.
        :type sp: :class:`str`
        :returns: The LunInfo object if created successfully.
        :rtype: :class:`LunInfo`
        :raises CallbackExecutionException: Raised if creating the LUN failed.
        """
        log.event.info("ERIClitpsan: createlun - Creating LUN {0}"
                       .format(lun_name))
        optargs = {}
        try:
            if bootable == "true":
                create_size = str(int(lun_size) + lunSizeFudgeMegs)
                log.trace.debug("Creating LUN \"{0}\" of Size \"{1}\"" +
                                 "in Pool \"{2}\" - oversized by {3}M"
                                .format(lun_name, lun_size, lun_container,
                                        lunSizeFudgeMegs))
            else:
                create_size = lun_size
                log.trace.debug("Creating LUN \"{0}\" of Size \"{1}\"" +
                                 "in Pool \"{2}\""
                                .format(lun_name, lun_size, lun_container))

            if lun_container_type == RG_CONTAINER_TYPE:
                optargs["raid_type"] = "5"
                thin_luns = False
            else:
                thin_luns = using_thin_luns()
                log.event.info("Thin LUN is set to: %s " % str(thin_luns))

            if thin_luns:
                lun_type = "thin"
            else:
                lun_type = "thick"

            luninfo = san.create_lun(lun_name, create_size,
                                     lun_container_type, lun_container, sp,
                                     lun_type=lun_type, ignore_thresholds=True,
                                     **optargs)
        except SanApiException, e:
            msg = "Failed to create LUN \"" + lun_name + "\" "
            log.trace.exception(msg)
            raise CallbackExecutionException(msg + str(e))
        except:
            raise
        return luninfo

    def _validate_existing_storage_pool(self, pool_name, desired_disk_count,
                                        desired_raid_level, san_api):
        """
        Validate the existing storage pool by comparing the expected number of
        disks and RAID level against the current number of disks and RAID
        level of the pool that already exists.

        :param pool_name: The name of the Storage Pool.
        :type pool_name: :class:`str`
        :param desired_disk_count: The expected number of disks in the pool.
        :type desired_disk_count: :class:`str`
        :param desired_raid_level: The expected RAID level of the pool.
        :type desired_raid_level: :class:`str`
        :param san_api: The SAN.
        :type san_api: :class:`str`
        :return: True if the expected values equal the existing values.
                 False if the expected values differ.
        :rtype: :class:`boolean`
        """
        try:
            pool_info = san_api.get_storage_pool(sp_name=pool_name)

            if desired_disk_count != pool_info.disks:
                log.trace.error("Existing storage pool has {0} disks, should "
                                "be {1}".format(pool_info.disks,
                                                desired_disk_count))
                return False

            if desired_raid_level != pool_info.raid:
                log.trace.error("Existing storage pool has RAID level {0}, "
                                "should be {1}".format(pool_info.raid,
                                                       desired_raid_level))
                return False
        except SanApiException:
            log.trace.exception("Failed to get storage pool information from "
                                "SAN")
            raise

        return True

    def _createsp(self, san, pool_name, disk_count, san_name, raid_level):
        """
        Creates a Storage Pool

        :param san: The SAN.
        :type san: :class:`str`
        :param pool_name: The name of the Storage Pool.
        :type pool_name: :class:`str`
        :param disk_count: The number of disks in the Storage Pool.
        :type disk_count: :class:`str`
        :param san_name: The name of the SAN.
        :type san_name: :class:`str`
        :param raid_level: The RAID level of the Storage Pool.
        :type raid_level: :class:`str`
        :returns: True if the Storage Pool was created successfully.
        :rtype: :class:`boolean`
        :raises CallbackExecutionException: Raised if Storage Pool already
            exists or fails to create.
        """
        log.trace.debug("Entering createsp with storage pool \"{0}\" "
                        "and disk count {1}".format(pool_name, disk_count))
        try:
            if san.check_storage_pool_exists(pool_name):
                if not self._validate_existing_storage_pool(pool_name,
                                                            disk_count,
                                                            raid_level, san):
                    msg = "Storage pool {0} exists with an invalid " \
                          "configuration.".format(pool_name)
                    log.trace.exception(msg)
                    raise CallbackExecutionException(msg)
                else:
                    log.event.info("Storage pool {0} exists with correct "
                                   "configuration, will re-use."
                                   .format(pool_name))
                    return True
        except SanApiException as e:
            msg = "Failed to verify if Storage pool {0} already exists."\
                .format(pool_name)
            log.trace.exception(msg)
            raise CallbackExecutionException(msg + " - " + str(e))

        try:
            log.event.info("Creating Storage Pool \"{0}\" with {1} disks on "
                           "SAN {2}".format(pool_name, disk_count, san_name))
            san.create_pool_with_disks(pool_name, disk_count, raid_level)
        except SanApiException as e:
            msg = "Failed to create Storage pool {0}.".format(pool_name)
            raise CallbackExecutionException(msg + " - " + str(e))
        return True

    def _createsg(self, san, sgname, sanname):
        """
        Creates a Storage Group.

        :param san: The SAN.
        :type san: :class:`str`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :param sanname: The name of the SAN.
        :type sanname: :class:`str`
        :returns: True if the storage group already exists.
        :rtype: :class:`boolean`
        :raises CallbackExecutionException: Raised if creating the storage
            group failed.
        """
        log.trace.debug("Entering createsg with Storage Group \"{0}\""
                       .format(sgname))
        try:
            if san.storage_group_exists(sgname):
                log.event.info("Storage group {0} already"
                       " exists. Will re-use.".format(sgname))
                return True
        except SanApiException:
            msg = "Unable to determine if SG {0} already exists. " + \
                  "Will try to create it and hope for the best." \
                  .format(sgname)
            log.trace.exception(msg)
        try:
            log.event.info("Creating Storage Group \"{0}\" on SAN \"{1}\""
                            .format(sgname, sanname))
            san.create_storage_group(sgname)
        except SanApiException as e:
            msg = 'Failed to create Storage Group'
            raise CallbackExecutionException(msg + " - " + str(e))
        return True

    @staticmethod
    def _create_host_rec(san, sgname, host_name, host_ip, hba_ports):
        """
        TODO Registers a host to a storage group.

        :param san: The SAN.
        :type san: :class:`str`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :param host_name: The host name.
        :type host_name: :class:`str`
        :param host_ip: The host IP.
        :type host_ip: :class:`str`
        :param hba_ports: A list of HBA ports.
        :type hba_ports: :class:`list`
        :returns: True if the host was registered correctly.
        :rtype: :class:`boolean`
        :raises CallbackExecutionException: Raised if registering the host
            failed.
        """

        log.event.info("ERIClitpsan: create_host_rec - Registering Host" + \
                        " %s " + "with Storage Group %s", host_name, sgname)
        preamble = "SAN.create_host_rec: "
        hbalist = san.get_hba_port_info()
        port_registered = False
        for wwpn in hba_ports:
            if wwpn:
                log.trace.debug(preamble + "SG: \"" + sgname + \
                        "\" Host: \"" + host_name + "\" \"" + \
                        host_ip + "\" WWPN: \"" + \
                        wwpn + "\"")
                init_info = [w for w in hbalist
                             if w.hbauid[24:].lower() == wwpn.lower()]
                if init_info:
                    for i in init_info:
                        log.trace.debug(preamble +
                                        "about to call create host init: "
                                        + str(i))
                        try:
                            san.create_host_initiator(sgname, host_name,
                                                      host_ip, i.hbauid,
                                                      i.spname, i.spport)
                        except SanApiException, e:
                            msg = 'Failed to register Host Initiator for'\
                                ' HOST: "{0}"  WWN: "{1}" '.format(
                                        wwpn, host_name)
                            raise CallbackExecutionException(msg + str(e))
                        port_registered = True
                else:
                    msg = "No WWN matching WWPN \"{0}\" for host " + \
                                        "\"{1}\"".format(wwpn, host_name)
                    log.event.warn(preamble + msg)
        # raise an exception if neither port a nor port b is registered
        if not port_registered:
            msg = "Neither port A nor port B of HBA could be " + \
                  "registered for host " + \
                  "\"{0}\"".format(host_name)
            log.trace.exception(preamble + msg)
            raise CallbackExecutionException(msg)
        return True

    def _registerlun(self, san, lunname, lun_container, lun_container_type,
                     bootable, sgname):
        """
        TODO Registers a LUN with a Storage Group.

        :param san: The SAN.
        :type san: :class:`str`
        :param lunname: The name of the LUN.
        :type lunname: :class:`str`
        :param lun_container: The container of the LUN.
        :type lun_container: :class:`str`
        :param lun_container_type: The type of the LUN container.
        :type lun_container_type: :class:`str`
        :param bootable: A boolean defining whether the LUN is bootable.
        :type bootable: :class:`boolean`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :returns: True if the LUn was registered successfully.
        :rtype: :class:`boolean`
        :raises CallbackExecutionException: Raised if registering the LUN
            failed for any reason.
        """
        log.event.info("ERIClitpsan: registerlun - Registering LUN \"%s\" " +
                       "with Storage Group \"%s\"", lunname, sgname)
        preamble = "ERIClitpssan: _registerlun - \"" + lunname + "\": "
        log.trace.debug(preamble + " properties: SG:\"" + sgname +
                                             "\" boot:\"" + bootable)

        # get storage group
        try:
            sginfo = san.get_storage_group(sgname)
        except SanApiException, e:
            msg = "Failed to get Storage Group Info for " + sgname
            log.trace.exception(msg)
            raise CallbackExecutionException(msg + str(e))
        except:
            raise

        log.trace.debug(preamble + "Retrieved Storage Group: \"{0}\""
                        .format(sgname))
        # get lun for its ALU
        try:
            if lun_container_type == SP_CONTAINER_TYPE:
                lun = san.get_lun(lun_name=lunname)
            else:
                lun = self._getrglun(san, lunname, lun_container)
            alu = lun.id
        except SanApiException, e:
            msg = "Failed to get LUN Info for \"{0}\""   \
                   .format(lunname)
            log.trace.exception(msg)
            raise CallbackExecutionException(msg + str(e))
        except:
            raise
        log.trace.debug(preamble + "Retrieved LUN with ALU \"{0}\""
                        .format(alu))

        # Now we can see if the LUN is registered, and if it is, we need to
        # get the HLU which we'll later test to see if it matches what is in
        # the model
        hlu = None
        if sginfo.hlualu_list is not None:
            for hlualu in sginfo.hlualu_list:
                if alu == hlualu.alu:
                    hlu = hlualu.hlu
                    break

        # LUN is registered already
        if hlu is not None:
            log.trace.debug(preamble + "LUN already registered with HLU:" + \
                            "\"{0}\" ALU: \"{1}\"".format(hlu, alu))

            # The LUN is already registered.  Now verify that its
            # 'bootability' matches what we are trying to register
            if bootable == "true":
                if hlu == "0":
                    log.trace.debug(preamble +
                                   "Bootable LUN already registered")
                    return True
                else:
                    msg = "Bootable LUN already registered as non-bootable"
                    log.trace.exception(preamble + msg)
                    raise CallbackExecutionException(msg)

            # bootable is false
            else:
                if hlu != "0":
                    log.trace.debug(preamble +
                                   "Non-bootable LUN already registered")

                    return True
                else:
                    # non-bootable LUN already registered as bootable LUN
                    msg = "Non-bootable LUN already registered as bootable"
                    log.trace.exception(preamble + msg)
                    raise CallbackExecutionException(msg)

        # Need to register LUN
        else:
            log.trace.debug(preamble +
                             "LUN is not registered, need to register")

            if bootable == "true":
                log.trace.debug(preamble + "Need to register bootable LUN")
                hlu = "0"
            else:
                log.trace.debug(preamble + "Need to register non-bootable LUN")
                hlu = self._get_next_hlu(san, sgname)

            try:
                san.add_lun_to_storage_group(sgname, hlu, alu)
            except:
                msg = "Failed to register LUN with storage group"
                log.trace.exception(preamble + msg)
                raise CallbackExecutionException(msg)

            log.trace.debug(preamble + "LUN registered with HLU: \"{0}\"" + \
                            "ALU \"{1}\"".format(hlu, alu))
            return True

    @staticmethod
    def _get_next_hlu(san, sgname):
        """
        TODO Gets the next HLU on a storage group.

        :params san: The SAN.
        :type san: :class:`str`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :returns: The next HLU.
        :rtype: :class:`str`
        :raises Something: What does this raise?
        """
        hlu = 1
        try:
            sginfo = san.get_storage_group(sgname)
            if sginfo.hlualu_list is not None:
                hlu = str(int(sginfo.hlualu_list[-1].hlu) + 1)
        except:
            raise
        return hlu

    @staticmethod
    def _getpoolinfo(san, lun_container):
        """
        TODO Gets the pool info for a

        :param san: The SAN.
        :type san: :class:`str`
        :param lun_container: The LUN container.
        :type lun_container: :class:`str`
        :returns: The pool info.
        :rtype: :class:`str`
        """

        return getpoolinfo(san, lun_container)

    @staticmethod
    def _normalise_to_megabytes(size):
        """
        TODO Normalises the given size into megabytes.

        :param size: The size to normalise.
        :type size: :class:`str` or :class:`int`
        :returns: The result of the normalisation of the given size.
        :rtype: :class:`str`
        """
        return normalise_to_megabytes(size)

    def _gen_lun_task(self, node, lun, lun_container_type, default_sp,
                                                san, create, bg_luns):

        """
        TODO Gets a LUN task.

        :param node: The node.
        :type node: :class:`str`
        :param lun: The LUN.
        :type lun: :class:`str`
        :param lun_container_type: The LUN container type.
        :type lun_container_type: :class:`str`
        :param default_sp: The default storage processor.
        :type default_sp: :class:`str`
        :param san: The SAN.
        :type san: :class:`str`
        :param create:
        :type create: :class:`str`
        :returns: The task.
        :rtype: :class:`CallbackTask`
        """

        model_item = lun.get_source()
        if model_item is None:
            model_item = san

        task = CallbackTask(model_item,
                         "Creating LUN \"{0}\" for Node \"{1}\""
                          .format(lun.lun_name, node.hostname),
                          self.create_lun_cb_task,
                          san.san_type,
                          lun.lun_name,
                          lun.storage_container,
                          lun_container_type,
                          self._normalise_to_megabytes(lun.size),
                          lun.bootable,
                          #lun.shared,
                          san.ip_a,
                          san.ip_b,
                          san.username,
                          san.password_key,
                          create,
                          san.login_scope,
                          default_sp,
                          bg_luns
        )
        task.model_items.add(san)
        task.model_items.add(lun)
        return task

    def _gen_storage_pool_task(self, san, pool_name, disk_count, raid_level):
        """
        Generates a Storage Pool task.

        :param san: The SAN.
        :type san: :class:`str`
        :param pool_name: The name of the SAN Storage Pool.
        :type pool_name: :class:`str`
        :param disk_count:
        :type disk_count: :class:`str`
        :param raid_level:
        :type raid_level: :class:`str`
        :return: The task to generate to Storage Pool.
        :rtype: :class:`CallbackTask`
        """
        task = CallbackTask(san.storage_containers,
                            "Creating Storage Pool \"{0}\" with {1} disks"
                            .format(pool_name, disk_count),
                            self.create_storagepool_cb_task,
                            san.san_type,
                            san.name,
                            san.ip_a,
                            san.ip_b,
                            san.username,
                            san.password_key,
                            san.login_scope,
                            pool_name,
                            disk_count,
                            raid_level)

        task.model_items.add(san)
        return task

    def _gen_storagegroup_task(self, node, san, sgname):
        """
        TODO Generates a storage group task.

        :param node: The node.
        :type node: :class:`str`
        :param san: The SAN.
        :type san: :class:`str`
        :param sg_name: The storage group name.
        :type sg_name: :class:`str`
        :returns: The task.
        :rtype: :class:`CallbackTask`
        """

        task = CallbackTask(node.system.get_source(),
                        "Creating StorageGroup \"{0}\" for Node \"{1}\""
                        .format(sgname, node.hostname),
                        self.create_sg_cb_task,
                        san.san_type,
                        san.name,
                        sgname,
                        san.ip_a,
                        san.ip_b,
                        san.username,
                        san.password_key,
                        san.login_scope
        )
        task.model_items.add(san)
        return task

    def _gen_update_san_task(self, san):
        """
        TODO Generates an update SAN task.

        :param san: The SAN.
        :type san: :class:`str`
        :returns: The task.
        :rtype: :class:`CallbackTask`
        """
        task = CallbackTask(san,
                        "Updating SAN \"{0}\""
                        .format(san.name),
                        self.update_san_cb_task,
                        san.name,
        )
        task.model_items.add(san)
        return task

    def _gen_registernode_task(self, node, node_ip, san, hbas,
            hba_ports, sgname):
        """
        TODO Generates the task to register a node.

        :param node: The node.
        :type node: :class:`str`
        :param node_ip: The node IP.
        :type node_ip: :class:`str`
        :param san: The SAN.
        :type san: :class:`str`
        :param hbas: A list of HBAs.
        :type hbas: :class:`list`
        :param hba_ports: A list of HBA ports.
        :type hba_ports: :class:`list`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :returns: The task.
        :rtype: :class:`CallbackTask`
        """

        task = CallbackTask(node.system.get_source(),
                        "Registering Host Initiator for Node \"{0}\" in"
                            " Storage Group \"{1}\""
                        .format(node.hostname, sgname),
                        self.create_hostinit_cb_task,
                        san.san_type,
                        sgname,
                        san.ip_a,
                        san.ip_b,
                        node_ip,
                        node.hostname,
                        hba_ports,
                        san.username,
                        san.password_key,
                        san.login_scope
        )
        task.model_items.add(san)
        for hba in hbas:
            task.model_items.add(hba)
        return task

    def _gen_registerlun_task(self, lun, lun_container_type, san, sgname):
        """
        TODO Generates the taks to register a LUN.

        :param lun: The LUN to register.
        :type lun: :class:`str`
        :param lun_container_type: The LUN container type.
        :type lun_container_type: :class:`str`
        :param san: The SAN.
        :type san: :class:`str`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :returns: The task.
        :rtype: :class:`CallbackTask`
        """
        model_item = lun.get_source()
        if model_item is None:
            model_item = san
        task = CallbackTask(model_item,
                        "Registering LUN \"{0}\" in Storage Group \"{1}\""
                        .format(lun.lun_name, sgname),
                        self.create_reglun_cb_task,
                        san.san_type,
                        sgname,
                        san.ip_a,
                        san.ip_b,
                        lun.lun_name,
                        lun.storage_container,
                        lun_container_type,
                        lun.bootable,
                        san.username,
                        san.password_key,
                        san.login_scope
        )
        task.model_items.add(san)
        task.model_items.add(lun)
        return task

    def create_storagepool_cb_task(self, callbackapi, san_type, san_name,
                                   spa_ip, spb_ip, user, passwd_key,
                                   login_scope, pool_name, disk_count,
                                   raid_level):
        """
        Create the Storage Pool.

        :param callbackapi: The callback API.
        :type callbackapi: :class:`str`
        :param san_type: The SAN API.
        :type san_type: :class:`str`
        :param san_name: The name of the SAN.
        :type san_name: :class:`str`
        :param spa_ip: The IP for storage pool A.
        :type spa_ip: :class:`str`
        :param spb_ip: The IP for storage pool B.
        :type spb_ip: :class:`str`
        :param user: The user to connect to the SAN.
        :type user: :class:`str`
        :param passwd_key: The password key
        :type passwd_key: :class:`str`
        :param login_scope: The login scope
        :type login_scope: :class:`str`
        :param pool_name: The SAN Storage Pool name.
        :type pool_name: :class:`str`
        :param disk_count: The number of disks in the Storage Pool.
        :type disk_count: :class:`str`
        :param raid_level: The RAID level of the Storage Pool.
        :type raid_level: :class:`str`

        """
        preamble = "SAN.create_storagepool_cb_task: {0}".format(pool_name)
        log.trace.debug(preamble + " about to try storage pool creation")
        san = api_builder(san_type, log.trace)
        password = self._get_san_password(callbackapi, user, passwd_key)
        self._saninit(san, spa_ip, spb_ip, user, password, login_scope)
        log.trace.debug(preamble + " SAN API Connection init")
        self._createsp(san, pool_name, disk_count, san_name, raid_level)
        return True

    def create_sg_cb_task(self, callbackapi, san_type, sanname, sgname,
                          spa_ip, spb_ip, user, passwd_key, login_scope):
        """
        TODO Create Storage Group

        :param callbackapi:
        :type callbackapi: :class:`str`
        :param san_type: The type of SAN.
        :type san_type: :class:`str`
        :param sanname: The name of the SAN.
        :type sanname: :class:`str`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :param spa_ip: The IP for storage pool A.
        :type spa_ip: :class:`str`
        :param spb_ip: The IP for storage pool B.
        :type spb_ip: :class:`str`
        :param user: The user used to connect.
        :type user: :class:`str`
        :param passwd_key: The password key.
        :type passwd_key: :class:`str`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        :returns: True. just returns true? No raising of exceptions?
        :rtype: :class:`boolean`
        """

        preamble = "SAN.create_sg_cb_task: \"" + sgname + "\" : "
        log.trace.debug(preamble + " about to try SG creation")
        san = api_builder(san_type, log.trace)
        password = self._get_san_password(callbackapi, user, passwd_key)
        self._saninit(san, spa_ip, spb_ip, user, password, login_scope)
        log.trace.debug(preamble + " SAN API Connection init")
        self._createsg(san, sgname, sanname)
        return True

    def create_hostinit_cb_task(self, callbackapi, san_type, sgname, spa_ip,
                                spb_ip, host_ip, host_name, hba_ports, user,
                                passwd_key, login_scope):
        """
        TODO Create Host Initiator Record

        :param callbackapi:
        :type callbackapi: :class:`str`
        :param san_type: The type of SAN.
        :type san_type: :class:`str`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :param spa_ip: The IP for storage pool A.
        :type spa_ip: :class:`str`
        :param spb_ip: The IP for storage pool B.
        :type spb_ip: :class:`str`
        :param host_ip: The host IP.
        :type host_ip: :class:`str`
        :param host_name: The host name.
        :type host_name: :class:`str`
        :param hba_ports: A list of the HBA ports.
        :type hba_ports: :class:`list`
        :param user: The user used to connect.
        :type user: :class:`str`
        :param passwd_key: The password key.
        :type passwd_key: :class:`str`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        :returns: True. just returns true? No raising of exceptions?
        :rtype: :class:`boolean`
        """
        preamble = "SAN.create_hostinit_cb_task: \"" + sgname + "\" : "
        log.trace.debug(preamble + " about to try create HostInit")
        san = api_builder(san_type, log.trace)
        password = self._get_san_password(callbackapi, user, passwd_key)
        self._saninit(san, spa_ip, spb_ip, user, password, login_scope)
        log.trace.debug(preamble + ' SAN API Connection init')
        self._create_host_rec(san, sgname, host_name, host_ip, hba_ports)
        return True

    def create_reglun_cb_task(self, callbackapi, san_type, sgname, spa_ip,
                              spb_ip, lun_name, lun_container,
                              lun_container_type, bootable, user, passwd_key,
                              login_scope):
        """
        TODO Register LUN

        :param callbackapi:
        :type callbackapi: :class:`str`
        :param san_type: The type of SAN.
        :type san_type: :class:`str`
        :param sgname: The storage group name.
        :type sgname: :class:`str`
        :param spa_ip: The IP for storage pool A.
        :type spa_ip: :class:`str`
        :param spb_ip: The IP for storage pool B.
        :type spb_ip: :class:`str`
        :param lun_name: The LUN name.
        :type lun_name: :class:`str`
        :param lun_container: The LUN container.
        :type lun_container: :class:`str`
        :param lun_container_type: The LUN container type.
        :type lun_container_type: :class:`str`
        :param bootable: A boolean defining whether the LUN is bootable.
        :type bootable: :class:`boolean`
        :param user: The user used to connect.
        :type user: :class:`str`
        :param passwd_key: The password key.
        :type passwd_key: :class:`str`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        :returns: True. just returns true? No raising of exceptions?
        :rtype: :class:`boolean`
        """
        preamble = "SAN.register_lun_cb_task: \"" + sgname + "\" : "
        log.trace.debug(preamble + " about to try LUN registration")
        san = api_builder(san_type, log.trace)
        password = self._get_san_password(callbackapi, user, passwd_key)
        self._saninit(san, spa_ip, spb_ip, user, password, login_scope)
        log.trace.debug(preamble + ' SAN API Connection init')

        self._registerlun(san, lun_name, lun_container,
                          lun_container_type, bootable, sgname)
        return True

    @staticmethod
    def _getrglun(san, lun_name, rg_id):
        """
        TODO
        Returns LunInfo Object of LUN matching
        supplied Raid Group ID and name
        Assumes PSL already initialised

        :param lun_name: The LUN name.
        :type lun_name: :class:`str`
        :param rg_id: The RAID group ID.
        :type rg_id: :class:`str`
        :returns: A LunInfo object of the matching LUN.
        :rtype: :class:`LunInfo`
        :raises SanApiEntityNotFoundException: Raised if the Raid Group Lun
            with the given name not found.
        """
        luninfos = san.get_luns(container_type="RaidGroup",
                                container=str(rg_id))
        for luninfo in luninfos:
            if luninfo.name == lun_name:
                return luninfo
        msg = "RG LUN with name " + lun_name + " in RG " + \
              str(rg_id) + " not found"
        raise SanApiEntityNotFoundException(msg, "1")

    def create_lun_cb_task(self, callbackapi, san_type, lun_name,
                           lun_container, lun_container_type, lun_size,
                           bootable, spa_ip, spb_ip, user, passwd_key,
                           create, login_scope, default_sp, bg_luns):
        """
        TODO
        Create the LUN
        This method encapsulates the primary steps in creating a LUN.
        It is this method that calls the SAN PSL methods that will
        instantiate the connection to the SAN, enumerate the existing
        LUNs and if the LUN to be created does not already exist
        will create the LUN.
        Some implicit behaviour is handled by the SAN rather than
        validated in this method.
        Examples:
        - We do not check that there is sufficient space in a container, since
        the SAN PSL will raise an appropriate exception on failure.
        - We do not confirm that the LUN to be created has a name that is
        unique. If a LUN with the same name & size is found in the same
        container, we assume that this is the correct LUN, otherwise, we let
        the PSL handle the exception.

        :param callbackapi:
        :type callbackapi: :class:`str`
        :param san_type: The type of SAN.
        :type san_type: :class:`str`
        :param lun_name: The LUN name.
        :type lun_name: :class:`str`
        :param lun_container: The LUN container.
        :type lun_container: :class:`str`
        :param lun_container_type: The LUN container type.
        :type lun_container_type: :class:`str`
        :param lun_size: The LUN size.
        :type lun_size: :class:`str`
        :param bootable: A boolean defining whether the LUN is bootable.
        :type bootable: :class:`boolean`
        :param spa_ip: The IP for storage pool A.
        :type spa_ip: :class:`str`
        :param spb_ip: The IP for storage pool B.
        :type spb_ip: :class:`str`
        :param user: The user used to connect.
        :type user: :class:`str`
        :param passwd_key: The password key.
        :type passwd_key: :class:`str`
        :param create:
        :type create: :class:`boolean`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        :param default_sp: The default storage processor to assign to.
        :type default_sp: :class:`str`
        :param bg_luns: list of LUN names in this LUN's balancing group.
        :type bg_luns: :class:`list` of :class:`str`
        :returns: Nothing
        :rtype: None
        """
        preamble = "SAN.create_lun_cb_task: \"" + lun_name + "\" : "
        log.trace.debug(preamble + " about to try creation")
        san = api_builder(san_type, log.trace)
        password = self._get_san_password(callbackapi, user, passwd_key)
        self._saninit(san, spa_ip, spb_ip, user, password, login_scope)
        log.trace.debug(preamble + ' SAN API Connection init')

        if self._existinglun(san, lun_name, lun_size,
                                 lun_container, lun_container_type):
            log.trace.debug(preamble + "Matching LUN found... assuming this " +
                             " is what we want - nothing more to do.")
            if lun_container_type == SP_CONTAINER_TYPE:
                lun = san.get_lun(lun_name=lun_name)
            else:
                lun = self._getrglun(san, lun_name, lun_container)

        else:
            log.trace.debug("Didn't find LUN \"{0}\"".format(lun_name))
            if create:
                sp = self._get_balanced_sp(san, default_sp, bg_luns)
                lun = self._createlun(san, lun_name, lun_size, lun_container,
                                      lun_container_type, bootable, sp)
            else:
                if lun_container_type == SP_CONTAINER_TYPE:
                    lun = san.get_lun(lun_name=lun_name)
                else:
                    lun = self._getrglun(san, lun_name, lun_container)

        self.rewrite_lun_uuid(callbackapi, lun_name, lun.uid)
        return

    def rewrite_lun_uuid(self, callbackapi, lun_name, lun_uid):
        """
        Rewrite LUN UUID
        :param callbackapi: Callback API context
        :type callbackapi: CallbackApi
        :param lun_name: LUN name
        :type lun_name: string
        :param lun_uid: Original LUN uid
        :type lun_uid: string
        """

        strip_char = ":"
        translated = lun_uid.translate(None, strip_char)

        qluns = callbackapi.query("lun-disk", lun_name=lun_name)
        for qlun in qluns:
            log.trace.debug("Updating uuid of LUN %s from %s => %s" %
                            (qlun.lun_name, qlun.uuid, translated))
            qlun.uuid = translated

    def _get_sanapi(self, san_type, log_trace):
        """
        TODO Gets the SAN API.

        :param san_type: The SAN type.
        :type san_type: :class:`str`
        :param log_trace: The log trace.
        :type log_trace: :class:`str`
        :returns: The SAN API.`
        :rtype: :class:`str`
        """
        return api_builder(san_type, log_trace)

    def get_lun_real_size(self, callbackapi, sanapi, ip_a, ip_b,
        lunname, username, pkey, login_scope):
        """
        TODO
        Gets the real size of a lun (as reported by the size).

        .. note::

            You should subtract 1 if the LUN is bootable.

        :param callbackapi: The callback API.
        :type callbackapi: :class:`str`
        :param sanapi: The SAN API.
        :type sanapi: :class:`str`
        :param ip_a: The IP of A
        :type ip_a: :class:`str`
        :param ip_b: The IP of B
        :type ip_b: :class:`str`
        :param lunname: The name of the LUN.
        :type lunname: :class:`str`
        :param username: The username.
        :type username: :class:`str`
        :param pkey: The password key.
        :type pkey: :class:`str`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        """

        password = self._get_san_password(callbackapi, username, pkey)
        self._saninit(sanapi, ip_a, ip_b, username, password, login_scope)
        luninfo = sanapi.get_lun(lun_name=lunname)
        return luninfo.size

    def update_lun_task(self, callbackapi, lunname, bootable, santype,
        ip_a, ip_b, old_value, new_value, _property, username, pkey,
                        login_scope):
        """
        TODO Updates a LUN task.

        :param callbackapi: The callback API.
        :type callbackapi: :class:`str`
        :param lunname: The LUN name.
        :type lunname: :class:`str`
        :param bootable: A boolean defining whether the LUN is bootable.
        :type bootable: :class:`boolean`
        :param santype: The type of SAN.
        :type santype: :class:`str`
        :param sanname: The name of the SAN.
        :type sanname: :class:`str`
        :param ip_a: The IP of A
        :type ip_a: :class:`str`
        :param ip_b: The IP of B
        :type ip_b: :class:`str`
        :param storage_containername: The storage container name.
        :type storage_containername: :class:`str`
        :param old_value: The old value of the param being updated.
        :type old_value: :class:`str`
        :param new_value: The new value of the param being updated.
        :type new_value: :class:`str`
        :param _property: The property to update.
        :type _property: :class:`str`
        :param username: The username.
        :type username: :class:`str`
        :param pkey: The password key.
        :type pkey: :class:`str`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        """

        if _property == "size":
            self.update_lun_size(callbackapi, lunname, bootable, santype,
                ip_a, ip_b, old_value, new_value, username, pkey, login_scope)
        else:
            log.trace.info('Update lun {lunname}:{prop} from {old} to {new}'
                    .format(lunname=lunname, prop=_property, old=old_value,
                            new=new_value))

    def update_lun_size(self, callbackapi, lunname, bootable, santype,
        ip_a, ip_b, old_value, new_value, username, pkey, login_scope):
        """
        TODO:
        Verify if the LUN requires expansion ( size in the model changed )
        as OSS-85366 just check if the real size matches the model size
        to verify if the manual procedure for manual expansion was done.
        Otherwise raise an error.
        TODO: Logic must be changed as soon as the plugin takes care of
        real LUN expansion.

        :param callbackapi: The callback API.
        :type callbackapi: :class:`str`
        :param lun_name: The LUN name.
        :type lun_name: :class:`str`
        :param bootable: A boolean defining whether LUN is bootable.
        :type bootable: :class:`boolean`
        :param santype: The type of SAN.
        :type santype: :class:`str`
        :param sanname: The name of the SAN.
        :type sanname: :class:`str`
        :param ip_a: The IP of A
        :type ip_a: :class:`str`
        :param ip_b: The IP of B
        :type ip_b: :class:`str`
        :param storage_containername: The storage container name.
        :type storage_containername: :class:`str`
        :param old_value: The old value of the param being updated.
        :type old_value: :class:`str`
        :param new_value: The new value of the param being updated.
        :type new_value: :class:`str`
        :param username: The username.
        :type username: :class:`str`
        :param pkey: The password key.
        :type pkey: :class:`str`
        :param login_scope: The login scope.
        :type login_scope: :class:`str`
        """

        if bootable:
            pass

        api = self._get_sanapi(santype, log.trace)
        real_size = self.get_lun_real_size(callbackapi, api, ip_a, ip_b,
            lunname, username, pkey, login_scope)

        ireal_size = int(real_size) - 1 if bootable else int(real_size)
        iold_size = int(self._normalise_to_megabytes(old_value))
        inew_size = int(self._normalise_to_megabytes(new_value))

        msg = "LUN sizes: real:{real} new:{new} old:{old}".format(
            real=ireal_size, new=inew_size, old=iold_size)
        log.trace.debug(msg)
        if ireal_size == inew_size:
            msg = 'lun {lun_name} wanted size {new} actual size {real}'.format(
                  lun_name=lunname, real=ireal_size, new=inew_size)
        elif ireal_size < inew_size:
            if ireal_size > iold_size:
                msg = 'Resizing lun {lun_name} from {real} to {new}'.format(
                    lun_name=lunname, real=ireal_size, new=inew_size)
                api.expand_pool_lun(lunname, str(inew_size))
            elif ireal_size == iold_size:
                msg = 'Resizing lun {lun_name} from {old} to {new}'.format(
                    lun_name=lunname, old=iold_size, new=inew_size)
                api.expand_pool_lun(lunname, str(inew_size))
            else:  # real_size > old_size
                msg = ('The new real size of the lun {lun_name} does not match'
                       ' the current size in the litp model {real} != '
                       '{new}').format(
                            lun_name=lunname, real=ireal_size, new=inew_size)
                raise CallbackExecutionException(msg)
        else:  # real_size > new_size
            msg = ('New real size of lun {lunname} is bigger than '
                   'new size set in the model {realsize} > {newsize}').format(
                    lunname=lunname, realsize=ireal_size, newsize=inew_size)
            log.trace.info(msg)
            raise CallbackExecutionException(msg)
        log.trace.info(msg)

    def _gen_update_lun_tasks(self, lun, san, storage_container):
        """
        TODO Generate updated LUN tasks

        :param lun: The LUN for which the tasks are generated.
        :type lun: :class:`str`
        :param san: The SAN on which the LUN resides.
        :type san: :class:`str`
        :param storage_container: The storage container. CHECL
        :type storage_container: :class:`str`
        :returns: The list of updated tasks.
        :rtype: :class:`list` of :class:`CallbackTask`
        """

        tasks = []
        for _property in LUN_UPDATABLE_PROPERTIES:
            if _property in lun.applied_properties:
                new_value = getattr(lun, _property)
                old_value = lun.applied_properties[_property]
                if not values_are_equal(old_value, new_value):
                    bootable = lun.bootable == "true"
                    msg = ('Update {prop} for lun {lun_name} in '
                            'storage: {storage_name}/{san_name} from '
                            '{old_value} to {new_value}').format(
                                    prop=_property,
                                    lun_name=lun.lun_name,
                                    storage_name=storage_container.name,
                                    san_name=san.name,
                                    new_value=new_value,
                                    old_value=old_value)
                    log.trace.info(msg)
                    task_model_item = get_model_item_for_lun(lun)
                    task = CallbackTask(task_model_item, msg,
                        self.update_lun_task, lun.lun_name, bootable,
                                san.san_type, san.ip_a, san.ip_b,
                                old_value, new_value,
                                _property, san.username, san.password_key,
                                san.login_scope)
                    if task_model_item.item_type_id != "lun-disk":
                        task.tag_name = \
                            deployment_plan_tags.PRE_NODE_CLUSTER_TAG
                        task.model_items.add(lun)
                    tasks.append(task)

        return tasks

    def update_san_cb_task(self, cbapi, sanname):  # pylint: disable=W0613
        """
        TODO Dummy task to allow updated SAN item to become 'Applied'
        :param callbackapi:
        :type callbackapi: :class:`str`
        :param sanname: The name of the SAN.
        :type sanname: :class:`str`
        :returns: True.
        :rtype: :class:`boolean`
        """
        preamble = "SAN.update_san_cb_task : "
        log.trace.debug(preamble + "Setting SAN \"{0}\" properties to applied"
                                                        .format(sanname))
        return True

    def callback_function(self, *args, **kwargs):
        """
        TODO
        Generates a callbacktask defined into a module.
        This call is needed to ensure the callbackapi argument is properly
        set by LITP.
        in the named arguments MUST be present following arguments:
        - module_name : A string with the full name of the module where The
          callback is defined
        - function_name : a string with the name of the function to be used
          as the callback

        See :var:`san_plugin.san_power_control.gen_power_on_task` to get an
          example how it works

        :param args: The arguments list for the PSL callback task.
        :type args: :class:`list`

        :param kwargs: The dict containing key-value pairs for the task.
        :type kwargs: :class:`dict`
        :returns: a callback
        :rtype: :class:`object`

        """
        func_name = kwargs['function_name']
        module_name = kwargs['module_name']

        callback_func = sys.modules[module_name].__dict__[func_name]
        del kwargs['function_name']
        del kwargs['module_name']
        return callback_func(*args, **kwargs)

    def _create_hba_update_task(self, plugin_api_context):
        """
        Create HBA WWN update tasks.
        This is currently a manual procedure, so for any HBAs that are
        updated, generate a dummy task to ensure the value is saved to the
        LITP model.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        """
        log.event.info("ERIClitpsan: entering _create_hba_update_task")
        hbas = plugin_api_context.query('hba')
        tasks = []

        for hba in hbas:
            if hba.is_updated() and hba.hba_porta_wwn and (hba.hba_porta_wwn
            != hba.applied_properties.get('hba_porta_wwn')):
                task = CallbackTask(hba, "Task to update HBA WWPN details",
                self._update_hba)
                tasks.append(task)
            if hba.is_updated() and hba.hba_portb_wwn and (hba.hba_portb_wwn
            != hba.applied_properties.get('hba_portb_wwn')):
                task = CallbackTask(hba, "Task to update HBA WWPN details",
                self._update_hba)
                tasks.append(task)

        return tasks

    def _update_hba(self, plugin_api_context):
        """
        This is a dummy task in order to ensure that the HBA item is marked as
        applied in the LITP model.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        """
        pass
