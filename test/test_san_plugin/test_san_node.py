import sys
from mock import patch, Mock, MagicMock
from testfunclib import skip

from litp.core.plugin_context_api import PluginApiContext
from litp.core.execution_manager import CallbackExecutionException
from sanapi.sanapiexception import SanApiException, \
SanApiEntityNotFoundException, SanApiEntityAlreadyExistsException, \
SanApiConnectionException
from sanapi.sanapiinfo import LunInfo, HbaInitiatorInfo, HluAluPairInfo, \
StorageGroupInfo, StoragePoolInfo, SnapshotInfo
from litp.core.task import CallbackTask

from san_plugin.san_node import generate_node_tasks_after_expanding_luns
from san_plugin.san_node import scan_scsi_device_dmp_task
from san_plugin.san_node import scan_scsi_device_mpath_task
import testfunclib
from san_plugin.san_utils import normalise_to_megabytes

class TestSanNode(testfunclib.BasicTestSan):
    def setUp(self):
        testfunclib.BasicTestSan.setUp(self)

    def add_dmp_cluster(self, name, id):
        self.add_vcs_cluster(name, cluster_id=id, cluster_type="vcs")

    def add_mpath_cluster(self, name, id):
        self.add_vcs_cluster(name, cluster_id=id, cluster_type="sfha")        


    def test_generate_node_tasks_after_expanding_luns_no_tasks(self):
        """generate_node_tasks_after_expanding_luns if lun_updated_tasks=[]"""
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        tasks = generate_node_tasks_after_expanding_luns(self.plugin, 
            self.context, [])
        self.assertEqual(len(tasks),0)

    def test_generate_node_tasks_after_expanding_luns_dmp(self):
        """dmp: generate_node_tasks_after_expanding_luns if lun_updated_tasks=[]"""
        # expand one lun in the dmp-node
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        # from nose.tools import set_trace; set_trace()
        san = self.context.query('san-emc', name='san_01')[0]
        storage_container = self.context.query('storage-container', 
            name='pool01')[0]

        dmp_node = self.context.query_by_vpath(
            '/deployments/local/clusters/cluster-dmp/nodes/node3')
        lun0 =  dmp_node.query('lun-disk')[0]
        lun0._model_item._applied_properties['size']=testfunclib.inc_size(
            lun0.size, 1024)
        lun0._model_item.set_updated()
        
        # get the update-lun tasks
        # upd_tasks = self.plugin._create_updated_luns_tasks(self.context)
        upd_tasks = self.plugin._gen_update_lun_tasks(lun0, san, 
            storage_container)

        node_tasks = generate_node_tasks_after_expanding_luns(self.plugin,
            self.context, upd_tasks)
        self.assertEqual(len(node_tasks),1)
        self.assertEqual(node_tasks[0].callback,self.plugin.callback_function)
        self.assertEqual(node_tasks[0].kwargs, 
            {'module_name': 'san_plugin.san_node', 
            'function_name': 'scan_scsi_device_dmp_task'})

    def test_generate_node_tasks_after_expanding_luns_mpath(self):
        """mpath: generate_node_tasks_after_expanding_luns if lun_updated_tasks=[]"""
        # expand one lun in the dmp-node
        self.setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps()
        mpath_node = self.context.query_by_vpath(
            '/deployments/local/clusters/cluster-mpath/nodes/node4')
        lun0 =  mpath_node.query('lun-disk')[0]
        san = self.context.query('san-emc', name='san_01')[0]
        storage_container = self.context.query('storage-container', 
            name='pool01')[0]
        # for st in san.storage_containers:
        #    storage_container = st
        #    break

        lun0._model_item._applied_properties['size']=testfunclib.inc_size(
            lun0.size, 1024)
        lun0._model_item.set_updated()
                
        # get the update-lun tasks
        # upd_tasks = self.plugin._create_updated_luns_tasks(self.context)
        
        upd_tasks = self.plugin._gen_update_lun_tasks(lun0, san, 
            storage_container)

        # from nose.tools import set_trace; set_trace()
        node_tasks = generate_node_tasks_after_expanding_luns(self.plugin,
            self.context, upd_tasks)
        self.assertEqual(len(node_tasks),1)
        self.assertEqual(node_tasks[0].callback,self.plugin.callback_function)
        self.assertEqual(node_tasks[0].kwargs, 
            {'module_name': 'san_plugin.san_node', 
            'function_name': 'scan_scsi_device_mpath_task'})

    @skip
    def test_scan_scsi_device_mpath_task_ok(self, mock_mco):

        mock_mco.side_effect = MagicMock(name='mco')
        api_mock = MagicMock(name='api')
        self.assertTrue(scan_scsi_device_mpath_task(api_mock, 'node'))

    @skip
    def test_scan_scsi_device_mpath_task_mco_fail(self, mock_mco_api):
        
        mock_mco = MagicMock(name='mco')
        mock_mco.scan_scsi_device_mpath = MagicMock('mco-scan', 
            side_effect= Exception('Failed to scan scsi node'))
        mock_mco_api.return_value = mock_mco

        api_mock = MagicMock(name='api')
        # from nose.tools import set_trace; set_trace()
        try:
            r = scan_scsi_device_mpath_task(api_mock, 'node')
            self.fail()
        except CallbackExecutionException, msg:
            self.assertTrue('Failed to scan scsi ' in str(msg))


    @skip
    def test_scan_scsi_device_dmp_task_mco_fail(self, mock_mco_api):
        mock_mco = MagicMock(name='mco')
        mock_mco.scan_scsi_device_dmp = MagicMock('mco-scan', 
            side_effect= Exception('Failed to scan scsi node'))
        mock_mco_api.return_value = mock_mco

        api_mock = MagicMock(name='api')
        # from nose.tools import set_trace; set_trace()
        try:
            r = scan_scsi_device_dmp_task(api_mock, 'node')
            self.fail()
        except CallbackExecutionException, msg:
            self.assertTrue('Failed to scan scsi ' in str(msg))
