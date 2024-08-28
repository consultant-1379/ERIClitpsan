'''
Created on 15 Jul 2014

Common functions for unit test code

@author: edavmax
'''


import re
import unittest
from mock import patch, Mock, MagicMock

from sanapi.sanapiinfo import *
from sanapi.sanapiexception import *
import os
from litp.core.execution_manager import CallbackExecutionException

from san_plugin.sanplugin import SanPlugin
from sanapi.sanapi import api_builder
from sanapi.sanapiexception import SanApiException, \
SanApiEntityNotFoundException, SanApiEntityAlreadyExistsException, \
SanApiConnectionException
from sanapi.sanapiinfo import LunInfo, HbaInitiatorInfo, HluAluPairInfo, \
StorageGroupInfo, StoragePoolInfo, SnapshotInfo
from san_extension.sanextension import SanExtension
from litp.core.plugin_context_api import PluginApiContext
from network_extension.network_extension import NetworkExtension
from vcs_extension.vcs_extension import VcsExtension
from volmgr_extension.volmgr_extension import VolMgrExtension
from litp.extensions.core_extension import CoreExtension
from bmc_extension.bmc_extension import BmcExtension

from litp.core.model_manager import ModelManager
from litp.core.plugin_manager import PluginManager
from litp.core.model_type import ItemType, Child
from litp.core.model_item import ModelItem
from litp.core.execution_manager import CallbackExecutionException
from san_plugin.san_validate import SanPluginValidator

from inspect import getargspec
from litp.core.task import CallbackTask
# from litp.core.execution_manager import CallbackTask
# import unittest2 as unittest
import unittest
from collections import namedtuple
from san_plugin.san_utils import normalise_to_megabytes
#
# from san_plugin.san_utils import get_balancing_sp, hba_port_list, \
# get_bg as get_bg_san_utils, toggle_sp, get_lun_names_for_bg
#
# from san_plugin.san_utils import cmp_values, values_are_equal, \
# get_ip_for_node, saninit
#
# from san_plugin.san_validate import SanPluginValidator
# from bmc_extension.bmc_extension import BmcExtension
# import testfunclib
# from san_plugin import san_power_control
# from san_plugin import san_snapshot

# -----------------------------------------------------
# DECORATORS


# Decorator for 2.6 to implement unittest.skip @unittest.skip("")
def skip(func):
    return



def singleton(cls):
    '''
    :param cls:
    '''

    def getinstance():
        '''
        getinstance()
        '''
        if cls not in singleton.instances:
            singleton.instances[cls] = cls()
        return singleton.instances[cls]
    return getinstance

singleton.instances = {}


# -----------------------------------------------------
# FUNCTIONS


def myassert_raises_regexp(tstobj, exceptiontype, message, function, *args, **kwargs):
    '''
    implementation of AssertRaisesRegexp for 2.6 (AssertRaisesRegexp was added to 2.7)

    '''
    try:
        function(*args, **kwargs)
    except exceptiontype as e:
        if not re.search(message, e.args[0]):
            tstobj.fail("Exception " + str(exceptiontype) + " does not contain expected message " + message + \
                           ". Contents of exception:" + e.args[0])
    except:
        tstobj.fail("No Exception of type " + str(exceptiontype) + " raised")
    else:
        tstobj.fail("No Exception of any type raised")



def myassert_is_instance(tstobj, objtotest, classname):
    """
    Implementation of assertIsInstance (which is available in 2.7)
    """
    cname = classname.__name__
    oname = objtotest.__class__.__name__

    if oname != cname:
        tstobj.fail("Object is type %s, should be %s" % (oname, cname))

def myassert_in(tstobj, first, second, msg):
    """
    Implementation of assertIn from 2.7
    """
    success = False
    for item in second:
        if first == item:
            success = True
            break

    if success == False:
        tstobj.fail(msg)

def validate_ipv4(addr):
    '''
    Function to validate ipv4 address
    Arguments: ipv4 address as string
    Returns: True or False
    '''
    if not addr:
        return False
    octets = addr.split('.')
    if len(octets) != 4:
        return False
    for num in octets:
        if not num.isdigit():
            return False
        num = int(num)
        if num < 0 or num > 255:
            return False
    return True


class ItemMock(MagicMock):
    """
    basic item functionality
    """
    def __init__(self, name,  **kwargs):
        MagicMock.__init__(self, **kwargs)
        self.name = name
    def get_vpath(self):
        return self.name


class LunMock(ItemMock):
    """mock a lun disk

    Attributes:
        name: the name of the lun
        [properties]: dynamic list of properties to be created in __init__,
           depending of dict properties
        applied_properties: a dict with the values in the model before
           "update"
        is_applied: boolean indicatin if the lun is in state Applied
        is_updated: boolean indicatin if the lun is in state Updated
        is_initial: boolean indicatin if the lun is in state Initial
        is_for_removal: boolean indicatin if the lun is in state ForRemoval

    """
    def __init__(self, name, properties={}, applied_properties={},
        is_updated=True, is_applied=False, is_initial=False,
        is_for_removal=False, **kwargs ):
        """initialize the mocked lun

        Arguments:
            name: the name of the lun
            properties: a dict with the properties and its corresponding
               values for the lun
            applied_properties: a dict with the property values before update
            states: a dict with the states of the lun

        ex:
           lun1 = LunMock('lun1',
              properties={'size':'10M'},
              applied_properties={'size' : '9M'},
              states={'is_updated': True })

        """
        ItemMock.__init__(self, name, **kwargs)
        for f in properties:
            self.__dict__[f]= properties[f]

        self.applied_properties = applied_properties
        self.lun_name = self.name
        self.is_initial = MagicMock(return_value=is_initial)
        self.is_updated = MagicMock(return_value=is_updated)
        self.is_applied = MagicMock(return_value=is_applied)
        self.is_for_removal = MagicMock(return_value=is_for_removal)
        self.get_cluster = MagicMock(return_value=None)
        self.item_type_id = "lun-disk"


class NodeMock(ItemMock):
    """
    mock a node
    """
    def __init__(self, name, **kwargs):
        ItemMock.__init__(self, name, **kwargs)
        self.system = MagicMock()
        self.system.disks = MagicMock()
        self.luns = []
        self.system.disks.query = MagicMock(side_effect=self.query_mock)
        self.get_vpath = lambda: self.name
    def query_mock(self, _type, storage_container=None):
        if _type == "lun-disk":
            return self.luns
    def add_lun(self, mock_lun):
        self.luns.append(mock_lun)
    def add_luns(self, list_of_luns):
        for lun in list_of_luns:
            self.add_lun(lun)


class SanMock(ItemMock):
    def __init__(self, name, properties={}, applied_properties={},
        is_updated=True, is_applied=False, is_initial=False,
        is_for_removal=False, **kwargs ):
        """initialize the mocked SAN

        Arguments:
            name: the name of the SAN
            properties: a dict with the properties and its corresponding
               values for the SAN
            applied_properties: a dict with the property values before update
            states: a dict with the states of the SAN
        """
        ItemMock.__init__(self, name, **kwargs)
        for f in properties:
            self.__dict__[f]= properties[f]

        self.applied_properties = applied_properties
        self.san_name = self.name
        self.is_initial = MagicMock(return_value=is_initial)
        self.is_updated = MagicMock(return_value=is_updated)
        self.is_applied = MagicMock(return_value=is_applied)
        self.is_for_removal = MagicMock(return_value=is_for_removal)
        self.get_cluster = MagicMock(return_value=None)
        self.item_type_id = "san-emc"
        self.storage_containers = []

    def add_storage_container(self, storage):
        self.storage_containers.append(storage)


class StorageContainerMock(ItemMock):
    """
    mock a storage container
    """
    def __init__(self, name, **kwargs):
        ItemMock.__init__(self, name, **kwargs)
        self.nodes = []
    def add_node(self, node):
        self.nodes.append(node)
    def query(self, _type):
        if _type == "node":
            return self.nodes

class SanPluginContextMock(MagicMock):
    """
    mock the full api context
    """
    def __init__(self, **kwargs):
        MagicMock.__init__(self, **kwargs)
        self.sans = []
    def query(self, _type):
        if _type=="lun-disk":
            luns = []
            for node in self.query('node'):
                luns += node.luns
            return luns
        if _type == "node":
            nodes = []
            for san in self.sans:
                for st in san.storage_containers:
                    nodes += st.query('node')
            ret = nodes
        elif _type == "san-emc":
            ret = self.sans
        elif _type == "vcs-cluster":
            ret = []
        else:
            ret = None
        return ret
    def add_san(self, san):
        self.sans.append(san)
    def add_storage(self, san_name, storage):
        for san in self.sans:
            if san.name == san_name:
                san.add_storage_container(storage)
    def add_node(self, storage_name, node):
        for san in self.sans:
            for st in san.storage_containers:
                if st.name == storage_name:
                    st.add_node(node)
    def get_node(self, node_name):
        for node in self.query('node'):
            if node.name == node_name:
                return node
    def get_san(self, san_name):
        for san in self.sans:
            if san.name == san_name:
                return san
    def add_lun(self, node_name, lun):
        node = self.get_node(node_name)
        node.add_lun(lun)

def get_tasks_by_function_name(tasks, function_name):
    return [task for task in tasks if task.kwargs['function_name']==function_name]

def get_task_in_list(tasks, function_name, model_item ):
    # from nose.tools import set_trace; set_trace()
    print "Checking : ",function_name,'-------------------'
    for task in tasks:
        if task.kwargs['function_name'] == function_name and \
            task.model_item == model_item:
            return task
    return None

def task_in_list(tasks, function_name, model_item):
    """
    check if a task is in the List
    """
    return True if get_task_in_list(tasks, function_name) else False

def nicetask2str(task):
    return "{0}\n-------------\n{1}-------------\n-------------".format(
        str(taskA.args), str(taskA.kwargs), str(taskA.model_item))

def task2str(task):
    return str(task.model_item)+str(task.args)+str(task.kwargs)

def equal_tasks(taskA, taskB):
    return task2str(taskA)==task2str(taskB)

def task_in_list2(list_of_tasks, a_task):
    return True if get_task_in_list(list_of_tasks, a_task) else False

def get_task_in_list(list_of_tasks, a_task):
    for task in list_of_tasks:
        if equal_tasks(task, a_task):
            return task


class BasicTestSan(unittest.TestCase):

    def setUp(self):
        """
        Construct a model, sufficient for test cases
        that you wish to implement in this suite.
        """
        self.model = ModelManager()
        self.plugin_manager = PluginManager(self.model)
        self.context = PluginApiContext(self.model)
        # Use add_property_types to add property types defined in
        # model extenstions
        # For example, from CoreExtensions (recommended)
        self.plugin_manager.add_property_types(
            CoreExtension().define_property_types())

        # Use add_item_types to add item types defined in
        # model extensions
        # For example, from CoreExtensions
        self.plugin_manager.add_item_types(
            CoreExtension().define_item_types())

        self.plugin_manager.add_property_types(
            SanExtension().define_property_types())
        self.plugin_manager.add_item_types(
            SanExtension().define_item_types())

        # need to add network item_types in unittests
        self.plugin_manager.add_property_types(
            NetworkExtension().define_property_types())
        self.plugin_manager.add_item_types(
            NetworkExtension().define_item_types())

        # need to add vcs item_types in unittests
        self.plugin_manager.add_property_types(
            VcsExtension().define_property_types())
        self.plugin_manager.add_item_types(
            VcsExtension().define_item_types())

        # need to add volmgr item_types in unittests
        self.plugin_manager.add_property_types(
            VolMgrExtension().define_property_types())
        self.plugin_manager.add_item_types(
            VolMgrExtension().define_item_types())

        # need to add bmc item_types in unittests
        self.plugin_manager.add_property_types(
            BmcExtension().define_property_types())
        self.plugin_manager.add_item_types(
            BmcExtension().define_item_types())

        # Add default minimal model (which creates '/' root item)
        self.plugin_manager.add_default_model()

        # Instantiate your plugin and register with PluginManager
        self.plugin = SanPlugin()
        self.plugin_manager.add_plugin('SanPlugin', 'sanplugin.sanplugin',
                                       '1.0.1-SNAPSHOT', self.plugin)

        self.plugin_validator = SanPluginValidator()

    def _add_item_to_model(self, *args, **kwargs):
        result = self.model.create_item(*args, **kwargs)
        self._assess_result(result)
        return result

    def _add_inherit_to_model(self, source_item_path, item_path, **properties):
        result = self.model.create_inherited(source_item_path, item_path,
                                             **properties)
        self._assess_result(result)
        return result

    def _assess_result(self, result):
        try:
            checks = [type(result) is list,
                      len(result),
                      type(result[0]) is ValidationError]
        except TypeError:  # result is not list
            pass
        except IndexError:  # result is empty list
            pass
        else:
            if all(checks):
                raise RuntimeError(repr(result[0]))

    def add_bmc(self, system_name, ipaddress, username, pkey):
        rsp = self.model.create_item("bmc",
            "/infrastructure/systems/{s}/bmc".format(s=system_name),
            ipaddress=ipaddress,
            username=username,
            password_key=pkey)
        self.assertFalse(isinstance(rsp, list), rsp)

    def get_node(self, hostname):
        nodes = self.context.query('node')
        for node in nodes:
            if node.hostname == hostname:
                return node

    def add_node(self, cluster_name, node_name, system_name, nwinfo):
        rsp = self.model.create_item("node",
                                      "/deployments/local/clusters/" +
                                      cluster_name + "/nodes/" +
                                      node_name,
                                      hostname=node_name)
        self.assertFalse(isinstance(rsp, list), rsp)
        self.model.create_inherited("/infrastructure/systems/" +
                     system_name,
                     "/deployments/local/clusters/" +
                     cluster_name + "/nodes/" +
                     node_name + "/system")
        self.model.create_inherited("/software/profiles/rhel",
                          "/deployments/local/clusters/" +
                          cluster_name + "/nodes/" +
                          node_name + "/os")
        self.model.create_inherited("/infrastructure/storage/storage_profiles/profile_1",
                          "/deployments/local/clusters/" +
                          cluster_name + "/nodes/" +
                          node_name + "/storage_profile")
        for nw in nwinfo:
            rsp = self.model.create_item("network-interface",
                                  "/deployments/local/clusters/" +
                                  cluster_name + "/nodes/" +
                                  node_name + "/network_interfaces/" + nw["if_name"],
                                  network_name=nw["network_name"],
                                  ipaddress=nw["ip"])
            self.assertFalse(isinstance(rsp, list), rsp)

    def get_san(self, san_name):
        sans = self.context.query('san-emc')
        for s in sans:
            if s.name == san_name:
                return s

    def add_san(self, san_name, san_type, ip_a, ip_b, san_username,
                san_password_key, login_scope, san_serial_number,
                storage_site_id, storage_network):
        optargs={
            "name":san_name,
            "san_type": san_type,
            "username": san_username,
            "password_key": san_password_key,
            "login_scope": login_scope,
            "san_serial_number": san_serial_number,
            "storage_site_id": storage_site_id,
            "storage_network": storage_network
        }

        if ip_a:
            optargs["ip_a"] = ip_a

        if ip_b:
            optargs["ip_b"] = ip_b

        rsp = self.model.create_item("san-emc",
                                     "/infrastructure/storage/storage_providers/" + \
                                     san_name,
                                     **optargs)
        self.assertFalse(isinstance(rsp, list), rsp)

    def add_raid_group(self, san_name, rg_id):
        # Add a raid group to the model
        rsp = self.model.create_item("storage-container",
              "/infrastructure/storage/storage_providers/" + san_name + \
              "/storage_containers/rgfen" + rg_id ,
                                    type="RAID_GROUP",
                                    name=rg_id)
        self.assertFalse(isinstance(rsp, list), rsp)

    def add_storage_pool(self, san_name, pool_name):
        # Add a storage container to the model
        rsp = self.model.create_item("storage-container",
              "/infrastructure/storage/storage_providers/" + san_name + \
              "/storage_containers/" + pool_name,
                                    type="POOL",
                                    name=pool_name)
        self.assertFalse(isinstance(rsp, list), rsp)

    def get_snapable_luns_in_node_by_container(self, node, container):
        return [ lun for lun in node.system.disks.query('lun-disk',
                         storage_container=container.name)
                     if lun.external_snap == "false" and
                        int(lun.snap_size)>0 ]

    def get_snapable_luns_in_container(self, container):
        container_luns = set([])
        nodes = self.context.query('node')
        for node in nodes:
            luns = self.get_snapable_luns_in_node_by_container(node, container)
            for lun in luns:
                container_luns.add(lun)
        return list(container_luns)


    def add_hbas(self, system_name, hba_info):
        # adds the HBA ports to the system
        for hba in hba_info:
            optargs=dict()
            count=0
            for wwn in hba_info[hba][:2]:
                if wwn:
                    if count == 0:
                        prop_name = "hba_porta_wwn"
                    else:
                        prop_name = "hba_portb_wwn"
                    count += 1
                    optargs[prop_name] = wwn

            rsp = self.model.create_item("hba",
                                          "/infrastructure/systems/" +
                                          system_name +
                                          "/controllers/" + hba,
                                          failover_mode="std",
                                          **optargs)
            self.assertFalse(isinstance(rsp, list), rsp)

    def get_lun_disk(self, system_name, lun_name):
        node = self.get_node(system_name)
        luns = self.context.query('lun-disk')
        for lun in luns:
            if lun.lun_name == lun_name:
                return lun

    def add_lun_disk(self, system_name, model_name, lun_name, dev_name, size, container,
                    bootable, shared, uuid=None, external_snap=None, snap_size=None, bg=None):
        # Add a lun disk

        if bg == None:
            if external_snap is not None or snap_size is not None:
                rsp = self.model.create_item("lun-disk",
                                           "/infrastructure/systems/" + system_name + \
                                           "/disks/" + model_name,
                                           lun_name = lun_name,
                                           uuid=uuid,
                                           name = dev_name,
                                           size = size,
                                           storage_container = container,
                                           bootable = bootable,
                                           shared = shared,
                                           external_snap = external_snap,
                                           snap_size = snap_size
                                             )
            else:
                rsp = self.model.create_item("lun-disk",
                                           "/infrastructure/systems/" + system_name + \
                                           "/disks/" + model_name,
                                           lun_name = lun_name,
                                           uuid=uuid,
                                           name = dev_name,
                                           size = size,
                                           storage_container = container,
                                           bootable = bootable,
                                           shared = shared)
        else:
            if external_snap is not None or snap_size is not None:
                rsp = self.model.create_item("lun-disk",
                                           "/infrastructure/systems/" + system_name + \
                                           "/disks/" + model_name,
                                           lun_name = lun_name,
                                           uuid=uuid,
                                           name = dev_name,
                                           size = size,
                                           storage_container = container,
                                           bootable = bootable,
                                           shared = shared,
                                           external_snap = external_snap,
                                           snap_size = snap_size,
                                           balancing_group = bg
                                             )
            else:
                rsp = self.model.create_item("lun-disk",
                                           "/infrastructure/systems/" + system_name + \
                                           "/disks/" + model_name,
                                           lun_name = lun_name,
                                           uuid=uuid,
                                           name = dev_name,
                                           size = size,
                                           storage_container = container,
                                           bootable = bootable,
                                           shared = shared,
                                           balancing_group = bg
                                             )

        self.assertFalse(isinstance(rsp, list), rsp)

    def add_fen_lun_disk(self, cluster_name, model_name, lun_name,
                         dev_name, size, container,
                         bootable, shared, uuid):
        # Add a fencing lun disk
        rsp = self.model.create_item("lun-disk",
                                   "/deployments/local/clusters/" +
                                   cluster_name + \
                                   "/fencing_disks/" + model_name,
                                   lun_name = lun_name,
                                   name = dev_name,
                                   size = size,
                                   storage_container = container,
                                   bootable = bootable,
                                   shared = shared,
                                   uuid = uuid)
        self.assertFalse(isinstance(rsp, list), rsp)

    def add_vcs_cluster(self, name, cluster_type="vcs", cluster_id="1",
        low_prio_net="services", llt_nets="heartbeat1,hearbeat2"):
        rsp = self.model.create_item("vcs-cluster",
            '/deployments/local/clusters/{n}'.format(n=name),
            cluster_id=cluster_id, cluster_type=cluster_type,
            low_prio_net=low_prio_net, llt_nets=llt_nets)
        self.assertFalse(isinstance(rsp, list), rsp)

    def query(self, item_type=None, **kwargs):
        # Use ModelManager.query to find items in the model
        # properties to match desired item are passed as kwargs.
        # The use of this method is not required, but helps
        # plugin developer mimic the run-time environment
        # where plugin sees QueryItem-s.
        return self.context.query(item_type, **kwargs)

    def assertItemsEqual(self, _list1, _list2):
        list1 = list(_list1)
        list2 = list(_list2)
        self.assertEqual(len(list1), len(list2))
        list1.sort()
        list2.sort()
        for idx in range(len(list1)):
            self.assertEqual(list1[idx], list2[idx])

    def assertTasksAreEqual(self, tasklist1, tasklist2):
        def cmp_task(t1, t2):
            return cmp(task2str(t1),task2str(t2))
        list1 = list(tasklist1)
        list2 = list(tasklist2)
        self.assertEqual(len(list1),len(list2))
        list1.sort(cmp_task)
        list2.sort(cmp_task)
        for idx in range(len(list1)):
            if list1[idx] != list2[idx]:
                print list1[idx]
                print "---"
                print list2[idx]
            self.assertEqual(list1[idx],list2[idx])


    def setup_basic_model(self):
        # Use ModelManager.crete_item and ModelManager.create_link
        # to create and reference (i.e.. link) items in the model.
        # These correspond to CLI/REST verbs to create or link
        # items.
        self.os_profile = self.model.create_item("os-profile",
                                                 "/software/profiles/rhel",
                                                 name="sample-profile",
                                                 path="/profiles/node-iso/")
        self.system1 = self.model.create_item("system",
                                              "/infrastructure/systems/system1",
                                              system_name="SYS1")
        self.system2 = self.model.create_item("system",
                                              "/infrastructure/systems/system2",
                                              system_name="SYS2")
        self.network = self.model.create_item("network",
                                              "/infrastructure/networking/networks/ms_network",
                                              name="nodes",
                                              subnet="10.10.10.0/24",
                                              litp_management="true")

        rsp = self.model.create_item("vlan",
                                                "/ms/network_interfaces/vlan_4003_storage",
                                                ipaddress="10.10.10.20",
                                                network_name="storage",
                                                device_name="eth0.270")
        self.assertFalse(isinstance(rsp, list), rsp)

        rsp = self.model.create_item("storage-profile-base",
                                     "/infrastructure/storage/storage_profiles/profile_1")
        self.assertFalse(isinstance(rsp, list), rsp)

        # deployment
        self.deployment = self.model.create_item("deployment",
                                   "/deployments/local")
        # cluster
        self.cluster = self.model.create_item("cluster",
                                   "/deployments/local/clusters/cluster1")


    def setup_basic_model_with_nodes(self):
        self.setup_basic_model()
        self.add_node("cluster1", "node1", "system1", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.30"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.30"}
                                          ])
        self.add_node("cluster1", "node2", "system2", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.31"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.31"}
                                          ])

    def setup_basic_model_with_nodes_no_storage_nw(self):
        # basic model with nodes. No connection to storage network
        self.setup_basic_model()
        self.add_node("cluster1", "node1", "system1", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.30"}
                                          ])
        self.add_node("cluster1", "node2", "system2", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.31"}
                                          ])

    def setup_valid_san_model_no_shared_luns(self):
        # Use ModelManager.crete_item and ModelManager.create_link
        # to create and reference (i.e.. link) items in the model.
        # These correspond to CLI/REST verbs to create or link
        # items.
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san( san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                      "admin", "password", "Global", "12321", "FARGO01",
                      "storage")

        self.add_storage_pool(san_name, pool_name)

        self.add_lun_disk("system1", "bootlun1", "BOOTLUN1", "sda", "100G", pool_name,
                          "true", "false", uuid="BAD00000000000000000000000000015")

        self.add_lun_disk("system1", "applun1", "APPLUN1", "sdb", "100G", pool_name,
                          "false", "false", uuid="BAD00000000000000000000000000015")

        self.add_lun_disk("system1", "versant1", "VERSANT1", "sdc", "100G", pool_name,
                          "false", "false", uuid="BAD00000000000000000000000000015")

        self.add_lun_disk("system2", "bootlun2", "BOOTLUN2", "sdd", "100G", pool_name,
                          "true", "false", uuid="BAD00000000000000000000000000015")

        self.add_lun_disk("system2", "applun2", "APPLUN2", "sde", "100G", pool_name,
                          "false", "false", uuid="BAD00000000000000000000000000015")

        self.add_lun_disk("system2", "versant2", "VERSANT2", "sdf", "100G", pool_name,
                          "false", "false", uuid="BAD00000000000000000000000000015")

        self.add_node("cluster1", "node1", "system1", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.30"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.30"}
                                          ])
        self.add_node("cluster1", "node2", "system2", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.31"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.31"}
                                          ])

        self.add_hbas("system1", {
                                      "hba1":("00:11:22:33:44:55:66:77",
                                              "AA:BB:CC:DD:EE:FF:00:11"),
                                      "hba2":("01:11:22:33:44:55:66:77",
                                              "AB:BB:CC:DD:EE:FF:00:11")
                                      })
        self.add_hbas("system2", {
                                      "hba1":("00:11:22:33:44:55:66:77",
                                              "AA:BB:CC:DD:EE:FF:00:11"),
                                      "hba2":("01:11:22:33:44:55:66:77",
                                              "AB:BB:CC:DD:EE:FF:00:11")
                                      })

    def setup_basic_model_with_bmc(self):
        self.setup_basic_model()

        # Add a svc System
        self.system3 = self.model.create_item("blade",
                                              "/infrastructure/systems/system3",
                                              system_name="SYS3")

        self.add_bmc("system3", "10.10.30.1", "root", "password")

    def setup_complex_model_with_bmc(self):
        self.setup_basic_model()

        # Add a svc System
        self.system3 = self.model.create_item("blade",
                                              "/infrastructure/systems/system3",
                                              system_name="SYS3")

        self.add_bmc("system3", "10.10.30.1", "root", "password")

        # Add a svc System
        self.system3 = self.model.create_item("blade",
                                              "/infrastructure/systems/system4",
                                              system_name="SYS3")

        self.add_bmc("system4", "10.10.30.2", "root", "password")

        # Add a svc System
        self.system3 = self.model.create_item("blade",
                                              "/infrastructure/systems/system5",
                                              system_name="SYS3")

        self.add_bmc("system5", "10.10.30.3", "root", "password")

    def setup_complex_san_model_with_nodes_snappable_luns_and_external_snaps(self):
        """
        Complex model to test restore_snapshot

        Create the following setup :
        system1
        system2
        system3(node3)
            - MYSNAPLUN0
            - MYSNAPLUN1
            - MYSNAPLUN2 (external_snap)
            - MYSNAPLUN3 (shared in node5)
            - MYSNAPLUN4 (external_snap)
        system4(node4)
            - MYSNAPLUN5 (snap_size=0)
        system5
            - MYSNAPLUN3 (shared in node3)
            - MYSNAPLUN6
            - MYSNAPLUN7 (external)
            - MYSNAPLUN8

        san_01
            - pool01
                - MYSNAPLUN1
                - MYSNAPLUN2
                - MYSNAPLUN3
                - MYSNAPLUN4
                - MYSNAPLUN5
                - MYSNAPLUN6
                - MYSNAPLUN7
            -pool02
                - MYSNAPLUN0
                - MYSNAPLUN8
        """
        # 3 blades system3, system4 and system5
        san_name = "san_01"
        pool_name = "pool01"
        pool_name2 = "pool02"

        self.setup_complex_model_with_bmc()

        # Add the san
        self.add_san( san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                      "admin", "password", "Global", "12321", "FARGO01",
                      "storage")
        self.add_storage_pool(san_name, pool_name)
        self.add_storage_pool(san_name, pool_name2)

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

        # Two clusters, one dmp one mpath
        self.add_vcs_cluster("cluster-dmp", cluster_id="2", cluster_type="sfha")
        self.add_vcs_cluster("cluster-mpath", cluster_id="3", cluster_type="vcs")

        # Three nodes node3, node4 and node5
        self.add_node("cluster-dmp", "node3", "system3", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.30"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.30"}
                                         ])
        self.add_node("cluster-mpath", "node4", "system4", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.31"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.31"}
                                        ])
        self.add_node("cluster-dmp", "node5", "system5", [
                {"network_name":"node", "if_name":"if0","ip":"10.10.10.32"},
                {"network_name":"storage", "if_name":"if1","ip":"10.10.20.32"}
                                        ])

        # Add three snapable luns to node3
        self.add_lun_disk("system3", "mysnappablelun0", "MYSNAPLUN0", "sda", "20G", pool_name2,
                        bootable = "false", shared = "false",
                        uuid="BAD00000000000000000000000000010",
                        external_snap="false", snap_size="30")
        self.add_lun_disk("system3", "mysnappablelun1", "MYSNAPLUN1", "sdb", "20G", pool_name,
                        bootable = "false", shared = "false",
                        uuid="BAD00000000000000000000000000011",
                        external_snap="false", snap_size="30")
        self.add_lun_disk("system3", "mysnappablelun2", "MYSNAPLUN2", "sdc", "20G", pool_name,
                        bootable = "false", shared = "false",
                        uuid="BAD00000000000000000000000000012",
                        external_snap="true", snap_size="30")

        # A shared lun between node3 and node5
        self.add_lun_disk("system3", "mysnappablelun3", "MYSNAPLUN3", "sdd", "20G", pool_name,
                           bootable = "false", shared = "true",
                           uuid="BAD00000000000000000000000000013",
                           external_snap="false", snap_size="30")
        self.add_lun_disk("system5", "mysnappablelun3", "MYSNAPLUN3", "sda", "20G", pool_name,
                           bootable = "false", shared = "true",
                           uuid="BAD00000000000000000000000000013",
                           external_snap="false", snap_size="30")

        # A non snapable lun in node3
        self.add_lun_disk("system3", "myNosnappablelun4", "MYSNAPLUN4", "sde", "20G", pool_name,
                           bootable = "false", shared = "false",
                           uuid="BAD00000000000000000000000000014",
                           external_snap="true", snap_size="0")
        # Another non snapable lun in node4
        self.add_lun_disk("system4", "myNosnappablelun5", "MYSNAPLUN5", "sda", "20G", pool_name,
                           bootable = "false", shared = "false",
                           uuid="BAD00000000000000000000000000015",
                           external_snap="false", snap_size="0")

        # Add two snapable luns to node5 in pool1
        self.add_lun_disk("system5", "mysnappablelun6", "MYSNAPLUN6", "sdb", "20G", pool_name,
                        bootable = "false", shared = "false",
                        uuid="BAD00000000000000000000000000016",
                        external_snap="false", snap_size="30")
        self.add_lun_disk("system5", "mysnappablelun7", "MYSNAPLUN7", "sdc", "20G", pool_name,
                        bootable = "false", shared = "false",
                        uuid="BAD00000000000000000000000000017",
                        external_snap="true", snap_size="30")
        # and one more snapable lun to node5 in pool2
        self.add_lun_disk("system5", "mysnappablelun8", "MYSNAPLUN8", "sdd", "20G", pool_name2,
                        bootable = "false", shared = "false",
                        uuid="BAD00000000000000000000000000018",
                        external_snap="false", snap_size="30")

def inc_size(size, num_megas):
    old_size = int(normalise_to_megabytes(size))
    new_size = old_size + num_megas
    return str(new_size)
