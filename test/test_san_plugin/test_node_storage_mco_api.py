# COPYRIGHT Ericsson AB 2015
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

import os, sys, unittest
from nose.plugins.skip import SkipTest
from mock import (patch, MagicMock)
from litp.core.litp_logging import LitpLogger
from san_plugin.node_storage_mco_api import (NodeStorageMcoApiException, NodeStorageMcoApi,)


class TestNodeStorage(unittest.TestCase):

    @patch("san_plugin.node_storage_mco_api.log")
    @patch("san_plugin.node_storage_mco_api.run_rpc_command")
    def test_call_mco(self, run_rpc_command, litp_log_mock):
        """
        Test call MCO with command, verify errors thrown correctly
        """

        info =  MagicMock(name="trace_info_mock")
        error = MagicMock(name="trace_error_mock")
        litp_log_mock.trace.info = info
        litp_log_mock.trace.error = error

        myNS = NodeStorageMcoApi("atrcxb2443")
        myNS._gen_mco_command = MagicMock("gen_mco_mock", return_value="\"mco rpc scsi_ops scan_scsi -I atrcxb2443\" ")
        agent = "scsi_ops"
        action = "scan_scsi"
        kargs = {"some" : 0, "example" : 1, "kargs" : 2}


        # Run with len(results) != 1, len(results[self.node]["errors] == 0 
        # and result["retcode"] == 0

        run_rpc_command.return_value = {}

        self.assertRaises(NodeStorageMcoApiException,
            myNS._call_mco, agent, action, kargs)

        # Run with len(results) == 1, len(results[self.node]["errors] != 0
        # and result["retcode"] == 0

        run_rpc_command.return_value = {'atrcxb2443': 
                                       {'data': 
                                       {'err': '', 'out': '', 'retcode': 0},
                                       'errors': 'ExampleError'}}

        self.assertRaises(NodeStorageMcoApiException,
            myNS._call_mco, agent, action, kargs)

        # Run with len(results) == 1, len(results[self.node]["errors] == 0
        # Run with result["retcode"] != 0

        run_rpc_command.return_value = {'atrcxb2443': 
                                       {'data': 
                                       {'err': '', 'out': '', 'retcode': 1},
                                       'errors': ''}}

        self.assertRaises(NodeStorageMcoApiException,
            myNS._call_mco, agent, action, kargs)


        # Run with len(results) == 1, len(results[self.node]["errors] == 0
        # Run with result["retcode"] == 0

        run_rpc_command.return_value = {'atrcxb2443': 
                                       {'data': 
                                       {'err': '', 'out': '', 'retcode': 0},
                                       'errors': ''}}

        myNS._call_mco(agent, action, kargs)
        info.assert_any_call("MCO call success: \"mco rpc scsi_ops scan_scsi -I atrcxb2443\" ")


    def test_gen_mco_command(self):
        """
        Test generate MCO command
        """

        myNS = NodeStorageMcoApi("node")
        agent = "scsi_ops"
        action = "scan_scsi"
        kargs = {"some" : 0, "example" : 1, "kargs" : 2}
        command = myNS._gen_mco_command(agent, action, kargs).strip()
        expected_command = "\"mco rpc scsi_ops scan_scsi some=0 example=1 kargs=2 -I node\""
        self.assertEqual(command, expected_command)

    @patch("san_plugin.node_storage_mco_api.NodeStorageMcoApi._call_mco")
    def test_scan_scsi_hosts(self, mock_mco_call):
        """
        Test scan SCSI hosts
        """

        myNS = NodeStorageMcoApi("node")
        myNS.scan_scsi_hosts()
        mock_mco_call.assert_any_call("scsi_ops", "scan_scsi", {}, 120)


    @patch("san_plugin.node_storage_mco_api.NodeStorageMcoApi._call_mco")
    def test_edit_multipath(self, mock_mco_call):
        """
        Test edit multipath
        """

        myNS = NodeStorageMcoApi("node")
        myNS.edit_multipath("NotARealUUID")
        mock_mco_call.assert_any_call("scsi_ops", "add_multipath",
                                     {"uuid" : "NotARealUUID"}, 120)
