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

sys.path.append('./puppet/mcollective_agents/files')

from rescan_DM import (run_command, get_multipath_device,
get_lun_size, get_scsi_paths, scan_scsi_paths, )
from rescan_VX import(err, run_command, get_emc_device, get_multipath_devices,
update_block_devices, rescan_vx, )


class TestMultipath(unittest.TestCase):

    mock_mpath_output =\
          "mpathc (3600601604f2131221af43b7c258ee511) dm-1 DGC,VRAID\n" +\
          "size=9G features='1 queue_if_no_path' hwhandler='1 emc' wp=rw\n" +\
          "|-+- policy='round-robin 0' prio=0 status=active\n" +\
          "| `- 0:0:0:2 sdc 8:32 active undef running\n" +\
          "`-+- policy='round-robin 0' prio=0 status=enabled\n" +\
          "  `- 0:0:1:2 sdf 8:80 active undef running\n" +\
          "mpathb (3600601604f213400027dfb5c258ee511) dm-4 DGC,VRAID\n" +\
          "size=5G features='1 queue_if_no_path' hwhandler='1 emc' wp=rw\n" +\
          "|-+- policy='round-robin 0' prio=0 status=active\n" +\
          "| `- 0:0:0:1 sdb 8:16 active undef running\n" +\
          "`-+- policy='round-robin 0' prio=0 status=enabled\n" +\
          "  `- 0:0:1:1 sde 8:64 active undef running\n" +\
          "mpatha (3600601604f213400fc05c096128ee511) dm-0 DGC,VRAID\n" +\
          "size=6G features='1 queue_if_no_path' hwhandler='1 emc' wp=rw\n" +\
          "|-+- policy='round-robin 0' prio=0 status=active\n" +\
          "| `- 0:0:1:0 sdd 8:48 active undef running\n" +\
          "`-+- policy='round-robin 0' prio=0 status=enabled\n" +\
          "  `- 0:0:0:0 sda 8:0  active undef running\n"

    mock_mpath_output_2 =\
          "mpathc (3600601604f2131221af43b7c258ee511) dm-1 DGC,VRAID\n" +\
          "size=9G features='1 queue_if_no_path' hwhandler='1 emc' wp=rw\n" +\
          "|-+- policy='round-robin 0' prio=0 status=active\n" +\
          "| `- 0:0:10:2 sdc 8:32 active undef running\n" +\
          "`-+- policy='round-robin 0' prio=0 status=enabled\n" +\
          "  `- 0:10:11:2 sdf 8:80 active undef running\n" +\
          "mpathb (3600601604f213400027dfb5c258ee511) dm-4 DGC,VRAID\n" +\
          "size=5G features='1 queue_if_no_path' hwhandler='1 emc' wp=rw\n" +\
          "|-+- policy='round-robin 0' prio=0 status=active\n" +\
          "| `- 0:0:0:1 sdb 8:16 active undef running\n" +\
          "`-+- policy='round-robin 0' prio=0 status=enabled\n" +\
          "  `- 0:0:1:1 sde 8:64 active undef running\n" +\
          "mpatha (3600601604f213400fc05c096128ee511) dm-0 DGC,VRAID\n" +\
          "size=6G features='1 queue_if_no_path' hwhandler='1 emc' wp=rw\n" +\
          "|-+- policy='round-robin 0' prio=0 status=active\n" +\
          "| `- 0:0:1:0 sdd 8:48 active undef running\n" +\
          "`-+- policy='round-robin 0' prio=0 status=enabled\n" +\
          "  `- 0:0:0:0 sda 8:0  active undef running\n"

    mock_vx_output =\
      "DEVICE       TYPE            DISK         GROUP        STATUS\n" +\
      "emc_clariion0_56 auto:sliced     emc_clariion0_56  elasticsearch_vg online\n" +\
      "emc_clariion0_57 auto:LVM        -            -            LVM\n" +\
      "emc_clariion0_58 auto:sliced     emc_clariion0_58  postgresdb_vg online\n" +\
      "emc_clariion0_59 auto:sliced     emc_clariion0_59  jms_vg       online\n" +\
      "emc_clariion0_62 auto:sliced     emc_clariion0_62  mysql_vg     online\n" +\
      "emc_clariion0_64 auto:sliced     emc_clariion0_64  versant_vg   online\n" +\
      "emc_clariion0_67 auto:LVM        -            -            online invalid\n" +\
      "emc_clariion0_96 auto:sliced     -            (vxfencoorddg_21137) online\n" +\
      "emc_clariion0_98 auto:sliced     -            (vxfencoorddg_21137) online\n" +\
      "emc_clariion0_100 auto:sliced     -            (vxfencoorddg_21137) online\n"

    mock_vx_mpath_devices =\
      "NAME         STATE[A]   PATH-TYPE[M] CTLR-NAME  ENCLR-TYPE   ENCLR-NAME    ATTRS\n" +\
      "================================================================================\n" +\
      "sdd          ENABLED(A)  PRIMARY      c0         EMC_CLARiiON  emc_clariion0     -\n" +\
      "sdn          ENABLED    SECONDARY    c0         EMC_CLARiiON  emc_clariion0     -\n" +\
      "sdx          ENABLED    SECONDARY    c1         EMC_CLARiiON  emc_clariion0     -\n"

    @patch("rescan_DM.run_command")
    def test_get_multipath_device(self, mock_run_cmd):
        """
        Test multipath device name retrieved on DMP
        """

        mock_run_cmd.return_value = self.mock_mpath_output
        result = get_multipath_device("600601604f2131221af43b7c258ee511")
        self.assertTrue(result == "mpathc", "Not equal, mpathc != " + result)

    @patch("rescan_DM.run_command")
    def test_get_lun_size(self, mock_run_cmd):
        """
        Test size of LUN to expand is retrieved on DMP
        """

        mock_run_cmd.return_value = self.mock_mpath_output
        result = get_lun_size("600601604f213400fc05c096128ee511")
        self.assertTrue(result == "6G", "Not equal, 6G != " + result)

    @patch("rescan_DM.run_command")
    def test_get_scsi_paths(self, mock_run_cmd):
        """
        Test multipaths to LUN retrieved on DMP
        """

        mock_run_cmd.return_value = self.mock_mpath_output
        result = get_scsi_paths("600601604f2131221af43b7c258ee511")
        self.assertTrue(result == ["0:0:0:2", "0:0:1:2"],\
            "Not equal, ['0:0:0:2', '0:0:1:2'] != " + str(result))

        mock_run_cmd.return_value = self.mock_mpath_output_2
        result = get_scsi_paths("600601604f2131221af43b7c258ee511")
        self.assertTrue(result == ["0:0:10:2", "0:10:11:2"],\
            "Not equal, ['0:0:10:2', '0:10:11:2'] != " + str(result))

    @patch("rescan_VX.run_command")
    def test_get_emc_device(self, mock_run_cmd):
        """
        Test EMC device for LUN number retrieved
        """

        mock_run_cmd.return_value = (0, self.mock_vx_output)
        result = get_emc_device(57)
        self.assertTrue(result == "emc_clariion0_57", "Not equal, " +\
            "'emc_clariion0_57 != " + str(result))

    @patch("rescan_VX.run_command")
    def test_get_multipath_devices(self, mock_run_cmd):
        """
        Test multipath devices retrieved on VX
        """

        mock_run_cmd.return_value = (0, self.mock_vx_mpath_devices)
        result = get_multipath_devices("emc_clariion0_57")
        self.assertTrue(result == ["sdd", "sdn", "sdx"], "Not equal, " +\
          "['sdd', 'sdn', 'sdx'] != " + str(result))






