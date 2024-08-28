##############################################################################
# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

#from litp.core.plugin import Plugin
from litp.core.litp_logging import LitpLogger
from litp.core.validators import ValidationError

log = LitpLogger()

# This fudge required for bootable LUNs with moore than one partition.
# See http://jira-oss.lmera.ericsson.se/browse/OSS-62390
MAX_FEN_LUN_SIZE = 500
LUN_SIZE_UPDATE_THRESHOLD_PERCENT = 1
LUN_UPDATABLE_PROPERTIES = ['size', 'snap_size', 'external_snap', 'uuid']

from san_plugin.san_utils import normalise_to_megabytes
from san_plugin.san_utils import get_updated_items


class SanPluginValidator(object):
    """
    LITP SAN plugin validator.

    :param object: An object.
    :type object: :class:`object`
    """

    def validate_model(self, plugin_api_context):
        """
        This method is used to validate the model.
        The following checks are performed:
        - check that at least one storage container(pool) is defined per SAN.
        - check non-shared lun-disks have unique name in a SAN.
        - check lun-disks with same name are not marked shared and non-shared.
        - check that shared LUNs have the same properties across nodes.
        - check lun-disks are in storage container defined in a SAN.
        - for bootable lun-disks check:
             - LUN not also shared.
        - check storage network in SAN definitions is among the networks
            defined for the MS
        - check that each node has at least one HBA port defined.
        - Check that for each san, either ip a or ip b is defined.
        - Check that fencing disks are defined in a valid Raid Group.
        - Check that the lun names of fencing disks are not duplicated.
        - Check that the fencing LUNs are a valid size.
        - Check that the fencing LUNs are shared not bootable.

        update validation
        - new_size of the lun must be bigger than old size.
        - All shared luns share same size values after update.
        - Check that there is no snaps in luns that are about to be expanded
        - Only the size could be modified in update.

        :param plugin_api_context: LITP model representation.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of ValidationError objects. If the list is empty the
            model validation succeeds for the SAN Plugin.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.event.info("SAN Model Validation")

        errors = []
        emc_sans = plugin_api_context.query('san-emc')
        if len(emc_sans) > 0:
            log.trace.debug("Validating SAN related information in model")
            # only perform validation if we have san(s)
            nodes = plugin_api_context.query('node')
            snapshots = plugin_api_context.query('snapshot-base')
            errors += self._check_san_details(emc_sans)
            errors += self._check_storage_container(emc_sans)
            errors += self._check_luns_in_valid_container(emc_sans, nodes)
            errors += self._check_duplicate_lun_names(emc_sans, nodes)
            errors += self._check_bootable_luns(emc_sans, nodes)
            errors += self._check_shared_luns_identical(nodes)
            errors += self._check_san_accessible_from_ms(plugin_api_context)
            errors += self._check_hba_ports(nodes)
            #errors += self._check_valid_rgs(nodes)
            #errors += self._check_fen_luns_valid_rg(plugin_api_context)
            errors += self._check_fen_luns_duplicate_names(plugin_api_context)
            errors += self._check_fen_luns_valid_size(plugin_api_context)
            errors += self._check_fen_luns_shared_not_bootable(
                                                           plugin_api_context)
            # update validation
            errors += self._check_updated_luns_right_size(nodes)
            errors += self._check_snaps_in_lun_expansion(snapshots, nodes)
            errors += self._check_valid_lun_updates(nodes)
            errors += self._check_updated_luns_new_size_too_small(nodes)
            log.trace.debug("Number of SAN Plugin validation errors: %d"
                         % len(errors))
            for error in errors:
                log.trace.debug("%s" % error.error_message)
        else:
            log.trace.debug("No SAN defined in model" +
                            " - skipping SAN validation")

        return errors

    def _check_updated_luns_right_size(self, nodes):
        """
        This function checks that the new size updated to a LUN must be bigger
        than the previous size of the LUN.

        :param nodes: A list of managed node objects from model.
        :type nodes: :class:`list`
        :returns: A list of ValidationError objects.
        :rtype :class:`list` of  :class:`ValidationError`
        """

        log.trace.debug("Checking for size in updated luns")
        errors = []
        for node in nodes:
            luns = get_updated_items(node.system.disks.query('lun-disk'))
            for lun in luns:
                old_size = int(normalise_to_megabytes(
                    lun.applied_properties['size']))
                new_size = int(normalise_to_megabytes(lun.size))
                if new_size < old_size:
                    msg = ('Invalid Size. New size({new_size}M) '
                           'should not be less than Old size '
                           '{old_size}M').format(new_size=new_size,
                                                    old_size=old_size)
                    errors.append(ValidationError(item_path=lun.get_vpath(),
                                                    error_message=msg
                    ))
        return errors

    def _check_updated_luns_new_size_too_small(self, nodes):
        """
        This function checks that the new size updated to a LUN must be at
        least 1% bigger than the previous size of the LUN.

        :param nodes: A list of managed node objects from model.
        :type nodes: :class:`list`
        :returns: A list of ValidationError objects.
        :rtype :class:`list` of  :class:`ValidationError`
        """

        log.trace.debug("Checking for new size >1% bigger in updated luns")
        errors = []
        for node in nodes:
            luns = get_updated_items(node.system.disks.query('lun-disk'))
            for lun in luns:
                if lun.applied_properties['size'] == lun.size:
                    continue

                old_size = int(normalise_to_megabytes(
                    lun.applied_properties['size']))
                new_size = int(normalise_to_megabytes(lun.size))
                if new_size <= old_size +     \
                        int((old_size / 100) * \
                        LUN_SIZE_UPDATE_THRESHOLD_PERCENT):
                    msg = ('Invalid Size. Size increase is too small. '
                           'New size \"{0}M\" is within 1% of Old size '
                           '\"{1}M.\"'.format(new_size, old_size))
                    errors.append(ValidationError(item_path=lun.get_vpath(),
                                                  error_message=msg
                    ))
        return errors

    def _check_snaps_in_lun_expansion(self, snapshots, nodes):
        """
        This function checks that a LUN that is about to be expanded
        does not contains a snapshot.

        :param snapshots: A list of snapshots from model.
        :type snapshot-base: :class:`list`
        :param nodes: A list of node objects from model
        :type nodes: :class:`list`
        :returns: A list of ValidationError objects.
        :rtype :class:`list` of :class:`ValidationError
        """
        errors = []
        log.trace.debug("""Checking that there are no snaps in the SAN in the
        case of Lun Expansion""")
        # filter for "unnamed" snapshots

        def lun_expansion_with_snap(lun):
            snappable = lun.snap_size > 0 and lun.external_snap == "false"
            old_size = int(normalise_to_megabytes(
                lun.applied_properties['size']))
            new_size = int(normalise_to_megabytes(lun.size))
            return (new_size > old_size) and snappable

        snapshot = "snapshot" in [snap.item_id for snap in snapshots]
        if snapshot:
            for node in nodes:
                luns = get_updated_items(node.system.disks.query("lun-disk"))
                for lun in luns:
                    if lun_expansion_with_snap(lun):
                        msg = ("It is not possible to expand a LUN that "
                                "contains a snapshot")
                        errors.append(ValidationError(
                            item_path=lun.get_vpath(),
                            error_message=msg))
        return errors

    def _check_valid_lun_updates(self, nodes):
        """
        Verify that only the size, snap_size or external_snap could be
        changed.

        :param nodes: A list of nodes.
        :type nodes: :class:`list` of :class:`node`
        :returns: Any errors encountered.
        :rtype: :class:`list` of :class:`Error`
        """

        errors = []
        log.trace.debug("Checking only updatable properties could "
                        "be updated in luns")
        for node in nodes:
            luns = get_updated_items(node.system.disks.query('lun-disk'))
            for lun in luns:
                for prop in lun.applied_properties.keys():
                    ignore = (prop in LUN_UPDATABLE_PROPERTIES)
                    try:
                        new_value = getattr(lun, prop)
                    except AttributeError:
                        ignore = True
                    if not ignore:
                        old_value = lun.applied_properties[prop]
                        if old_value != new_value:
                            msg = ('Only the size property could be '
                                   'updated in a lun ({p})').format(
                                        p=prop)
                            errors.append(ValidationError(
                                item_path=lun.get_vpath(),
                                error_message=msg))
        return errors

    def _check_storage_container(self, emc_sans):
        """
        This function checks that at least one storage container is defined
        per SAN.

        :param emc_sans: A list of EMC SAN objects from model.
        :type emc_sans: :class:`list` of
            :class:`litp.core.model_manager.QueryItem` objects
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking storage containers are defined")
        errors = []
        for san in emc_sans:
            if len(san.storage_containers) == 0:
                errors.append(
                    ValidationError(
                        item_path=san.get_vpath(),
                        error_message="No storage containers defined"
                    )
                )
        return errors

    def _check_bootable_luns(self, emc_sans, nodes):
        """
        This function performs the following checks on bootable LUNs:
         - LUN not also shared
         - dist_part enabled

        :param emc_sans: A list of EMC SAN objects from model.
        :type emc_sans: :class:`list` of
            :class:`litp.core.model_manager.QueryItem`
        :param nodes: A list of managed node objects from model.
        :type nodes: :class:`list` of :class:`node`
        :returns: A list of ValidationError objects.
        :rtype: :class:`ValidationError`
        """

        log.trace.debug("Checking bootable LUNs")
        errors = []
        for san in emc_sans:
            for storage_container in san.storage_containers:
                poolname = storage_container.name
                for node in nodes:
                    bootable_luns = node.system.disks.query(
                                   'lun-disk', bootable='true',
                                   storage_container=poolname)
                    for lun in bootable_luns:
                        # check bootable LUN not also marked shared
                        log.trace.debug("Checking bootable LUNs not " +
                                         "also marked shared")
                        if lun.shared == "true":
                            errors.append(
                                ValidationError(
                                    item_path=lun.get_vpath(),
                                    error_message=("Node %s: Bootable LUN %s "
                                                   "also marked as shared"
                                              % (node.hostname, lun.lun_name))
                                )
                            )
        return errors

    def _check_luns_in_valid_container(self, emc_sans, nodes):
        """
        This function checks that each LUN is in one of the storage
        containers (i.e. pools) defined in the SANs.

        :param emc_sans: A list of EMC SAN objects from model.
        :type emc_sans: :class:`list`
            of :class:`litp.core.model_manager.QueryItem`
        :param nodes: A list of managed node objects from model.
        :type nodes: :class:`list` of `node`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking LUNs are in a valid container")
        errors = []
        valid_containers = self._get_storage_container_names(emc_sans)
        if valid_containers:
            for node in nodes:
                all_luns = node.system.disks.query('lun-disk')
                for lun in all_luns:
                    if lun.storage_container not in valid_containers:
                        errors.append(
                            ValidationError(
                                item_path=lun.get_vpath(),
                                error_message=("Node %s: LUN %s: "
                                               "invalid storage container "
                                               "'%s'. Valid containers are: %s"
                                              % (node.hostname, lun.lun_name,
                                                  lun.storage_container,
                                                  ','.join(valid_containers)))
                            )
                        )
        return errors

    def _check_duplicate_lun_names(self, emc_sans, nodes):
        """
        This function performs the following checks on LUNs:
         - Non-shared LUNs have unique names within a SAN.
         - Non-shared LUNs do not exist with same
           name as shared LUN.
         - Shared LUNS are not duplicated within a node

        :param emc_sans: A list of EMC SAN objects from model.
        :type emc_sans: :class:`list` of
            :class:`litp.core.model_manager.QueryItem`
        :param nodes: A list of managed node objects from model.
        :type nodes: :class:`list` of :class:`node`
        :returns: A list of ValidationError.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking for duplicate LUN names")
        errors = []
        for san in emc_sans:
            san_nonshared_luns = []
            san_shared_luns = []
            for storage_container in san.storage_containers:
                poolname = storage_container.name
                for node in nodes:
                    san_nonshared_luns += node.system.disks.query('lun-disk',
                                storage_container=poolname, shared='false')
                    # check for duplicates within shared luns in a node
                    node_shared_luns = node.system.disks.query('lun-disk',
                                storage_container=poolname, shared='true')
                    dup_lun_names = self._get_duplicate_luns(node_shared_luns)
                    if dup_lun_names:
                        errors.append(
                            ValidationError(
                                item_path=node.get_vpath(),
                                error_message="Duplicate shared LUN \
                                               names defined for node %s: %s"
                               % (node.hostname, ','.join(dup_lun_names)),
                            )
                        )
                    san_shared_luns += node_shared_luns
                # check for duplicate lun names in the san
                # for luns which are not marked shared
                dup_lun_names = self._get_duplicate_luns(san_nonshared_luns)
                if dup_lun_names:
                    errors.append(
                        ValidationError(
                            item_path=san.get_vpath(),
                            error_message="Duplicate LUN names \
                                           defined for SAN %s: %s"
                            % (san.name, ','.join(dup_lun_names)),
                        )
                    )
                if not errors:
                    # check to ensure luns with same name
                    # are not marked shared and non-shared
                    dup_lun_names = self._get_duplicate_luns(san_nonshared_luns
                              + self._uniqify_shared_luns(san_shared_luns))
                    if dup_lun_names:
                        errors.append(
                            ValidationError(
                                item_path=san.get_vpath(),
                                error_message=("The following LUNs are marked "
                                               "shared and non-shared for SAN "
                                               "%s: %s"
                                        % (san.name, ','.join(dup_lun_names)))
                            )
                        )
        return errors

    def _check_shared_luns_identical(self, nodes):
        """
        This function performs the following checks on LUNs:
         - Shared LUNS are have identical props

        :param emc_sans: A list of EMC SAN objects from model.
        :type emc_sans: :class:`list` of
            :class:`litp.core.model_manager.QueryItem`
        :param nodes: A list of managed node objects from model.
        :type nodes: :class:`list` of :class:`node`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking for mismatched shared lun parameters")
        errors = []
        processed_shared_lunnames = []
        for node in nodes:
            node_shared_luns = node.system.disks.query('lun-disk',
                                                    shared='true')
            for shared_lun in node_shared_luns:
                if shared_lun.lun_name not in processed_shared_lunnames:
                    processed_shared_lunnames.append(
                                        shared_lun.lun_name)

                    if hasattr(shared_lun, 'balancing_group'):
                        props = ("size", "bootable", "name",
                                   "storage_container", "balancing_group")
                    else:
                        props = ("size", "bootable", "name",
                                   "storage_container")

                    for lun_prop in props:
                        errors += self._check_shared_lun_param_mismatch(
                                   shared_lun, node, nodes, lun_prop)

        return errors

    def _check_shared_lun_param_mismatch(self, shared_lun, node, nodes,
                                         param_name):
        """
        This function checks that the passed parameter has the same value for
        all instances of a shared LUN.

        :param shared_lun: The shared LUN.
        :type shared_lun: :class:`litp.core.model_manager.QueryItem`
        :param node: The node.
        :type node: :class:`litp.core.model_manager.QueryItem`
        :param nodes: A list of nodes.
        :type nodes: :class:`list` of
            :class:`litp.core.model_manager.QueryItem`
        :param param_name: The name of the parameter to check.
        :type param_name: :class:`str`
        :returns: A list of ValidationError objects.
        :rtype :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking for mismatched shared lun parameter "
                        + param_name + " for LUN " + shared_lun.lun_name)
        errors = []
        for other_node in nodes:
            if node.hostname == other_node.hostname:
                continue
            param_value = eval("shared_lun." + param_name)
            other_node_shared_luns = \
                other_node.system.disks.query('lun-disk',
                                            shared='true')
            for other_shared_lun in other_node_shared_luns:
                if shared_lun.lun_name == \
                    other_shared_lun.lun_name:
                    # now we compare all the other props
                    other_param_value = eval("other_shared_lun." +
                                             param_name)
                    if param_value != other_param_value:
                        errors.append(
                            ValidationError(
                                item_path=node.get_vpath(),
                                error_message=("Shared LUN %s: "
                                               "%s mismatch between "
                                               "node %s and node %s - "
                                               "%s vs %s"
                                               % (shared_lun.lun_name,
                                                  param_name,
                                                  node.hostname,
                                                  other_node.hostname,
                                                  param_value,
                                                  other_param_value))
                            )
                        )
                        break
        return errors

    def _check_san_accessible_from_ms(self, plugin_api_context):
        """
        This function checks that the storage network defined in the SANs is
        among the networks defined for the MS.

        :param plugin_api_context: Plugin API context.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking SAN networks are accessible from MS")
        errors = []
        emc_sans = plugin_api_context.query('san-emc')
        managed_station = plugin_api_context.query('ms')[0]
        ms_networks = [nw.network_name
                      for nw in managed_station.network_interfaces]
        for san in emc_sans:
            if san.storage_network not in ms_networks:
                errors.append(
                    ValidationError(
                        item_path=san.get_vpath(),
                        error_message=("SAN %s network %s not "
                                       "in list of MS networks: %s"
                                   % (san.name, san.storage_network,
                                   ','.join(ms_networks)))
                    )
                )
        return errors

    def _check_hba_ports(self, nodes):
        """
        This function checks that each node has at least one HBA port defined.

        :param nodes: A list of managed node objects from model.
        :type nodes: :class:`list` of
            :class:`litp.core.model_manager.QueryItem`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        errors = []
        log.trace.debug("Checking HBA ports")
        for node in nodes:
            # Only check for HBA's if the system is using any lun-disks
            if node.system.disks.query('lun-disk'):
                hbas = node.system.controllers.query('hba')
                if len(hbas) == 0:
                    errors.append(
                        ValidationError(
                             item_path=node.system.controllers.get_vpath(),
                             error_message=("No HBAs defined for node %s"
                                            % node.hostname)
                        )
                    )
                for hba in hbas:
                    if not hba.hba_porta_wwn and not hba.hba_portb_wwn:
                        errors.append(
                            ValidationError(
                                 item_path=hba.get_vpath(),
                                 error_message=(
                                     "Neither HBA port A nor HBA "
                                     "port B have been specified for node %s"
                                     % node.hostname)
                            )
                        )
        return errors

    def _check_fen_luns_valid_rg(self, plugin_api_context):
        """
        This function checks that the fencing LUNs are in a valid raid group.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking fencing lun names are not duplicated")
        errors = []
        emc_sans = plugin_api_context.query('san-emc')
        valid_rg_ids = self._get_raid_group_ids(emc_sans)
        vcs_clusters = plugin_api_context.query('vcs-cluster')
        for cluster in vcs_clusters:
            fen_luns = cluster.fencing_disks.query('lun-disk')
            for lun in fen_luns:
                if lun.storage_container not in valid_rg_ids:
                    errors.append(
                        ValidationError(
                            item_path=cluster.get_vpath(),
                            error_message=("Invalid Raid Group ID %s "
                                  "associated with fencing LUN %s"
                                  % (lun.storage_container, lun.lun_name))
                        )
                    )
        return errors

    def _check_fen_luns_valid_size(self, plugin_api_context):
        """
        This function checks that the fencing LUNs are a valid size group.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking fencing luns are valid size")
        errors = []
        vcs_clusters = plugin_api_context.query('vcs-cluster')
        for cluster in vcs_clusters:
            fen_luns = cluster.fencing_disks.query('lun-disk')
            for lun in fen_luns:
                lun_size = int(normalise_to_megabytes(lun.size))
                if lun_size > MAX_FEN_LUN_SIZE:
                    errors.append(
                        ValidationError(
                            item_path=cluster.get_vpath(),
                            error_message=("Size of fencing lun %s, "
                                  "%s, is too large (max=%sM)"
                                  % (lun.lun_name, lun.size,
                                  str(MAX_FEN_LUN_SIZE)))
                        )
                    )
        return errors

    def _check_fen_luns_duplicate_names(self, plugin_api_context):
        """
        This function checks that the fencing lun names are not duplicated
        within a cluster.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking fencing luns are in valid RG")
        errors = []
        vcs_clusters = plugin_api_context.query('vcs-cluster')
        for cluster in vcs_clusters:
            fen_luns = cluster.fencing_disks.query('lun-disk')
            dup_lun_names = self._get_duplicate_luns(fen_luns)
            if dup_lun_names:
                errors.append(
                    ValidationError(
                        item_path=cluster.get_vpath(),
                        error_message=("Fencing LUN names duplicated "
                              "within cluster")
                    )
                )
        return errors

    def _check_fen_luns_shared_not_bootable(self, plugin_api_context):
        """
        This function checks that the fencing luns are marked shared and not
        bootable.

        :param plugin_api_context: API context of LITP model.
        :type plugin_api_context: :class:`PluginApiContext`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """

        log.trace.debug("Checking fencing luns are in valid RG")
        errors = []
        vcs_clusters = plugin_api_context.query('vcs-cluster')
        for cluster in vcs_clusters:
            fen_luns = cluster.fencing_disks.query('lun-disk')
            for lun in fen_luns:
                if lun.shared != "true":
                    errors.append(
                        ValidationError(
                            item_path=cluster.get_vpath(),
                            error_message=("Fencing LUN %s not marked "
                                           "shared" % lun.lun_name)
                        )
                    )
                if lun.bootable == "true":
                    errors.append(
                        ValidationError(
                            item_path=cluster.get_vpath(),
                            error_message=("Fencing LUN %s is marked "
                                           "bootable" % lun.lun_name)
                        )
                    )
        return errors

    def _check_san_details(self, emc_sans):
        """
        Utility function to check SAN login details:
        - Check at least one IP defined; If two IPS are defined, check if
        they are different.

        :param emc_sans: A list of SANs.
        :type emc_sans: :class: list: of
            :class:`litp.core.model_manager.QueryItem`
        :returns: A list of ValidationError objects.
        :rtype: :class:`list` of :class:`ValidationError`
        """
        errors = []
        log.trace.debug("Checking SAN details")
        for san in emc_sans:
            if not san.ip_a and not san.ip_b:
                errors.append(
                    ValidationError(
                         item_path=san.get_vpath(),
                         error_message=("No connection IP specified for san %s"
                                      % san.name)
                    )
                )
            else:
                if san.ip_a == san.ip_b:
                    errors.append(
                            ValidationError(
                                item_path=san.get_vpath(),
                                error_message="SAN IP address (a) must be "
                                "different from SAN IP address (b)"
                                )
                            )
        return errors

    def _get_storage_container_names(self, emc_sans):
        """
        Utility function to get a list of all the storage
        containers defined across the SANs.
        TODO - look for containers of pool only

        :param emc_sans: A list of EMC SAN objects from model.
        :type emc_sans: :class:`list` of
            :class:`litp.core.model_manager.QueryItem`
        :returns: A list of storage container names.
        :rtype: :class:`list` of :class:`str`
        """

        log.trace.debug("Entering get_storage_container_names")
        storage_container_names = []
        for san in emc_sans:
            for storage_container in san.storage_containers:
                storage_container_names.append(storage_container.name)

        return storage_container_names

    def _get_raid_group_ids(self, emc_sans):
        """
        Utility function to get a list of all the raid groups defined across
        the SANs.

        :param emc_sans: A list of EMC SAN objects from model.
        :type emc_sans: :class:`list` o
            :class:`litp.core.model_manager.QueryItem`
        :returns: A list of raid group ids.
        :rtype: :class:`list` of :class:`str`
        """

        log.trace.debug("Entering _get_raid_group_ids")
        rg_ids = []
        for san in emc_sans:
            for storage_container in san.storage_containers:
                if storage_container.type.lower() == "raid_group":
                    rg_ids.append(storage_container.name)

        return rg_ids

    def _get_duplicate_luns(self, luns):
        """
        Utility function to identify LUNs in a list where the LUN name is
        duplicated.

        :param luns: A list of LUN objects.
        :type luns: :class:`list` of :class:`litp.core.model_manager.QueryItem`
        :returns: A list of duplicate LUN names.
        :rtype: :class:`list` of :class:`str`
        """

        if len(luns) < 2:
            return None

        lun_names = [lun.lun_name for lun in luns]
        return tuple(set([lun_names[i] for i, x in enumerate(lun_names)
                        if lun_names.count(x) > 1]))

    def _uniqify_shared_luns(self, luns):
        """
        Utility function to remove luns from lun list with duplicate names.

        :param luns: A list of lun objects.
        :type luns: :class:`list` of :class:`litp.core.model_manager.QueryItem`
        :returns: A list of luns objects where lun names are unique.
        :rtype: :class:`list` of :class:`litp.core.model_manager.QueryItem`
        """

        uniq_luns = []
        for lun in luns:
            if lun.lun_name not in [l.lun_name for l in uniq_luns]:
                uniq_luns.append(lun)
        return uniq_luns
