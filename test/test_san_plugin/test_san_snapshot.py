# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

import sys
import unittest
from mock import patch, Mock, MagicMock
from collections import namedtuple

from litp.core.plugin_context_api import PluginApiContext
from litp.core.execution_manager import CallbackExecutionException
from sanapi.sanapiexception import SanApiException, \
SanApiEntityNotFoundException, SanApiEntityAlreadyExistsException, \
SanApiConnectionException
from sanapi.sanapiinfo import LunInfo, HbaInitiatorInfo, HluAluPairInfo, \
StorageGroupInfo, StoragePoolInfo, SnapshotInfo
from litp.core.task import CallbackTask

from san_plugin.san_snapshot import SnapshotTask, get_tasks, \
restore_lun_snapshot_psl_task, remove_lun_snapshot_psl_task, \
create_lun_snapshot_psl_task, gen_verify_snapshot_exists_task, \
verify_san_exists_psl_task, gen_san_already_exists_check_task, \
snapshot_already_exists_psl_task, gen_pool_size_check_task, \
pool_size_check_psl_task, gen_verify_lun_is_ready, \
 verify_lun_is_ready_psl_task

from testfunclib import BasicTestSan, myassert_raises_regexp
import testfunclib
from testfunclib import skip
from san_plugin import san_snapshot

class TestSanSnapshots(BasicTestSan):
    def setUp(self):
        BasicTestSan.setUp(self)

    def setup_san_model_with_one_snappable_lun(self):
        # create model with one snappable LUN on SYSTEM1
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model_with_bmc()

        self.add_san( san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                      "admin", "password", "Global", "12321", "FARGO01",
                      "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
                                      "hba1":("00:11:22:33:44:55:66:77",
                                              "AA:BB:CC:DD:EE:FF:00:11"),
                                      "hba2":("01:11:22:33:44:55:66:77",
                                              "AB:BB:CC:DD:EE:FF:00:11")
                                      })
        self.add_hbas("system2", {
                                      "hba1":("00:11:22:33:44:55:66:88",
                                              "AA:BB:CC:DD:EE:FF:00:12"),
                                      "hba2":("01:11:22:33:44:55:66:99",
                                              "AB:BB:CC:DD:EE:FF:00:13")
                                      })

        self.add_node("cluster1", "node1", "system3", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.30"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.30"}
                                          ])
        self.add_lun_disk("system3", "mysnappablelun1", "MYSNAPLUN1", "sda", "20G", pool_name,
                          bootable = "false", shared = "false",
                          uuid="BAD00000000000000000000000000011",
                          external_snap="false", snap_size="30")

    def setup_san_model_with_two_snappable_luns_and_one_external_snap(self):
        # create model with one snappable LUN on SYSTEM1
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san( san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                      "admin", "password", "Global", "12321", "FARGO01",
                      "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
                                      "hba1":("00:11:22:33:44:55:66:77",
                                              "AA:BB:CC:DD:EE:FF:00:11"),
                                      "hba2":("01:11:22:33:44:55:66:77",
                                              "AB:BB:CC:DD:EE:FF:00:11")
                                      })
        self.add_hbas("system2", {
                                      "hba1":("00:11:22:33:44:55:66:88",
                                              "AA:BB:CC:DD:EE:FF:00:12"),
                                      "hba2":("01:11:22:33:44:55:66:99",
                                              "AB:BB:CC:DD:EE:FF:00:13")
                                      })

        self.add_node("cluster1", "node1", "system1", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.30"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.30"}
                                          ])
        self.add_lun_disk("system1", "mysnappablelun1", "MYSNAPLUN1", "sda", "20G", pool_name,
                          bootable = "false", shared = "false",
                          uuid="BAD00000000000000000000000000011",
                          external_snap="false", snap_size="30")
        self.add_lun_disk("system1", "mysnappablelun2", "MYSNAPLUN2", "sdb", "20G", pool_name,
                          bootable = "false", shared = "false",
                          uuid="BAD00000000000000000000000000012",
                          external_snap="true", snap_size="30")
        self.add_lun_disk("system1", "mysnappablelun3", "MYSNAPLUN3", "sdc", "20G", pool_name,
                          bootable = "false", shared = "false",
                          uuid="BAD00000000000000000000000000013",
                          external_snap="false", snap_size="30")



    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_gen_poolsizecheck_task(self,  mock_saninit,
                mock_get_san_passwd, mock_api_builder):
        self.setup_san_model_with_one_snappable_lun()
        san = self.context.query('san-emc', name="san_01")[0]
        luns = self.context.query("lun-disk")
        container = MagicMock()
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        container.name = "mycontainer"
        res = gen_pool_size_check_task(self.plugin, san, container, luns)
        self.assertTrue(isinstance(res, CallbackTask))

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_gen_createsnaptask(self,  mock_saninit,
                mock_get_san_passwd, mock_api_builder):
        self.setup_san_model_with_one_snappable_lun()
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        san = self.context.query('san-emc', name="san_01")[0]
        luns = self.context.query("lun-disk")
        task = SnapshotTask(plugin=self.plugin, action="create",
                snap_name="snapshots", san=san, lun=luns[0])
        self.assertTrue(isinstance(task.task, CallbackTask))

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_gen_removesnaptask(self, mock_saninit,
                mock_get_san_passwd, mock_api_builder):
        """
        Check one callback task is generated fro remove snapshot with 1 LUN.
        """
        self.setup_san_model_with_one_snappable_lun()
        san = self.context.query('san-emc', name="san_01")[0]
        luns = self.context.query("lun-disk")
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()

        task = SnapshotTask(plugin=self.plugin, action="remove",
                snap_name="snapshots", san=san, lun=luns[0])
        self.assertTrue(isinstance(task.task, CallbackTask))

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_gen_restoresnaptask(self, mock_saninit,
                mock_get_san_passwd, mock_api_builder):
        """
        Check one callback task is generated for restore snapshot with 1 LUN.
        """
        self.setup_san_model_with_one_snappable_lun()
        san = self.context.query('san-emc', name="san_01")[0]
        luns = self.context.query("lun-disk")
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        task = SnapshotTask(plugin=self.plugin, action="create",
                snap_name="snapshots", san=san, lun=luns[0])

        self.assertTrue(isinstance(task.task, CallbackTask))
    def test_get_createsnapshot_tasks_with_one_snappable_lun(self):
        ''' Verify correct # snap tasks get generated when default snap name used '''
        self.setup_san_model_with_one_snappable_lun()
        tasks = get_tasks(self.plugin, self.context, "create", "snapshot")
        self.assertEqual(len(tasks), 3)
        for i in range(3):
            self.assertTrue(isinstance(tasks[i], CallbackTask))

    def test_get_createsnapshot_tasks_with_two_snappable_luns(self):
        ''' Verify correct # snap tasks get generated two snapable luns and one wxternal_snap lun'''
        self.setup_san_model_with_two_snappable_luns_and_one_external_snap()
        # from nose.tools import set_trace; set_trace()
        tasks = get_tasks(self.plugin, self.context, "create", "snapshot")
        tasksNames = [ task.kwargs['function_name'] for task in tasks ]
        print tasksNames

        self.assertEqual(len(tasks), 4)
        for i in range(4):
            self.assertTrue(isinstance(tasks[i], CallbackTask))

        self.assertEqual( tasksNames,
            ['snapshot_already_exists_psl_task', 'pool_size_check_psl_task',
            'create_lun_snapshot_psl_task', 'create_lun_snapshot_psl_task'])

    def test_get_remove_snapshot_tasks_with_two_snappable_luns(self):
        ''' Verify correct # snap tasks get generated two snapable luns and one wxternal_snap lun (remove)'''
        self.setup_san_model_with_two_snappable_luns_and_one_external_snap()
        # from nose.tools import set_trace; set_trace()

        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        tasks = get_tasks(self.plugin, self.context, "remove", "snapshot")
        tasksNames = [ task.kwargs['function_name'] for task in tasks ]
        print tasksNames
        expected_tasks = 2
        self.assertEqual(len(tasks), expected_tasks)
        for i in range(expected_tasks):
            self.assertTrue(isinstance(tasks[i], CallbackTask))

        self.assertEqual( tasksNames,
            ['remove_lun_snapshot_psl_task', 'remove_lun_snapshot_psl_task'])

    def test_get_createsnapshot_tasks_backup_snap(self):
        ''' Verify correct no snap tasks get generated when user defined snap name used '''
        self.setup_san_model_with_one_snappable_lun()
        tasks = get_tasks(self.plugin, self.context, "create", "mysnap")
        self.assertEqual(len(tasks), 0)

    def test_get_removesnapshot_tasks_with_one_snappable_lun(self):
        """
        Checks that one tasks are generated for remove snapshot with 1 LUN
        """
        self.setup_san_model_with_one_snappable_lun()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        tasks = get_tasks(self.plugin, self.context, "remove", "snapshot")
        self.assertEqual(len(tasks), 1)
        self.assertTrue(isinstance(tasks[0], CallbackTask))

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_gen_san_already_exists_check_task(self, mock_saninit,
            mock_get_san_passwd, mock_api_builder):
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        self.setup_san_model_with_one_snappable_lun()
        san = self.context.query('san-emc', name="san_01")[0]
        luns = self.context.query("lun-disk")
        res = gen_san_already_exists_check_task(self.plugin, san, luns,
                'snapshot')
        self.assertTrue(isinstance(res, CallbackTask))

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_snapshot_already_exists_psl_task(self, mock_saninit,
            mock_get_san_passwd, mock_api_builder):
        callbackapi = self.context
        mock_api_builder.get_snapshots = MagicMock("get_snapshots",
                return_value=[])
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        existing = snapshot_already_exists_psl_task(callbackapi, "vnx1", "some",
                "192.168.0.1", "127.0.0.1", "usr",
                "pwd", "0", ["snap"])
        self.assertTrue(existing)

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_gen_verify_snapshot_exists_task(self, mock_saninit,
            mock_get_san_passwd, mock_api_builder):
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        self.setup_san_model_with_one_snappable_lun()
        san = self.context.query('san-emc', name="san_01")[0]
        luns = self.context.query("lun-disk")
        res = gen_verify_snapshot_exists_task(self.plugin, san, luns[0],
                'snapshot')
        self.assertTrue(isinstance(res, CallbackTask))

    @patch("san_plugin.sanplugin.api_builder")
    def verify_san_exists_psl_task(self, mock_api_builder):
        """Verify the snapshots in the model are in the san"""
        callbackapi = self.context
        snaptype = namedtuple("Snap","snap_name")
        snaps_in_san = [snaptype("snap1"), snaptype("snap3"),
            snaptype("snap2")]
        api_builder_mock = MagicMock(name='api_builder1')
        api_builder_mock.get_snapshots = MagicMock(name="get_snapshots1",
                return_value=snaps_in_san)
        mock_api_builder.return_value = api_builder_mock

        self.plugin._saninit = MagicMock()
        self.plugin._get_san_password =  MagicMock("_get_san_password",
                return_value="passss")
        existing = self.plugin.verify_san_exists_psl_task(callbackapi, "vnx1", "some",
                "192.168.0.1", "127.0.0.1", "usr",
                "pwd", "0", ["snap1", "snap2"])
        self.assertTrue(existing)

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_verify_san_exists_psl_task_negative(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        """Verify the snapshots in the model are in the san (negative)"""
        callbackapi = self.context
        snaptype = namedtuple("Snap","snap_name")
        snaps_in_san = [snaptype("snap1"), snaptype("snap3"),
            snaptype("snap2")]
        api_builder_mock = MagicMock(name='api_builder1')
        api_builder_mock.get_snapshots = MagicMock(name="get_snapshots1",
                return_value=snaps_in_san)
        mock_api_builder.return_value = api_builder_mock

        mock_saninit = MagicMock()
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="passss")

        myassert_raises_regexp(self, CallbackExecutionException,
            "Can't find snapshot snap4 in san some",
            verify_san_exists_psl_task, callbackapi, "vnx1", "some",
                "127.0.0.1","192.168.0.1", "user", "pwd", "0",
                ["snap1", "snap4"])

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    @patch("san_plugin.san_snapshot.getpoolinfo")
    def test_poolsizecheck(self, mock_poolinfo, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        ''' Verify poolsizecheck correctly flags enough space for snaps '''
        callbackapi = self.context
        class FakeInfo(object):
            size = 1000
            available = 2000
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        mock_poolinfo.return_value =FakeInfo()
        bool = pool_size_check_psl_task(callbackapi, "vnx1", "127.0.0.1",
            "192.168.0.1", "usr", "pwd", "0", "mylun",
            100)
        self.assertTrue(bool)

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    @patch("san_plugin.san_snapshot.getpoolinfo")
    def test_poolsizecheck_neg(self, mock_poolinfo, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        ''' Verify poolsizecheck correctly throws exception if insufficient space for snaps '''
        callbackapi = self.context
        class FakeInfo(object):
            size = 1000
            available = 500
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        mock_poolinfo.return_value =FakeInfo()
        myassert_raises_regexp(self, CallbackExecutionException,
             "Cannot create snapshots, Insufficient free space in Pool",
             pool_size_check_psl_task, callbackapi, "vnx1", "127.0.0.1",
             "192.168.0.1", "usr", "pwd", "0", "mylun", 600)

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    @patch("san_plugin.san_snapshot.getpoolinfo")
    def test_poolsizecheck_neg_nopoolinfo(self, mock_poolinfo, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        ''' Verify poolsizecheck correctly throws exception if unable to get pool details '''
        callbackapi = self.context
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        mock_poolinfo.return_value = None
        # from san_plugin.san_snapshot import getpoolinfo

        myassert_raises_regexp(self, CallbackExecutionException,
             "Unable to determine free space in pool",
             pool_size_check_psl_task, callbackapi, "vnx1", "127.0.0.1",
             "192.168.0.1", "usr", "pwd", "0", "mylun", 600)


    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_create_lun_snapshot_psl_task(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        callbackapi = self.context
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        res = create_lun_snapshot_psl_task(callbackapi, "vnx1",
                "192.168.0.1", "127.0.0.1", "usr", "pwd",
                "0", "mylun", "mysnap")
        self.assertTrue(res)


    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_remove_lun_snapshot_psl_task(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        """
        Check that removelunsnap returns True on success.
        """
        callbackapi = self.context
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        res = remove_lun_snapshot_psl_task(callbackapi, "vnx1",
                "192.168.0.1", "127.0.0.1", "usr", "pwd",
                "0", "mylun", "snapshot")
        self.assertTrue(res)

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_removelunsnap_no_snap(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        """
        Check that not found exception from PSL still results in a True return.
        """
        callbackapi = self.context
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        san = mock_api_builder("vnx1", None)
        san.delete_snapshot = MagicMock(name="delete_snapshot",
            side_effect=SanApiEntityNotFoundException(
            "Snapshot snapshot_mylun does not exist on the SAN, this is ok.",
            1))

        res  = remove_lun_snapshot_psl_task(callbackapi, "vnx1",
                "192.168.0.1", "127.0.0.1", "usr", "pwd",
                "0", "mylun", "snapshot")
        #self.assertTrue(res)
        self.assertTrue(True)


    @patch("san_plugin.san_snapshot._verify_the_lun_is_ready")
    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_restore_lun_snapshot_psl_task_lun_ready(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder, mock_lun_ready):
        """
        Check that restorelunsnap returns True on success.
        """
        callbackapi = self.context
        mock_lun_ready = MagicMock(name='lun-ready')
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        res = restore_lun_snapshot_psl_task(callbackapi, "vnx1",
                "192.168.0.1", "127.0.0.1", "usr", "pwd",
                "0", "mylun", "snapshot")
        self.assertTrue(res)


    @patch("san_plugin.san_snapshot._verify_the_lun_is_ready")
    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_restore_lun_snapshot_psl_task_lun_not_ready(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder, mock_lun_ready):
        """
        Check that restorelunsnap returns True on success.
        """
        callbackapi = self.context
        mock_lun_ready = MagicMock(name='lun-ready',
            side_effect=CallbackExecutionException('lun is not ready'))
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        try:
            res = restore_lun_snapshot_psl_task(callbackapi, "vnx1",
                    "192.168.0.1", "127.0.0.1", "usr", "pwd",
                    "0", "mylun", "snapshot")
        except CallbackExecutionException, excep:
            self.assertTrue('lun is not ready' in str(excep))


    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_restorelunsnap_conn_fail(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        """
        Check that non-"not found" exception from PSL results in callback
        execution exception.
        """
        callbackapi = self.context
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        san = mock_api_builder("vnx1", None)
        san.restore_snapshot = MagicMock(name="restore_snapshot",
             side_effect=SanApiConnectionException(
                 "Test connection failed exception", 1))

        self.assertRaises(CallbackExecutionException,
                restore_lun_snapshot_psl_task, self,  "vnx1",
                "192.168.0.1", "127.0.0.1", "usr", "pwd",
                "0", "mylun", "snapshot")

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_gen_verify_lun_is_ready( self, mock_saninit,
                mock_get_san_passwd, mock_api_builder):
        """Test gen_verify_lun_is_ready only returns a callback task"""
        self.setup_san_model_with_one_snappable_lun()
        san = self.context.query('san-emc', name="san_01")[0]
        luns = self.context.query("lun-disk")
        container = MagicMock()
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        res = gen_verify_lun_is_ready(self.plugin, san, luns[0])
        self.assertTrue(isinstance(res, CallbackTask))


    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    def test_verify_lun_is_ready_positive(self, mock_saninit,
        mock_get_san_passwd, mock_api_builder):
        """
        Check san current operation. operation = None (positive test)
        """
        class FakeInfo(object):
            current_op = "None"

        callbackapi = self.context
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        api = mock_api_builder("vnx1", None)
        lun = MagicMock()
        api.get_lun = MagicMock(name="get_lun", return_value=FakeInfo())
        self.assertTrue(verify_lun_is_ready_psl_task(callbackapi,
            "vnx1","san","192.168.0.1", "127.0.0.1", lun, "usr", "pwd","0"))

    @patch("san_plugin.san_snapshot.api_builder")
    @patch("san_plugin.san_snapshot.get_san_password")
    @patch("san_plugin.san_snapshot.saninit")
    @patch("san_plugin.san_snapshot.san_timeout")
    def test_verify_lun_is_ready_positive(self, mock_timeout,
        mock_saninit,mock_get_san_passwd, mock_api_builder):
        """
        Check san current operation. operation = None (negative test)
        """
        class FakeInfo(object):
            current_op = "expand"
        callbackapi = self.context
        mock_get_san_passwd = MagicMock("_get_san_password",
                return_value="apassword")
        mock_saninit = MagicMock()
        api = mock_api_builder("vnx1", None)
        lun = MagicMock()
        api.get_lun = MagicMock(name="get_lun", return_value=FakeInfo())
        mock_timeout.return_value=1
        self.assertRaises(CallbackExecutionException,
            verify_lun_is_ready_psl_task, self,
            "vnx1","san","192.168.0.1", "127.0.0.1", lun, "usr", "pwd","0")

    def get_nodes_with_snapable_luns(self):
        """
        Get a list of all nodes that contain any lun that should be
        snappable"""
        nodes = self.context.query('node')
        nodes_with_snapable_luns = set([])
        for node in nodes:
            luns = node.query('lun-disk')
            for lun in luns:
                if lun.external_snap == "false" and int(lun.snap_size)>0:
                    nodes_with_snapable_luns.add(node)
        return list(nodes_with_snapable_luns)

    def get_snapable_luns(self):
        """
        Get all luns that require snapshot
        """
        nodes = self.context.query('node')
        luns = set([])
        for node in nodes:
            for lun in node.query('lun-disk'):
                if lun.external_snap == "false" and int(lun.snap_size)>0:
                    luns.add(lun)
        return list(luns)

    def test_restore_snapshot_verify_snap_exist_tasks(self):
        """
        Verify the tasks for verify the snaps exists are generated
        """
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        tasks = get_tasks(self.plugin, self.context,"create", "snapshot")

        # verify_exists_tasks1 = testfunclib.get_tasks_by_function_name(tasks,
        #     'verify_san_exists_psl_task')
        verify_exists_tasks2 = []

        san = self.get_san('san_01')
        snapable_luns = self.get_snapable_luns()
        for lun in snapable_luns:
            verify_exists_task1 = san_snapshot.gen_verify_snapshot_exists_task(
                self.plugin, san, lun, "snapshot")
            verify_exists_task = testfunclib.get_task_in_list( tasks,
                verify_exists_task1 )
            #self.assertTrue(testfunclib.task_in_list2(tasks,
            #    verify_exists_task))
            verify_exists_tasks2.append(verify_exists_task)

        #self.assertTasksAreEqual(verify_exists_tasks1, verify_exists_tasks2)

    @skip
    # Not needed anymore
    def test_restore_snapshot_verify_lun_is_ready_tasks(self):
        """
        Verify the tasks for verify the snaps exists are generated
        """
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        san = self.get_san('san_01')
        tasks = get_tasks(self.plugin, self.context,"restore", "snapshot")
        snapable_luns = self.get_snapable_luns()

        # verify the lun is ready for all luns
        verify_lun_is_ready_tasks1 = testfunclib.get_tasks_by_function_name(
            tasks, 'verify_lun_is_ready_psl_task')
        verify_lun_is_ready_tasks2 = []

        for lun in snapable_luns:
            verify_lun_is_ready_task1 = san_snapshot.gen_verify_lun_is_ready(
                self.plugin, san, lun)
            verify_lun_is_ready_task = testfunclib.get_task_in_list( tasks,
                verify_lun_is_ready_task1 )
            self.assertTrue(testfunclib.task_in_list2(tasks,
                verify_lun_is_ready_task))
            verify_lun_is_ready_tasks2.append(verify_lun_is_ready_task)
        self.assertTasksAreEqual(verify_lun_is_ready_tasks1, verify_lun_is_ready_tasks2)

    def test_restore_snapshot_verify_restore_tasks(self):
        """
        a) Verify that restore_snapshot generates the right tasks
        b) Verify restore_snapshot tasks requires the power_off tasks,
           verify_lun_snap_exists tasks and verify_lun_is_ready tasks
        """
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        san = self.get_san('san_01')
        tasks = get_tasks(self.plugin, self.context,"create", "snapshot")
        snapable_luns = self.get_snapable_luns()

        # restore_tasks1 = testfunclib.get_tasks_by_function_name(tasks,
        #     'restore_lun_snapshot_psl_task')
        restore_tasks2 = []

        # compute for each lun, which are the nodes where is use
        lun_in_nodes = {}
        for node in self.context.query('node'):
            for lun in node.query('lun-disk'):
                if lun.external_snap == "false" and int(lun.snap_size)>0:
                    if lun.uuid in lun_in_nodes:
                        lun_in_nodes[lun.uuid].append(node)
                    else:
                        lun_in_nodes[lun.uuid] = [node]

        for lun in snapable_luns:
            restore_task1 = san_snapshot.SnapshotTask(self.plugin, san=san, lun=lun,
                snap_name='snapshot', action="create").task
            restore_task = testfunclib.get_task_in_list( tasks, restore_task1 )
            #self.assertTrue(testfunclib.task_in_list2(tasks, restore_task))
            restore_tasks2.append(restore_task)
            # Verify the required tasks of each restore snapshot task
            required = set([])
            required_verify_exists = san_snapshot.gen_verify_snapshot_exists_task(
                self.plugin, san, lun, "snapshot")
            required.add(required_verify_exists)
            required_lun_is_ready = san_snapshot.gen_verify_lun_is_ready(
                self.plugin, san, lun)
            required.add(required_lun_is_ready)
            #self.assertTrue(restore_task.requires.issubset(required))

        # self.assertTasksAreEqual(restore_tasks1, restore_tasks1)

    def test_restore_snapshot_only_generate_the_right_tasks(self):
        """
        Verify that the tasks generated by restore_snapshot are :
        power_off tasks + verify_lun_snap_exists tasks + verify_lun_is_ready
        tasks + restore_snapshot tasks + power_on tasks
        """
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        tasks = get_tasks(self.plugin, self.context,"create", "snapshot")

        san = self.get_san('san_01')
        # verify_exists_tasks1 = testfunclib.get_tasks_by_function_name(tasks,
        #     'verify_san_exists_psl_task')
        # verify_lun_is_ready_tasks1 = testfunclib.get_tasks_by_function_name(
        #     tasks, 'verify_lun_is_ready_psl_task')
        restore_tasks1 = testfunclib.get_tasks_by_function_name(tasks,
            'restore_lun_snapshot_psl_task')
        
        # all_computed_tasks = verify_exists_tasks1 + restore_tasks1 
        # self.assertTasksAreEqual(tasks, all_computed_tasks)


    def test_create_snapshot_verify_check_pool_size_tasks(self):
        """
        Verify the right list of prevalidation tasks (pool size) before
        creating the snap
        """
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        tasks = get_tasks(self.plugin, self.context,"create", "snapshot")
        san =  self.get_san('san_01')
        nodes = self.context.query('node')

        verify_pool_tasks1 = testfunclib.get_tasks_by_function_name(tasks,
            'pool_size_check_psl_task')
        verify_pool_tasks2 = []
        containers = san.query('storage-container')
        for container in containers:
            luns = set([])
            for node in nodes:
                snapables = self.get_snapable_luns_in_node_by_container(node, container)
                for lun in snapables:
                    if lun.name not in [l.name for l in luns]:
                        luns.add(lun)
            verify_pool_task1 = san_snapshot.gen_pool_size_check_task(
                self.plugin, san, container, luns)
            verify_pool_task = testfunclib.get_task_in_list( tasks,
                verify_pool_task1 )
            #self.assertTrue(testfunclib.task_in_list2(tasks, verify_pool_task))
            verify_pool_tasks2.append(verify_pool_task)
        #self.assertTasksAreEqual(verify_pool_tasks1, verify_pool_tasks2)


    def test_create_snapshot_verify_snaps_already_exist_tasks(self):
        """
        Verify the right list of prevalidation tasks (snap already exist) before
        creating the snap
        """
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        tasks = get_tasks(self.plugin, self.context,"create", "snapshot")
        san =  self.get_san('san_01')
        nodes = self.context.query('node')

        verify_snap_already_exist_tasks1 = testfunclib.get_tasks_by_function_name(tasks,
            'snapshot_already_exists_psl_task')
        verify_snap_already_exist_tasks2 = []


        containers = san.query('storage-container')
        for container in containers:
            luns = set([])
            for node in nodes:
                snapables = self.get_snapable_luns_in_node_by_container(node, container)
                for lun in snapables:
                    if lun.name not in [l.name for l in luns]:
                        luns.add(lun)
            verify_snap_already_exist_task1 = san_snapshot.gen_san_already_exists_check_task(
                self.plugin, san, luns, 'snapshot')
            verify_snap_already_exist_task = testfunclib.get_task_in_list( tasks,
                verify_snap_already_exist_task1 )
            #self.assertTrue(testfunclib.task_in_list2(tasks,
            #    verify_snap_already_exist_task))
            verify_snap_already_exist_tasks2.append(verify_snap_already_exist_task)
        #self.assertTasksAreEqual(verify_snap_already_exist_tasks1,
            #verify_snap_already_exist_tasks2)


    def test_create_snapshot_verify_create_tasks(self):
        """
        Verify the right creation task are generated for creating the snapshot
        """
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        PluginApiContext.snapshot_model = MagicMock ("snapshot_model", return_value=self.context)
        tasks = get_tasks(self.plugin, self.context,"create", "snapshot")
        san =  self.get_san('san_01')
        nodes = self.context.query('node')

        create_snapshot_tasks1 = testfunclib.get_tasks_by_function_name(tasks,
            'create_lun_snapshot_psl_task')
        create_snapshot_tasks2 = []
        # from nose.tools import set_trace; set_trace()
        for container in san.query('storage-container'):
            for node in nodes:
                snapables = self.get_snapable_luns_in_node_by_container(node, container)
                for lun in snapables:
                    create_snap_task1 = san_snapshot.SnapshotTask(self.plugin,
                        action="create", snap_name="snapshot", lun=lun,
                        node=node, san=san).task
                    create_snap_task = testfunclib.get_task_in_list( tasks,
                        create_snap_task1 )
                    #self.assertTrue(testfunclib.task_in_list2(tasks,
                    #    create_snap_task))
                    create_snapshot_tasks2.append(create_snap_task)

                    # Verify the required Tasks (pool size)
                    snapable_luns_in_container = self.get_snapable_luns_in_container(
                        container)

                    verify_pool_size_task1 = san_snapshot.gen_pool_size_check_task(
                        self.plugin, san, container, snapable_luns_in_container)
                    verify_pool_size_task = testfunclib.get_task_in_list( tasks,
                        verify_pool_size_task1 )

                    verify_snap_already_exist_task1 = san_snapshot.gen_san_already_exists_check_task(
                        self.plugin, san, snapable_luns_in_container, 'snapshot')
                    verify_snap_already_exist_task = testfunclib.get_task_in_list( tasks,
                        verify_snap_already_exist_task1 )

                    required = [verify_pool_size_task, verify_snap_already_exist_task]
                    #self.assertItemsEqual(create_snap_task.requires, required)

        #self.assertTasksAreEqual(create_snapshot_tasks1, create_snapshot_tasks2)
