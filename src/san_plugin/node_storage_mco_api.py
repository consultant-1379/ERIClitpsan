##############################################################################
# COPYRIGHT Ericsson AB 2014
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

from litp.core.rpc_commands import run_rpc_command
from litp.core.litp_logging import LitpLogger
log = LitpLogger()

DEFAULT_MCO_TIMEOUT = 120


class NodeStorageMcoApiException(Exception):
    pass


class NodeStorageMcoApi(object):

    def __init__(self, node):
        # self.agent = "nodestorage" # TODO # Need to refactor this as there
        # are several agents
        self.node = node  # we use string, others use list

    def _call_mco(self, agent, mco_action, kargs, timeout=None):
        """
        general method to run MCollective commands using run_rpc_command
        """
        mco_cmd = self._gen_mco_command(agent, mco_action, kargs)

        log.trace.info('Running MCO Node Storage command {0}'.format(mco_cmd))
        results = run_rpc_command([self.node], agent, mco_action, kargs,
                                                                  timeout)

        if len(results) != 1:
            err_msg = "Failed to execute command: {0}".format(mco_cmd)
            err_msg += "Reason: Expected 1 response, received %s"\
                    % (len(results))
            log.trace.error(err_msg)
            raise NodeStorageMcoApiException(err_msg)
        if len(results[self.node]["errors"]) != 0:
            err_msg = "Command failure: {0}".format(mco_cmd)
            err_msg += "Reason: MCO failure... {0}"\
                    .format(results[self.node]["errors"])
            log.trace.error(err_msg)
            raise NodeStorageMcoApiException(err_msg)

        result = results[self.node]['data']  # we only pass in one node
        if result["retcode"] != 0:
            err_msg = "Command failure: {0}".format(mco_cmd)
            err_msg += "Reason: Command failed... retcode {0}, stderr {1}"\
                    .format(result["retcode"], result["err"])
            log.trace.error(err_msg)
            raise NodeStorageMcoApiException(err_msg)

        log.trace.info("MCO call success: {0}".format(mco_cmd))

    def _gen_mco_command(self, agent, action, kargs=None):
        command = "\"mco rpc {0} {1} ".format(agent, action)
        if kargs:
            for a, v in kargs.iteritems():
                command += "{0}={1} ".format(a, v)
        command += "-I {0}\" ".format(self.node)
        return command

    def scan_scsi_hosts(self, timeout=DEFAULT_MCO_TIMEOUT):
        kwargs = {}
        agent = "scsi_ops"
        mco_action = "scan_scsi"
        self._call_mco(agent, mco_action, kwargs, timeout)

    def edit_multipath(self, uuid, timeout=DEFAULT_MCO_TIMEOUT):
        kwargs = {"uuid": uuid}
        agent = "scsi_ops"
        mco_action = "add_multipath"
        self._call_mco(agent, mco_action, kwargs, timeout)

    def node_scan_scsi_device_mpath(self, uuid, timeout=DEFAULT_MCO_TIMEOUT):
        kwargs = {"uuid": uuid}
        agent = "scsi_ops"
        mco_action = "rescan_DM"

        self._call_mco(agent, mco_action, kwargs, timeout)

    def node_scan_scsi_device_dmp(self, lun_id, timeout=DEFAULT_MCO_TIMEOUT):
        kwargs = {"lunid": lun_id}
        agent = "scsi_ops"
        mco_action = "rescan_VX"
        self._call_mco(agent, mco_action, kwargs, timeout)
