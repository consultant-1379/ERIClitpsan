# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

import sys
from inspect import getargspec

from litp.core.execution_manager import CallbackExecutionException
from litp.core.task import CallbackTask
from mock import patch, MagicMock
from sanapi.sanapiexception import SanApiException, \
    SanApiEntityNotFoundException
from sanapi.sanapiinfo import LunInfo, HbaInitiatorInfo, HluAluPairInfo, \
    StorageGroupInfo, StoragePoolInfo

from san_plugin.san_utils import cmp_values, values_are_equal, \
    get_ip_for_node
from san_plugin.san_utils import get_balancing_sp, hba_port_list, \
    get_bg as get_bg_san_utils, toggle_sp, get_lun_names_for_bg
from testfunclib import BasicTestSan
from testfunclib import StorageContainerMock
from testfunclib import skip, myassert_raises_regexp, validate_ipv4, \
    NodeMock, LunMock, SanPluginContextMock, SanMock, ItemMock


class TestSanPlugin(BasicTestSan):
    def printc(self, model_node):
        print('{0} {1}'.format(model_node.vpath, model_node.item_type))
        if model_node.properties:
            for _name, _value in model_node.properties.items():
                print('\t{0}: {1}'.format(_name, _value))
        for child in model_node.children.values():
            self.printc(child)

    def setUp(self):
        """
        Construct a model, sufficient for test cases
        that you wish to implement in this suite.
        """
        BasicTestSan.setUp(self)

    def tprint(self, string):
        """
        print to stderr if needed in test for debug or logging.
        mvn clean install & nose tests steal stdout so you can't see that.
        """
        print >> sys.stderr, string

    def get_bg(self, lun):
        '''
        Returns balancing group value from a LITP LUN object,
        or None if not defined
        '''
        if hasattr(lun, 'balancing_group'):
            return lun.balancing_group
        else:
            return None

    def setup_basic_vcs_model(self):
        # create basic model containing vcs cluster
        self.setup_basic_model()
        rsp = self.model.create_item("vcs-cluster",
                                     "/deployments/local/clusters/db_cluster",
                                     default_nic_monitor="mii",
                                     cluster_type="sfha",
                                     low_prio_net="mgnt",
                                     cluster_id="21977",
                                     ha_manager="vcs",
                                     llt_nets="heartbeat1,heartbeat2")
        self.assertFalse(isinstance(rsp, list), rsp)

        self.add_node("db_cluster", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("db_cluster", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_hbas("system2", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        san_name = "san_01"
        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")

    def setup_san_model_with_valid_fencing_luns(self):
        # create model containing fencing LUNs
        self.setup_basic_vcs_model()
        san_name = "san_01"
        fen_rg_id = "0"

        self.add_raid_group(san_name, fen_rg_id)
        for lun_num in range(1, 4):
            self.add_fen_lun_disk("db_cluster", "fenlun" + str(lun_num),
                                  "FENLUN" + str(lun_num), "sdf", "100M",
                                  fen_rg_id,
                                  "false", "true",
                                  uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_invalid_fencing_luns(self):
        # create model containing fencing LUNs
        self.setup_basic_vcs_model()
        san_name = "san_01"
        fen_rg_id = "0"
        bad_fen_rg_id = "22"

        self.add_raid_group(san_name, fen_rg_id)
        for lun_num in range(1, 4):
            self.add_fen_lun_disk("db_cluster", "fenlun" + str(lun_num),
                                  "FENLUN" + str(lun_num), "sdf", "100M",
                                  bad_fen_rg_id,
                                  "false", "true",
                                  uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_dup_fencing_luns(self):
        # create model containing duplicate fencing LUNs
        self.setup_basic_vcs_model()
        san_name = "san_01"
        fen_rg_id = "0"

        self.add_raid_group(san_name, fen_rg_id)
        self.add_fen_lun_disk("db_cluster", "fenlun1",
                              "FENLUN1", "sdf", "100M", fen_rg_id,
                              "false", "true",
                              uuid="BAD00000000000000000000000000015")
        self.add_fen_lun_disk("db_cluster", "fenlun2",
                              "FENLUN1", "sdg", "100M", fen_rg_id,
                              "false", "true",
                              uuid="BAD00000000000000000000000000016")

    def setup_san_model_with_bad_fencing_lun_size(self):
        # create model containing fencing LUNs with invalid size
        self.setup_basic_vcs_model()
        san_name = "san_01"
        fen_rg_id = "0"

        self.add_raid_group(san_name, fen_rg_id)
        self.add_fen_lun_disk("db_cluster", "fenlun1",
                              "FENLUN1", "sdf", "501M", fen_rg_id,
                              "false", "true",
                              uuid="BAD00000000000000000000000000015")
        self.add_fen_lun_disk("db_cluster", "fenlun2",
                              "FENLUN2", "sdg", "1G", fen_rg_id,
                              "false", "true",
                              uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_fencing_invalidprops(self):
        # create model containing fencing LUNs with invalid size
        self.setup_basic_vcs_model()
        san_name = "san_01"
        fen_rg_id = "0"

        self.add_raid_group(san_name, fen_rg_id)
        self.add_fen_lun_disk("db_cluster", "fenlun2",
                              "FENLUN2", "sdg", "100M", fen_rg_id,
                              "true", "false",
                              uuid="BAD00000000000000000000000000015")
        self.add_fen_lun_disk("db_cluster", "fenlun3",
                              "FENLUN3", "sdf", "100M", fen_rg_id,
                              "true", "true",
                              uuid="BAD00000000000000000000000000015")
        self.add_fen_lun_disk("db_cluster", "fenlun4",
                              "FENLUN4", "sdf", "100M", fen_rg_id,
                              "false", "false",
                              uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_bootable_shared_lun(self):
        # create model containing LUN incorrectly marked
        # bootable and shared
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")

        self.add_storage_pool(san_name, pool_name)

        self.add_lun_disk("system1", "bootlun1", "BOOTLUN1", "sda", "100G",
                          pool_name,
                          bootable="true", shared="true",
                          uuid="BAD00000000000000000000000000015")
        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])

    def setup_san_model_with_no_hbas(self):
        # create model containing nodes with no HBA cards
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")

        self.add_lun_disk(
                "system1", "lun1", "lun1_1", "sda", "20G",
                pool_name, bootable="false", shared="false", bg="even")

        self.add_lun_disk(
                "system2", "lun1", "lun1_2", "sda", "20G",
                pool_name, bootable="false", shared="false", bg="even")

        self.add_storage_pool(san_name, pool_name)

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("cluster1", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])

    def setup_san_model_mixed_local_and_lun(self):
        """
        Set up a model where system1 is using local disks only and system2
        is using luns
        """
        self.setup_basic_model()

        self.add_san("san1", "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool("san1", "pool1")

        self.add_hbas("system2", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })

        rsp = self.model.create_item(
                "disk",
                "/infrastructure/systems/system1/disks/boot",
                uuid="kgb", bootable="true", size="10G", name="sda")
        self.assertFalse(isinstance(rsp, list), rsp)

        self.add_lun_disk(
                "system2", "lun1", "lun1_1", "sda", "20G",
                "pool1", bootable="false", shared="false", bg="even")

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("cluster1", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])

    def setup_san_model_with_hba_no_ports(self):
        # create model containing LUN incorrectly marked
        # bootable and shared
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")

        self.add_storage_pool(san_name, pool_name)

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("cluster1", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])
        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_hbas("system2", {
            "hba1": (None, None),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })

        self.add_lun_disk(
                "system1", "lun1", "lun1_1", "sda", "20G",
                pool_name, bootable="false", shared="false", bg="even")

        self.add_lun_disk(
                "system2", "lun1", "lun1_2", "sda", "20G",
                pool_name, bootable="false", shared="false", bg="even")

    def setup_san_model_with_lun_in_bad_pool(self):
        # create model with lun in non existing pool
        san_name = "san_01"
        good_pool_name = "pool01"
        bad_pool_name = "non_existing_pool"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, good_pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])

        self.add_lun_disk("system1", "bootlun1", "BOOTLUN1", "sda", "100G",
                          good_pool_name,
                          bootable="true", shared="false",
                          uuid="BAD00000000000000000000000000015")

        # now add LUN to non-exising pool
        self.add_lun_disk("system1", "applun1", "APPLUN1", "sdb", "100G",
                          bad_pool_name,
                          bootable="false", shared="false",
                          uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_no_pools(self):
        # create model with no storage pools
        san_name = "san_01"
        pool_name = "non_existing_pool"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_lun_disk("system1", "bootlun1", "BOOTLUN1", "sda", "100G",
                          pool_name,
                          bootable="true", shared="false",
                          uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_non_shared_luns_duplicate_name(self):
        # create model with non shared luns with duplicate luns
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])

        self.add_lun_disk("system1", "mylun01", "MYLUN", "sda", "100G",
                          pool_name,
                          bootable="false", shared="false",
                          uuid="BAD00000000000000000000000000015")
        self.add_lun_disk("system1", "mylun02", "MYLUN", "sdb", "100G",
                          pool_name,
                          bootable="false", shared="false",
                          uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_shared_and_nonshared_luns_duplicate_name(self):
        # create model with 2 luns with same name - one shared
        # and the other not shared
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_lun_disk("system1", "mylun01", "MYLUN", "sda", "100G",
                          pool_name,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")
        self.add_lun_disk("system1", "mylun02", "MYLUN", "sdb", "100G",
                          pool_name,
                          bootable="false", shared="false",
                          uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_shared_luns(self):
        # create model with 2 luns in 2 different nodes
        # with same name both shared
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_hbas("system2", {
            "hba1": ("00:11:22:33:44:55:66:88",
                     "AA:BB:CC:DD:EE:FF:00:12"),
            "hba2": ("01:11:22:33:44:55:66:99",
                     "AB:BB:CC:DD:EE:FF:00:13")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("cluster1", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])
        self.add_lun_disk("system1", "mylun01", "MYLUN", "sda", "100G",
                          pool_name,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")
        self.add_lun_disk("system2", "mylun01", "MYLUN", "sda", "100G",
                          pool_name,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_all_luns(self):
        # create model with mixture of shared and
        # non-shared LUNs in both nodes
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_hbas("system2", {
            "hba1": ("00:11:22:33:44:55:66:88",
                     "AA:BB:CC:DD:EE:FF:00:12"),
            "hba2": ("01:11:22:33:44:55:66:99",
                     "AB:BB:CC:DD:EE:FF:00:13")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("cluster1", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])
        self.add_lun_disk("system1", "myregularlun1", "MYREGLUN1", "sda",
                          "20G", pool_name,
                          bootable="false", shared="false",
                          uuid="BAD00000000000000000000000000011")
        self.add_lun_disk("system1", "mysharedlun01", "MYLUN", "sdb", "100G",
                          pool_name,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")
        self.add_lun_disk("system2", "myregularlun2", "MYREGLUN2", "sdc",
                          "20G", pool_name,
                          bootable="false", shared="false",
                          uuid="BAD00000000000000000000000000012")
        self.add_lun_disk("system2", "mysharedlun01", "MYLUN", "sdb", "100G",
                          pool_name,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_duplicate_shared_luns_samenode(self):
        # create model with 2 luns with same name both shared
        # on same node
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_lun_disk("system1", "mylun01", "MYLUN", "sda", "100G",
                          pool_name,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")
        self.add_lun_disk("system1", "mylun02", "MYLUN", "sda", "100G",
                          pool_name,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")

    def setup_san_model_with_mismatched_shared_luns(self):
        # create model with shared luns but with
        # mismatched lun properties
        #
        san_name = "san_01"
        pool_name1 = "pool01"
        pool_name2 = "pool02"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name1)
        self.add_storage_pool(san_name, pool_name2)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_hbas("system2", {
            "hba1": ("00:11:22:33:44:55:66:88",
                     "AA:BB:CC:DD:EE:FF:00:12"),
            "hba2": ("01:11:22:33:44:55:66:99",
                     "AB:BB:CC:DD:EE:FF:00:13")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("cluster1", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])
        self.add_lun_disk("system1", "mylun01", "MYLUN", "sda", "100G",
                          pool_name1,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000015")
        self.add_lun_disk("system2", "mylun01", "MYLUN", "sdb", "101G",
                          pool_name2,
                          bootable="false", shared="true",
                          uuid="BAD00000000000000000000000000016")

    def setup_san_model_with_one_snappable_lun(self):
        # create model with one snappable LUN on SYSTEM1
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model_with_bmc()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_hbas("system2", {
            "hba1": ("00:11:22:33:44:55:66:88",
                     "AA:BB:CC:DD:EE:FF:00:12"),
            "hba2": ("01:11:22:33:44:55:66:99",
                     "AB:BB:CC:DD:EE:FF:00:13")
        })

        self.add_node("cluster1", "node1", "system3", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_lun_disk("system3", "mysnappablelun1", "MYSNAPLUN1", "sda",
                          "20G", pool_name,
                          bootable="false", shared="false",
                          uuid="BAD00000000000000000000000000011",
                          external_snap="false", snap_size="30")

    def setup_san_model_with_balancing_group_luns(self):
        san_name = "san_01"
        pool_name = "pool01"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     "storage")
        self.add_storage_pool(san_name, pool_name)

        self.add_hbas("system1", {
            "hba1": ("00:11:22:33:44:55:66:77",
                     "AA:BB:CC:DD:EE:FF:00:11"),
            "hba2": ("01:11:22:33:44:55:66:77",
                     "AB:BB:CC:DD:EE:FF:00:11")
        })
        self.add_hbas("system2", {
            "hba1": ("00:11:22:33:44:55:66:88",
                     "AA:BB:CC:DD:EE:FF:00:12"),
            "hba2": ("01:11:22:33:44:55:66:99",
                     "AB:BB:CC:DD:EE:FF:00:13")
        })

        self.add_node("cluster1", "node1", "system1", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.30"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.30"}
        ])
        self.add_node("cluster1", "node2", "system2", [
            {"network_name": "node", "if_name": "if0", "ip": "10.10.10.31"},
            {"network_name": "storage", "if_name": "if1", "ip": "10.10.20.31"}
        ])

        # System 1 LUNs
        self.add_lun_disk("system1", "lun1", "lun1_1", "sda", "20G", pool_name,
                          bootable="false", shared="false", bg="even")

        self.add_lun_disk("system1", "lun2", "lun1_2", "sdb", "20G", pool_name,
                          bootable="false", shared="false", bg="even")

        self.add_lun_disk("system1", "lun3", "lun1_3", "sdc", "20G", pool_name,
                          bootable="false", shared="false", bg="even")

        self.add_lun_disk("system1", "lun4", "lun1_4", "sdd", "20G", pool_name,
                          bootable="false", shared="false")

        self.add_lun_disk("system1", "lun5", "lun1_5", "sde", "20G", pool_name,
                          bootable="false", shared="false")

        self.add_lun_disk("system1", "lun6", "lun1_6", "sdf", "20G", pool_name,
                          bootable="false", shared="false", bg="odd")

        self.add_lun_disk("system1", "lun7", "lun1_7", "sdg", "20G", pool_name,
                          bootable="false", shared="false", bg="odd")

        # System 1 Shared LUNs
        self.add_lun_disk("system1", "share1", "share1", "sdh", "100G",
                          pool_name,
                          bootable="false", shared="true", bg="share_even")

        self.add_lun_disk("system1", "share2", "share2", "sdh", "100G",
                          pool_name,
                          bootable="false", shared="true", bg="share_even")

        self.add_lun_disk("system1", "share3", "share3", "sdj", "100G",
                          pool_name,
                          bootable="false", shared="true")

        self.add_lun_disk("system1", "share4", "share4", "sdk", "100G",
                          pool_name,
                          bootable="false", shared="true", bg="share_odd")

        # System 2 LUNs
        self.add_lun_disk("system2", "lun1", "lun2_1", "sda", "20G", pool_name,
                          bootable="false", shared="false", bg="even")

        self.add_lun_disk("system2", "lun2", "lun2_2", "sdb", "20G", pool_name,
                          bootable="false", shared="false", bg="even")

        self.add_lun_disk("system2", "lun3", "lun2_3", "sdc", "20G", pool_name,
                          bootable="false", shared="false", bg="even")

        self.add_lun_disk("system2", "lun4", "lun2_4", "sdd", "20G", pool_name,
                          bootable="false", shared="false")

        self.add_lun_disk("system2", "lun5", "lun2_5", "sde", "20G", pool_name,
                          bootable="false", shared="false")

        self.add_lun_disk("system2", "lun6", "lun2_6", "sdf", "20G", pool_name,
                          bootable="false", shared="false", bg="odd")

        # System 2 Shared LUNs
        self.add_lun_disk("system2", "share1", "share1", "sdh", "100G",
                          pool_name,
                          bootable="false", shared="true", bg="share_even")

        self.add_lun_disk("system2", "share2", "share2", "sdh", "100G",
                          pool_name,
                          bootable="false", shared="true", bg="share_even")

        self.add_lun_disk("system2", "share3", "share3", "sdj", "100G",
                          pool_name,
                          bootable="false", shared="true")

        self.add_lun_disk("system2", "share4", "share4", "sdk", "100G",
                          pool_name,
                          bootable="false", shared="true", bg="share_odd")

    def setup_san_model_with_invalid_san_network(self):
        # create model with 2 luns with same name both shared
        san_name = "san_01"
        pool_name = "pool01"
        bad_san_network_name = "foonetwork"

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", "10.10.10.23", "10.10.10.24",
                     "admin", "password", "Global", "12321", "FARGO01",
                     bad_san_network_name)
        self.add_storage_pool(san_name, pool_name)

    def setup_san_model_with_no_san_ips(self):
        # create model with san but no san ips defined
        san_name = "san_01"
        pool_name = "pool01"
        san_network_name = "storage"
        san_ip_a = None
        san_ip_b = None

        self.setup_basic_model()

        self.add_san(san_name, "VNX2", san_ip_a, san_ip_b,
                     "admin", "password", "Global", "12321", "FARGO01",
                     san_network_name)
        self.add_storage_pool(san_name, pool_name)

    def add_lun_disk(self, system_name, model_name, lun_name, dev_name, size,
                     container,
                     bootable, shared, uuid=None, external_snap=None,
                     snap_size=None, bg=None):
        # Add a lun disk

        if bg == None:
            if external_snap is not None or snap_size is not None:
                rsp = self.model.create_item("lun-disk",
                                             "/infrastructure/systems/" + system_name + \
                                             "/disks/" + model_name,
                                             lun_name=lun_name,
                                             name=dev_name,
                                             size=size,
                                             storage_container=container,
                                             bootable=bootable,
                                             shared=shared,
                                             external_snap=external_snap,
                                             snap_size=snap_size
                                             )
            else:
                rsp = self.model.create_item("lun-disk",
                                             "/infrastructure/systems/" + system_name + \
                                             "/disks/" + model_name,
                                             lun_name=lun_name,
                                             name=dev_name,
                                             size=size,
                                             storage_container=container,
                                             bootable=bootable,
                                             shared=shared)
        else:
            if external_snap is not None or snap_size is not None:
                rsp = self.model.create_item("lun-disk",
                                             "/infrastructure/systems/" + system_name + \
                                             "/disks/" + model_name,
                                             lun_name=lun_name,
                                             name=dev_name,
                                             size=size,
                                             storage_container=container,
                                             bootable=bootable,
                                             shared=shared,
                                             external_snap=external_snap,
                                             snap_size=snap_size,
                                             balancing_group=bg
                                             )
            else:
                rsp = self.model.create_item("lun-disk",
                                             "/infrastructure/systems/" + system_name + \
                                             "/disks/" + model_name,
                                             lun_name=lun_name,
                                             name=dev_name,
                                             size=size,
                                             storage_container=container,
                                             bootable=bootable,
                                             shared=shared,
                                             balancing_group=bg
                                             )

        self.assertFalse(isinstance(rsp, list), rsp)

    def test_validate_nosan(self):
        """
        Validation when there is no SAN related information in the model
        """
        self.setup_basic_model_with_nodes()
        errors = self.plugin.validate_model(self)
        self.assertEqual(0, len(errors))

    def test_validate_validsan(self):
        """
        Validation when there is valid san information in the model
        """
        self.setup_valid_san_model_no_shared_luns()
        errors = self.plugin.validate_model(self)
        self.assertEqual(0, len(errors))

    def test_validate_boot_shared_lun(self):
        """
        Validation generated error if bootable LUN also marked shared
        """
        self.setup_san_model_with_bootable_shared_lun()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("also marked as shared" in
                        errors[0].error_message)

    def test_validate_no_hbas(self):
        """
        Validation generates error when no hba defined for nodes
        """
        self.setup_san_model_with_no_hbas()
        self.printc(self.model.get_root())
        errors = self.plugin.validate_model(self)
        self.assertEqual(2, len(errors))
        self.assertTrue("No HBAs defined for node" in
                        errors[0].error_message)

    def test_validate_local_disks_no_hbas(self):
        """
        Check validation generates no errors if a node has no lun-disks
        attached
        """
        self.setup_san_model_mixed_local_and_lun()
        errors = self.plugin.validate_model(self)
        for error in errors:
            print(error)
        self.assertEqual(0, len(errors))

    def test_validate_hba_no_ports(self):
        """
        Validation generates error when hba defined but no ports
        """
        self.setup_san_model_with_hba_no_ports()
        self.printc(self.model.get_root())
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("Neither HBA port A nor HBA port B have been specified"
                        in errors[0].error_message)

    def test_validate_no_pools(self):
        """
        Validation generates error when no pools defined
        """
        self.setup_san_model_with_no_pools()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("No storage containers defined" in
                        errors[0].error_message)

    def test_validate_lun_invalid_container(self):
        """
        Validation generates error lun in invalid container
        """
        self.setup_san_model_with_lun_in_bad_pool()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("invalid storage container" in
                        errors[0].error_message)

    def test_validate_luns_not_unique(self):
        """
        Validation generates error for non-shared luns with same name
        """
        self.setup_san_model_with_non_shared_luns_duplicate_name()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("Duplicate LUN names" in
                        errors[0].error_message)

    def test_validate_luns_shared_non_shared_same_name(self):
        """
        Validation generates error for luns with same name marked shared
        and nonshared"
        """
        self.setup_san_model_with_shared_and_nonshared_luns_duplicate_name()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("The following LUNs are marked shared and non-shared"
                        in errors[0].error_message)

    def test_validate_sharedluns_ok(self):
        """
        Validation does not generate error for shared luns
        """
        self.setup_san_model_with_shared_luns()
        errors = self.plugin.validate_model(self)
        self.assertEqual(0, len(errors))

    def test_validate_duplicate_sharedluns_samenode(self):
        """
        Validation generates error for duplicate shared LUNs same node
        """
        self.setup_san_model_with_duplicate_shared_luns_samenode()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("Duplicate shared LUN" in
                        errors[0].error_message)

    def test_validate_san_network(self):
        """
        Validation generates error for invalid san network
        """
        self.setup_san_model_with_invalid_san_network()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("not in list of MS networks" in
                        errors[0].error_message)

    def test_validate_san_no_ips(self):
        """
        Validation generates error for san with no ips
        """
        self.setup_san_model_with_no_san_ips()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))
        self.assertTrue("No connection IP specified for san" in
                        errors[0].error_message)

    def test_validate_san_mismatched_shared_luns(self):
        """
        Validation generates error for mismatched shared LUNs
        """
        self.setup_san_model_with_mismatched_shared_luns()
        errors = self.plugin.validate_model(self)
        self.assertEqual(3, len(errors))
        self.assertTrue("size mismatch" in
                        errors[0].error_message)
        self.assertTrue("name mismatch" in
                        errors[1].error_message)
        self.assertTrue("storage_container mismatch" in
                        errors[2].error_message)

    def test_create_configuration_no_san(self):
        """
        Check that SAN plugin generates no tasks when no SAN info in model
        """
        self.setup_basic_model_with_nodes()
        tasks = self.plugin.create_configuration(self)
        self.assertEqual(0, len(tasks))

    def test_create_configuration_nonshared(self):
        """
        Check that SAN plugin generates correct tasks for valid SAN info
        This model does not contain any shared LUNs
        """
        self.setup_valid_san_model_no_shared_luns()
        # Invoke plugin's methods to run test cases
        # and assert expected output.
        tasks = self.plugin.create_configuration(self)

        #
        # Phase 1 - check correct number of tasks
        #

        # check the total number of tasks
        self.assertEqual(16, len(tasks))
        # look for create storage group tasks one for each node
        self.assertEqual(2, len([task for task in tasks
                                 if task.call_type == "create_sg_cb_task"]))
        # look for create lun tasks one for each lun
        self.assertEqual(6, len([task for task in tasks
                                 if task.call_type == "create_lun_cb_task"]))
        # look for add lun to sg tasks one for each lun
        self.assertEqual(6, len([task for task in tasks
                                 if
                                 task.call_type == "create_reglun_cb_task"]))
        # look for create_hostinit_cb_task tasks for each node
        self.assertEqual(2, len([task for task in tasks
                                 if
                                 task.call_type == "create_hostinit_cb_task"]))

        #
        # Phase 2 - examine tasks in more detail
        #
        sg_tasks = [task for task in tasks
                    if task.call_type == "create_sg_cb_task"]
        lun_tasks = [task for task in tasks
                     if task.call_type == "create_lun_cb_task"]
        reg_tasks = [task for task in tasks
                     if task.call_type == "create_reglun_cb_task"]
        init_tasks = [task for task in tasks
                      if task.call_type == "create_hostinit_cb_task"]

        for tasklist in (sg_tasks, lun_tasks, reg_tasks, init_tasks):
            self.check_task_args(tasklist)

    def check_task_args(self, tasks):
        #
        # Function to examine details of CallbackTask
        # correct #args
        #
        for task in tasks:
            print task.call_type
            self.assertEqual(task.call_type, task.callback.__name__)
            num_cb_args = len(getargspec(task.callback)[0])
            self.assertEqual(len(task.args) + 2, num_cb_args)

    def test_create_configuration_all_luns(self):
        """
        Check that SAN plugin generates correct tasks for valid SAN info
        This model contains a mixture of shared/non shared LUNs
        """
        self.setup_san_model_with_all_luns()
        # Invoke plugin's methods to run test cases
        # and assert expected output.
        tasks = self.plugin.create_configuration(self)
        # check the total number of tasks
        self.assertEqual(12, len(tasks))
        # look for create storage group tasks one for each node
        self.assertEqual(2, len([task for task in tasks
                                 if task.call_type == "create_sg_cb_task"]))
        # look for create lun tasks one for each lun
        self.assertEqual(4, len([task for task in tasks
                                 if task.call_type == "create_lun_cb_task"]))
        # look for add lun to sg tasks one for each lun
        self.assertEqual(4, len([task for task in tasks
                                 if
                                 task.call_type == "create_reglun_cb_task"]))
        # look for create_hostinit_cb_task tasks for each node
        self.assertEqual(2, len([task for task in tasks
                                 if
                                 task.call_type == "create_hostinit_cb_task"]))

    @patch("san_plugin.sanplugin.api_builder")
    def test_createlun(self, mock_api_builder):
        """
        Check that SAN plugin calls sanapi create_lun properly
        """
        san = mock_api_builder("vnx1", None)
        san.create_lun = MagicMock(name="create_lun")
        self.plugin._createlun(san, "lun123", "100000", "mypool",
                               "Storage Pool", "true", "A")
        san.create_lun.assert_called_with("lun123", "100004", "Storage Pool",
                                          "mypool", "A", lun_type="thick",
                                          ignore_thresholds=True)

    @patch("san_plugin.sanplugin.api_builder")
    def test_createlun_fudge(self, mock_api_builder):
        """
        Check that SAN plugin includes size fudge when bootable is "true"
        """
        bootable = "true"
        san = mock_api_builder("vnx1", None)
        san.create_lun = MagicMock(name="create_lun")
        self.plugin._createlun(san, "lun123", "100000", "mypool",
                               "Storage Pool", bootable, "A")
        san.create_lun.assert_called_with("lun123", "100004", "Storage Pool",
                                          "mypool", "A", lun_type="thick",
                                          ignore_thresholds=True)

    @patch("san_plugin.sanplugin.api_builder")
    def test_createlun_nofudge(self, mock_api_builder):
        """
        Check that SAN plugin does not include fudge when bootable is "false"
        """
        bootable = "false"
        san = mock_api_builder("vnx1", None)
        san.create_lun = MagicMock(name="create_lun")
        self.plugin._createlun(san, "lun123", "100000", "mypool",
                               "Storage Pool", bootable, "A")
        san.create_lun.assert_called_with("lun123", "100000", "Storage Pool",
                                          "mypool", "A", lun_type="thick",
                                           ignore_thresholds=True)

    @patch("san_plugin.sanplugin.api_builder")
    def test_createlunpslfailed(self, mock_api_builder):
        """
        Check that SAN plugin handles exception from sanapi
        """
        san = mock_api_builder("vnx1", None)
        san.create_lun = MagicMock(name="create_lun",
                                   side_effect=SanApiException(
                                       "Unable to create LUN", 1))
        myassert_raises_regexp(self, CallbackExecutionException,
                               "Unable to create LUN", self.plugin._createlun,
                               san, "lun123",
                               "100000", "Storage Pool", "mypool", "true", "A")
        # san.create_lun.assert_called_with("lun123", "105120", "Storage Pool", "mypool")

    def test_get_ip_for_node(self):
        """
        Check get_ip_for_node() with good inputs
        """
        storage_network_name = "storage"
        self.setup_basic_model_with_nodes()
        node = self.context.query("node")[0]
        node_ip = get_ip_for_node(node, storage_network_name)
        self.assertTrue(validate_ipv4(node_ip))

    def test_get_ip_for_node_no_storage_nw(self):
        """
        Check get_ip_for_node() returns None for nodes without storage network
        """
        storage_network_name = "storage"
        self.setup_basic_model_with_nodes_no_storage_nw()
        node = self.context.query("node")[0]
        node_ip = get_ip_for_node(node, storage_network_name)
        self.assertEqual(node_ip, None)

    @skip
    def test_get_storage_network(self):
        """
        Check _get_storage_network() with good inputs
        """
        storage_network_name = "storage"
        self.setup_basic_model_with_nodes()
        storage_net = self.plugin._get_storage_network(self.model,
                                                       storage_network_name)
        self.assertTrue(storage_net.name, storage_network_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_existinglun_lun_not_existing(self, mock_api_builder):
        """
        Check _existinglun function returns False when LUN does not exist
        """
        self.setup_valid_san_model_no_shared_luns()
        lun_name = "MYLUN"
        lun_size = "100G"
        sp_name = "pool01"
        san = mock_api_builder("vnx1", None)
        san.get_lun = MagicMock(name="get_lun",
                                side_effect=SanApiEntityNotFoundException(
                                    "Unable to find LUN", 1))
        result = self.plugin._existinglun(san, lun_name, lun_size,
                                          sp_name, "Storage Pool")
        self.assertFalse(result)

    @patch("san_plugin.sanplugin.api_builder")
    def test_existinglun_psl_nonspecific_exception(self, mock_api_builder):
        """
        Check _existinglun function returns False when non specific
        exception received from PSL
        """
        self.setup_valid_san_model_no_shared_luns()
        sp_name = "pool01"
        lun_name = "MYLUN"
        lun_size = "100000"
        san = mock_api_builder("vnx1", None)
        san.get_lun = MagicMock(name="get_lun",
                                side_effect=SanApiException(
                                    "Fault in flux capacitor", 1))
        result = self.plugin._existinglun(san, lun_name, lun_size,
                                          sp_name, "Storage Pool")
        self.assertFalse(result)

    @patch("san_plugin.sanplugin.api_builder")
    def test_existinglun_identical_bootlun_existing(self, mock_api_builder):
        """
        Check _existinglun function returns True if identical bootable LUN exists
        """
        lun_fudge_size = 4
        self.setup_valid_san_model_no_shared_luns()
        sp_name = "pool01"
        lun_name = "MYLUN"
        lun_size = "100000"
        linfo = LunInfo("12", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        sp_name, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")
        san = mock_api_builder("vnx1", None)
        san.get_lun = MagicMock(name="get_lun", return_value=linfo)
        result = self.plugin._existinglun(san, lun_name, lun_size,
                                          sp_name,
                                          "Storage Pool")
        self.assertTrue(result)

    @patch("san_plugin.sanplugin.api_builder")
    def test_existinglun_identical_nonbootlun_existing(self, mock_api_builder):
        """
        Check _existinglun function returns True if identical non-bootable LUN exists
        """
        lun_fudge_size = 0
        self.setup_valid_san_model_no_shared_luns()
        sp_name = "pool01"
        lun_name = "MYLUN"
        lun_size = "100000"
        linfo = LunInfo("12", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        sp_name, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")
        san = mock_api_builder("vnx1", None)
        san.get_lun = MagicMock(name="get_lun", return_value=linfo)
        result = self.plugin._existinglun(san, lun_name, lun_size,
                                          sp_name,
                                          "Storage Pool")
        self.assertTrue(result)

    @patch("san_plugin.sanplugin.api_builder")
    def test_existinglun_rglun_not_existing(self, mock_api_builder):
        """
        Check _existinglun function returns False when RG LUN does not exist
        """
        self.setup_valid_san_model_no_shared_luns()
        lun_name = "MYLUN"
        lun_size = "100"
        rg_id = "0"
        san = mock_api_builder("vnx1", None)
        self.plugin._getrglun = MagicMock(name="_getrglun",
                                          side_effect=SanApiEntityNotFoundException(
                                              "Unable to find LUN", 1))
        result = self.plugin._existinglun(san, lun_name, lun_size,
                                          rg_id, "Raid Group")
        self.assertFalse(result)

    @patch("san_plugin.sanplugin.api_builder")
    def test_existinglun_rglun_existing(self, mock_api_builder):
        """
        Check _existinglun function returns True when identical RG LUN exists
        """
        self.setup_valid_san_model_no_shared_luns()
        lun_name = "FENLUN1"
        lun_size = "100"
        rg_id = "0"
        linfo = LunInfo("12", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        rg_id, lun_size,
                        "RaidGroup", "5")
        san = mock_api_builder("vnx1", None)
        self.plugin._getrglun = MagicMock(name="_getrglun", return_value=linfo)
        result = self.plugin._existinglun(san, lun_name, lun_size,
                                          rg_id, "Raid Group")
        self.assertTrue(result)

    @patch("san_plugin.sanplugin.api_builder")
    def test_saninit_positive(self, mock_api_builder):
        """
        Check _saninit function when PSL init successful
        """
        san_ipa = "1.2.3.4"
        san_ipb = "1.2.3.5"
        san_username = "admin"
        san_password = "password"
        san_cert = True
        san_vcheck = False
        san_escape = True
        san = mock_api_builder("vnx1", None)
        san.initialise = MagicMock(name="initialise")
        self.plugin._saninit(san, san_ipa, san_ipb, san_username, san_password,
                             "Global")
        san.initialise.assert_called_with((san_ipa, san_ipb), san_username,
                                          san_password, "Global", san_cert,
                                          san_vcheck, san_escape)
        self.plugin._saninit(san, san_ipa, san_ipb, san_username, san_password,
                             "Local")
        san.initialise.assert_called_with((san_ipa, san_ipb), san_username,
                                          san_password, "Local", san_cert,
                                          san_vcheck, san_escape)
        self.plugin._saninit(san, san_ipa, None, san_username, san_password,
                             "Local")
        san.initialise.assert_called_with((san_ipa,), san_username,
                                          san_password, "Local", san_cert,
                                          san_vcheck, san_escape)

    @patch("san_plugin.sanplugin.api_builder")
    def test_saninit_pslerror(self, mock_api_builder):
        """
        Check _saninit function when PSL init unsuccessful
        """
        san_ipa = "1.2.3.4"
        san_ipb = "1.2.3.5"
        san_username = "admin"
        san_password = "password"
        san_scope = "Global"
        san_cert = True
        san_vcheck = False
        san = mock_api_builder("vnx1", None)
        san.initialise = MagicMock(name="initialise",
                                   side_effect=SanApiException(
                                       "initialisation failure", 1))
        myassert_raises_regexp(self, CallbackExecutionException,
                               "Connection to SAN failed",
                               self.plugin._saninit, san, san_ipa,
                               san_ipb, san_username, san_password, san_scope)

    @patch("san_plugin.sanplugin.api_builder")
    def test_createsg_pslok(self, mock_api_builder):
        """
        Check that SAN plugin calls sanapi create_storage_group properly
        """
        san_name = "mysan"
        sg_name = "sg123"
        san = mock_api_builder("vnx1", None)
        san.storage_group_exists = MagicMock(name="san.storage_group_exists",
                                             return_value=False)
        san.create_storage_group = MagicMock(name="create_storage_group")
        self.plugin._createsg(san, sg_name, san_name)
        san.create_storage_group.assert_called_with(sg_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_createsg_sgexists(self, mock_api_builder):
        """
        Check that SAN plugin handles message from PSL
        storage group already in use
        """
        san_name = "mysan"
        sg_name = "sg123"
        san = mock_api_builder("vnx1", None)
        san.storage_group_exists = MagicMock(name="san.storage_group_exists",
                                             return_value=True)
        san.create_storage_group = MagicMock(name="create_storage_group")
        self.plugin._createsg(san, sg_name, san_name)
        self.assertFalse(san.create_storage_group.called)

    @patch("san_plugin.sanplugin.api_builder")
    def test_createsg_sgexists(self, mock_api_builder):
        """
        Check that SAN plugin handles message from PSL
        unable to check storage group already in use
        """
        san_name = "mysan"
        sg_name = "sg123"
        san = mock_api_builder("vnx1", None)
        san.storage_group_exists = MagicMock(name="san.storage_group_exists",
                                             side_effect=SanApiException(
                                                 "fault in flux capacitor", 1))

        san.create_storage_group = MagicMock(name="create_storage_group")
        self.plugin._createsg(san, sg_name, san_name)
        san.create_storage_group.assert_called_with(sg_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_createsg_pslnok(self, mock_api_builder):
        """
        Check that SAN plugin createsg handles exception from PSL
        """
        san_name = "mysan"
        sg_name = "sg123"
        san = mock_api_builder("vnx1", None)
        san.storage_group_exists = MagicMock(name="san.storage_group_exists",
                                             return_value=False)
        san.create_storage_group = MagicMock(name="create_storage_group",
                                             side_effect=SanApiException(
                                                 "fault in flux capacitor", 1))
        myassert_raises_regexp(self, CallbackExecutionException,
                               "Failed to create Storage Group",
                               self.plugin._createsg,
                               san, sg_name, san_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_host_rec_no_wwn_on_san(self, mock_api_builder):
        """
        Check that create_host_rec gracefully handles no matching WWNs on SAN
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpna = "50:01:43:80:12:0b:38:64"
        wwpnb = "50:01:43:80:12:0b:38:65"
        san = mock_api_builder("vnx1", None)
        san.get_hba_port_info = MagicMock(name="get_hba_port_info",
                                          return_value=[])
        myassert_raises_regexp(self, CallbackExecutionException,
                               "Neither port A nor port B of HBA could be registered for host",
                               self.plugin._create_host_rec,
                               san, sg_name, host_name, host_ip,
                               [wwpna, wwpnb])

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_host_rec_both_wwn_on_san(self, mock_api_builder):
        """
        Check that create_host_rec works when matching WWN found on SAN
        This is the main positive test
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpna = "50:01:43:80:12:0b:38:64"
        wwpnb = "50:01:43:80:16:7D:C4:5E"
        hbainfo = [
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:80:12:0b:38:64",
                    "spname1", "1"),
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                    "spname2", "2")
        ]

        san = mock_api_builder("vnx1", None)
        san.get_hba_port_info = MagicMock(name="get_hba_port_info",
                                          return_value=hbainfo)
        res = self.plugin._create_host_rec(san, sg_name,
                                           host_name, host_ip, [wwpna, wwpnb])
        self.assertEqual(True, res)

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_host_rec_one_wwn_on_san(self, mock_api_builder):
        """
        Check that create_host_rec works when only one matching WWN found on SAN
        This is the main positive test
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpna = "50:01:43:80:12:0b:38:64"
        wwpnb = "50:01:43:80:16:7D:C4:5E"
        hbainfo = [
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:80:12:0b:38:64",
                    "spname1", "1"),
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:99:99:99:99:99",
                    "spname2", "2")
        ]

        san = mock_api_builder("vnx1", None)
        san.get_hba_port_info = MagicMock(name="get_hba_port_info",
                                          return_value=hbainfo)
        res = self.plugin._create_host_rec(san, sg_name,
                                           host_name, host_ip, [wwpna, wwpnb])
        self.assertEqual(True, res)

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_host_rec_psl_error(self, mock_api_builder):
        """
        Check that create_host_rec handles exception from PSL
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpna = "50:01:43:80:12:0b:38:64"
        wwpnb = "50:01:43:80:16:7D:C4:5E"
        hbainfo = [
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:80:12:0b:38:64",
                    "spname1", "1"),
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                    "spname2", "2")
        ]

        san = mock_api_builder("vnx1", None)
        san.get_hba_port_info = MagicMock(name="get_hba_port_info",
                                          return_value=hbainfo)
        san.create_host_initiator = MagicMock(name="create_host_initiator",
                                              side_effect=SanApiException(
                                                  "error creating host init record",
                                                  1))
        myassert_raises_regexp(self, CallbackExecutionException,
                               "Failed to register Host Initiator",
                               self.plugin._create_host_rec, san, sg_name,
                               host_name,
                               host_ip, [wwpna, wwpnb])

    @patch("san_plugin.sanplugin.api_builder")
    def test_registernonbootablelun(self, mock_api_builder):
        """
        Check _registerlun when non-boot lun not already in storage group
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpn = "50:01:43:80:12:0b:38:64"
        lun_name = "mylun"
        storage_pool = "mypool"
        lun_size = "100000"
        bootable = "true"  # we need a test for bootable = "false" also
        lun_fudge_size = 4
        lun_bootable = "false"

        sginfo = self.configure_storage_group(sg_name,
                                              (("72", "0"), ("13", "1")))

        linfo = LunInfo("12", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        storage_pool, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")

        san = mock_api_builder("vnx1", None)
        san.get_storage_group = MagicMock(name="get_storage_group",
                                          return_value=sginfo)
        san.get_lun = MagicMock(name="get_lun",
                                return_value=linfo)
        res = self.plugin._registerlun(san, lun_name, storage_pool,
                                       "Storage Pool", lun_bootable, sg_name)
        san.get_storage_group.assert_called_with(sg_name)
        san.get_lun.assert_called_with(lun_name=lun_name)
        san.add_lun_to_storage_group.assert_called_with(sg_name, "2", "12")
        self.assertEqual(True, res)

    @patch("san_plugin.sanplugin.api_builder")
    def test_registerbootablelun(self, mock_api_builder):
        """
        Check _registerlun works when boot lun not already in storage group
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpn = "50:01:43:80:12:0b:38:64"
        lun_name = "mylun"
        storage_pool = "mypool"
        lun_size = "100000"
        lun_fudge_size = 4
        lun_bootable = "true"

        sginfo = self.configure_storage_group(sg_name,
                                              (("72", "2"), ("13", "1")))

        linfo = LunInfo("12", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        storage_pool, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")

        san = mock_api_builder("vnx1", None)
        san.get_storage_group = MagicMock(name="get_storage_group",
                                          return_value=sginfo)
        san.get_lun = MagicMock(name="get_lun",
                                return_value=linfo)
        res = self.plugin._registerlun(san, lun_name, storage_pool,
                                       "Storage Pool", lun_bootable, sg_name)
        san.get_storage_group.assert_called_with(sg_name)
        san.get_lun.assert_called_with(lun_name=lun_name)
        san.add_lun_to_storage_group.assert_called_with(sg_name, "0", "12")
        self.assertEqual(True, res)

    @patch("san_plugin.sanplugin.api_builder")
    def test_registernonbootablelun_alreadyexists(self, mock_api_builder):
        """
        Check _registerlun works when non boot lun already in storage group
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpn = "50:01:43:80:12:0b:38:64"
        lun_name = "mylun"
        storage_pool = "mypool"
        lun_size = "100000"
        lun_fudge_size = 4
        lun_bootable = "false"

        sginfo = self.configure_storage_group(sg_name,
                                              (("72", "0"), ("12", "1")))

        linfo = LunInfo("12", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        storage_pool, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")

        san = mock_api_builder("vnx1", None)
        san.get_storage_group = MagicMock(name="get_storage_group",
                                          return_value=sginfo)
        san.get_lun = MagicMock(name="get_lun",
                                return_value=linfo)
        res = self.plugin._registerlun(san, lun_name, storage_pool,
                                       "Storage Pool", lun_bootable, sg_name)
        san.get_storage_group.assert_called_with(sg_name)
        san.get_lun.assert_called_with(lun_name=lun_name)
        self.assertFalse(san.add_lun_to_storage_group.called)
        self.assertEqual(True, res)

    @patch("san_plugin.sanplugin.api_builder")
    def test_registerbootablelun_alreadyexists(self, mock_api_builder):
        """
        Check _registerlun works when boot lun already in storage group
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpn = "50:01:43:80:12:0b:38:64"
        lun_name = "mylun"
        storage_pool = "mypool"
        lun_size = "100000"
        lun_fudge_size = 4
        lun_bootable = "true"

        sginfo = self.configure_storage_group(sg_name,
                                              (("72", "0"), ("12", "1")))
        print "cfg:" + str(len(sginfo.hlualu_list))

        linfo = LunInfo("72", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        storage_pool, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")

        san = mock_api_builder("vnx1", None)
        san.get_storage_group = MagicMock(name="get_storage_group",
                                          return_value=sginfo)
        san.get_lun = MagicMock(name="get_lun",
                                return_value=linfo)
        res = self.plugin._registerlun(san, lun_name, storage_pool,
                                       "Storage Pool", lun_bootable, sg_name)
        san.get_storage_group.assert_called_with(sg_name)
        san.get_lun.assert_called_with(lun_name=lun_name)
        self.assertFalse(san.add_lun_to_storage_group.called)
        self.assertEqual(True, res)

    @patch("san_plugin.sanplugin.api_builder")
    def test_registernonbootablelun_alreadyexistsasbootable(self,
                                                            mock_api_builder):
        """
        Check _registerlun throws exception if non bootable lun already
        registered as bootable
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpn = "50:01:43:80:12:0b:38:64"
        lun_name = "mylun"
        storage_pool = "mypool"
        lun_size = "100000"
        lun_fudge_size = 4
        lun_bootable = "false"

        sginfo = self.configure_storage_group(sg_name,
                                              (("72", "0"), ("12", "1")))

        linfo = LunInfo("72", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        storage_pool, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")

        san = mock_api_builder("vnx1", None)
        san.get_storage_group = MagicMock(name="get_storage_group",
                                          return_value=sginfo)
        san.get_lun = MagicMock(name="get_lun",
                                return_value=linfo)
        myassert_raises_regexp(self, CallbackExecutionException,
                               "Non-bootable LUN already registered as bootable",
                               self.plugin._registerlun, san, lun_name,
                               storage_pool, "Storage Pool", lun_bootable,
                               sg_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_registerbootablelun_alreadyexistsasnonbootable(self,
                                                            mock_api_builder):
        """
        Check _registerlun throws exception if bootable lun already
        registered as non bootable
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpn = "50:01:43:80:12:0b:38:64"
        lun_name = "mylun"
        storage_pool = "mypool"
        lun_size = "100000"
        lun_fudge_size = 4
        lun_bootable = "true"

        sginfo = self.configure_storage_group(sg_name,
                                              (("72", "0"), ("12", "1")))

        linfo = LunInfo("12", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        storage_pool, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")

        san = mock_api_builder("vnx1", None)
        san.get_storage_group = MagicMock(name="get_storage_group",
                                          return_value=sginfo)
        san.get_lun = MagicMock(name="get_lun",
                                return_value=linfo)
        myassert_raises_regexp(self, CallbackExecutionException,
                               "Bootable LUN already registered as non-bootable",
                               self.plugin._registerlun, san, lun_name,
                               storage_pool, "Storage Pool", lun_bootable,
                               sg_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_registerbootablelun_pslerror(self, mock_api_builder):
        """
        Check _registerlun throws exception if exception received from
        PSL when registering LUN
        """
        sg_name = "sg123"
        host_name = "atrcxb1234"
        host_ip = "1.2.3.4"
        wwpn = "50:01:43:80:12:0b:38:64"
        lun_name = "mylun"
        storage_pool = "mypool"
        lun_size = "100000"
        lun_fudge_size = 4
        lun_bootable = "false"

        sginfo = self.configure_storage_group(sg_name,
                                              (("72", "0"), ("12", "1")))

        linfo = LunInfo("33", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        storage_pool, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")

        san = mock_api_builder("vnx1", None)
        san.get_storage_group = MagicMock(name="get_storage_group",
                                          return_value=sginfo)
        san.get_lun = MagicMock(name="get_lun",
                                return_value=linfo)
        san.add_lun_to_storage_group = MagicMock(
            name="add_lun_to_storage_group",
            side_effect=SanApiException("error adding lun to storage group",
                                        1))

        myassert_raises_regexp(self, CallbackExecutionException,
                               "Failed to register LUN with storage group",
                               self.plugin._registerlun, san, lun_name,
                               storage_pool, "Storage Pool", lun_bootable,
                               sg_name)

    def configure_storage_group(self, sg_name, aluhlupairs):
        hbainfo = [
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:80:12:0b:38:64",
                    "spname1", "1"),
            HbaInitiatorInfo(
                    "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                    "spname2", "2")
        ]
        aluhluinfo = []
        for pair in aluhlupairs:
            aluhluinfo.append(HluAluPairInfo(pair[1], pair[0]))
        sginfo = StorageGroupInfo(sg_name,
                                  "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                                  True,
                                  hbainfo, aluhluinfo)

        return sginfo

    def test_normalise_to_megabytes(self):
        """
        test _normalise_to_megabytes function
        """
        # valid sizes

        self.assertEqual("100", self.plugin._normalise_to_megabytes("100"))
        self.assertEqual("100", self.plugin._normalise_to_megabytes("100M"))
        self.assertEqual("102400", self.plugin._normalise_to_megabytes("100G"))
        self.assertEqual("104857600",
                         self.plugin._normalise_to_megabytes("100T"))

        # invalid sizes
        # myassert_raises_regexp(self, CallbackExecutionException,
        # "Invalid size",
        # self.plugin._normalise_to_megabytes("46a"))
        # myassert_raises_regexp(self, CallbackExecutionException,
        # "Invalid size",
        # self.plugin._normalise_to_megabytes("100"))
        # myassert_raises_regexp(self, CallbackExecutionException,
        # "Invalid size",
        # self.plugin._normalise_to_megabytes("foo"))

    def test_gen_lun_task(self):
        """
        test _gen_lun_task returns CallbackTask
        """
        self.setup_valid_san_model_no_shared_luns()
        node = self.context.query("node")[0]
        lun = self.context.query("lun-disk")[0]
        san = self.context.query("san-emc")[0]

        res = self.plugin._gen_lun_task(node, lun, "Raid Group", "A", san,
                                        True, [])

        self.assertTrue(isinstance(res, CallbackTask))

    def test_gen_storagegroup_task(self):
        """
        test _gen_storagegroup_task returns CallbackTask
        """
        sg_name = "sg123"
        self.setup_valid_san_model_no_shared_luns()
        node = self.context.query("node")[0]
        san = self.context.query("san-emc")[0]
        res = self.plugin._gen_storagegroup_task(node, san, sg_name)
        self.assertTrue(isinstance(res, CallbackTask))

    def test_gen_registernode_task(self):
        """
        test _gen_registernode_task returns CallbackTask
        """
        sg_name = "sg123"
        self.setup_valid_san_model_no_shared_luns()
        node = self.context.query("node")[0]
        san = self.context.query("san-emc")[0]
        hbas = self.context.query("hba")
        hba_ports = hba_port_list(hbas)
        res = self.plugin._gen_registernode_task(node, "1.2.3.4",
                                                 san, hbas, hba_ports, sg_name)
        self.assertTrue(isinstance(res, CallbackTask))

    def test_gen_registerlun_task(self):
        """
        test _gen_registerlun_task returns CallbackTask
        """
        sg_name = "sg123"
        self.setup_valid_san_model_no_shared_luns()
        san = self.context.query("san-emc")[0]
        lun = self.context.query("lun-disk")[0]

        res = self.plugin._gen_registerlun_task(lun, "Raid Group", san,
                                                sg_name)
        self.assertTrue(isinstance(res, CallbackTask))

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_sg_cb_task(self, mock_api_builder):
        """
        test create_sg_cb_task works correctly
        """
        sg_name = "sg123"
        san_type = "vnx1"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        user = "admin"
        san_scope = "Global"
        passwd_key = "key-for-san"
        passwd = "shroot"
        callbackapi = "Foo"
        san_name = "mysan"
        san = mock_api_builder("vnx1", None)
        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)

        self.plugin._saninit = MagicMock("_saninit")
        self.plugin._createsg = MagicMock("_createsg")
        res = self.plugin.create_sg_cb_task(callbackapi, san_type, san_name,
                                            sg_name, spa_ip, spb_ip, user,
                                            passwd_key, san_scope)
        self.assertTrue(res)
        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd,
                                                san_scope)
        self.plugin._createsg.assert_called_with(san, sg_name, san_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_hostinit_cb_task(self, mock_api_builder):
        """
        test create_hostinit_cb_task works correctly
        """
        sg_name = "sg123"
        san_type = "vnx1"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        san_scope = "Global"
        user = "admin"
        passwd_key = "key-for-san"
        passwd = "shroot"
        callbackapi = "Foo"
        host_name = "chaosmanor"
        host_ip = "10.45.121.22"
        wwn_a = "00:11:22:33:44:55:66:77:00:11:22:33:44:55:66:77"
        wwn_b = "00:11:22:33:44:55:66:78:00:11:22:33:44:55:66:78"
        san = mock_api_builder("vnx1", None)
        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)
        self.plugin._saninit = MagicMock("_saninit")
        self.plugin._create_host_rec = MagicMock("_create_host_rec")
        res = self.plugin.create_hostinit_cb_task(callbackapi, san_type,
                                                  sg_name, spa_ip, spb_ip,
                                                  host_ip, host_name,
                                                  [wwn_a, wwn_b], user,
                                                  passwd_key, san_scope)
        self.assertTrue(res)
        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd,
                                                san_scope)
        self.plugin._create_host_rec.assert_called_with(san, sg_name,
                                                        host_name, host_ip,
                                                        [wwn_a, wwn_b])

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_reglun_cb_task(self, mock_api_builder):
        """
        test create_reglun_cb_task works correctly
        """
        sg_name = "sg123"
        san_type = "vnx1"
        san_scope = "Global"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        lun_name = "mylun"
        lun_bootable = "true"
        user = "admin"
        passwd_key = "key-for-san"
        passwd = "shroot"
        callbackapi = "Foo"
        san_scope = "Global"
        san = mock_api_builder("vnx1", None)
        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)
        self.plugin._saninit = MagicMock("_saninit")
        self.plugin._registerlun = MagicMock("_registerlun")
        res = self.plugin.create_reglun_cb_task(callbackapi, san_type, sg_name,
                                                spa_ip, spb_ip, lun_name,
                                                "sp1", "Storage Pool",
                                                lun_bootable, user, passwd_key,
                                                san_scope)
        self.assertTrue(res)
        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd, san_scope)
        self.plugin._registerlun.assert_called_with(san, lun_name, "sp1",
                                                    "Storage Pool",
                                                    lun_bootable, sg_name)

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_lun_cb_task_lun_not_existing(self, mock_api_builder):
        """
        test create_lun_cb_task works correctly when lun doesn't exist
        """
        sg_name = "sg123"
        san_type = "vnx1"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        san_scope = "Global"
        lun_name = "APPLUN1"
        lun_bootable = "true"
        lun_size = "100000"
        bootable = "true"
        user = "admin"
        passwd_key = "key-for-san"
        passwd = "shroot"
        create = "true"
        sp_name = "mypool"
        sp_id = "12"
        sp_raid = "5"
        sp_size = "1Tb"
        sp_available = "500Gb"
        lun_fudge_size = 4
        lun_uuid = "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E"
        container_type = "Storage Pool"
        self.setup_valid_san_model_no_shared_luns()
        callbackapi = self.context
        linfo = LunInfo("33", lun_name,
                        lun_uuid,
                        sp_name, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")
        spinfo = StoragePoolInfo(sp_name, sp_id, sp_raid, sp_size,
                                 sp_available)
        san = mock_api_builder("vnx1", None)
        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)
        self.plugin._saninit = MagicMock("_saninit")
        self.plugin._createlun = MagicMock("_createlun", return_value=linfo)
        self.plugin._getpoolinfo = MagicMock("_getpoolinfo",
                                             return_value=spinfo)
        self.plugin._existinglun = MagicMock("_existinglun",
                                             return_value=False)
        self.plugin.create_lun_cb_task(callbackapi, san_type, lun_name,
                                       sp_name, container_type, lun_size,
                                       bootable, spa_ip,
                                       spb_ip, user, passwd_key, create,
                                       san_scope, "A", [])
        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd,
                                                san_scope)
        self.plugin._existinglun.assert_called_with(san, lun_name, lun_size,
                                                    sp_name,
                                                    container_type)
        self.plugin._createlun.assert_called_with(san, lun_name, lun_size,
                                                  sp_name, container_type,
                                                  bootable, "A")
        # check that the lun-disk uuid updated in model
        mylun = self.context.query("lun-disk", lun_name=lun_name)[0]
        self.assertEqual(mylun.uuid, lun_uuid.translate(None, ":-_"))

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_lun_cb_task_fencing_lun_not_existing(self,
                                                         mock_api_builder):
        """
        test create_lun_cb_task works correctly for fencing LUN when lun doesn't exist
        """
        sg_name = "sg123"
        san_type = "vnx1"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        san_scope = "Global"
        lun_name = "FENLUN1"
        lun_bootable = "true"
        lun_size = "100"
        bootable = "true"
        user = "admin"
        passwd_key = "key-for-san"
        passwd = "shroot"
        create = "true"
        rg_id = "0"
        sp_id = "12"
        sp_raid = "5"
        sp_size = "1Tb"
        sp_available = "500Gb"
        lun_fudge_size = 4
        lun_uuid = "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E"
        container_type = "Raid Group"
        self.setup_san_model_with_valid_fencing_luns()

        linfo = LunInfo("33", lun_name,
                        lun_uuid,
                        rg_id, lun_size,
                        "Raid Group", "5")

        callbackapi = self.context
        san = mock_api_builder("vnx1", None)
        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)
        self.plugin._saninit = MagicMock("_saninit")
        self.plugin._createlun = MagicMock("_createlun", return_value=linfo)
        self.plugin._existinglun = MagicMock("_existinglun",
                                             return_value=False)
        self.plugin.create_lun_cb_task(callbackapi, san_type, lun_name,
                                       rg_id, container_type, lun_size,
                                       bootable, spa_ip,
                                       spb_ip, user, passwd_key, create,
                                       san_scope, "A", [])
        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd,
                                                san_scope)
        self.plugin._existinglun.assert_called_with(san, lun_name, lun_size,
                                                    rg_id,
                                                    container_type)
        self.plugin._createlun.assert_called_with(san, lun_name, lun_size,
                                                  rg_id, container_type,
                                                  bootable, "A")
        # check that the lun-disk uuid updated in model
        luns = self.context.query("lun-disk")
        mylun = self.context.query("lun-disk", lun_name=lun_name)[0]
        self.assertEqual(mylun.uuid, lun_uuid.translate(None, ":-_"))

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_lun_cb_task_fencing_lun_existing(self, mock_api_builder):
        """
        test create_lun_cb_task works correctly for fencing LUN when lun exists
        """
        sg_name = "sg123"
        san_type = "vnx1"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        san_scope = "Global"
        lun_name = "FENLUN1"
        lun_bootable = "true"
        lun_size = "100"
        bootable = "true"
        user = "admin"
        passwd_key = "key-for-san"
        passwd = "shroot"
        create = "true"
        rg_id = "0"
        sp_id = "12"
        sp_raid = "5"
        sp_size = "1Tb"
        sp_available = "500Gb"
        lun_fudge_size = 4
        lun_uuid = "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E"
        container_type = "Raid Group"
        self.setup_san_model_with_valid_fencing_luns()

        callbackapi = self.context
        linfo = LunInfo("33", lun_name,
                        lun_uuid,
                        rg_id, lun_size,
                        "Raid Group", "5")
        san = mock_api_builder("vnx1", None)
        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)
        self.plugin._saninit = MagicMock("_saninit")
        self.plugin._createlun = MagicMock("_createlun", return_value=linfo)
        self.plugin._getrglun = MagicMock("_getrglun", return_value=linfo)
        self.plugin._existinglun = MagicMock("_existinglun", return_value=True)
        self.plugin.create_lun_cb_task(callbackapi, san_type, lun_name,
                                       rg_id, container_type, lun_size,
                                       bootable, spa_ip,
                                       spb_ip, user, passwd_key, create,
                                       san_scope, "A", [])
        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd,
                                                san_scope)
        self.plugin._getrglun.assert_called_with(san, lun_name, rg_id)
        self.plugin._existinglun.assert_called_with(san, lun_name, lun_size,
                                                    rg_id,
                                                    container_type)
        # check that the lun-disk uuid updated in model
        luns = self.context.query("lun-disk")
        mylun = self.context.query("lun-disk", lun_name=lun_name)[0]
        self.assertEqual(mylun.uuid, lun_uuid.translate(None, ":-_"))

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_lun_cb_task_lun_existing(self, mock_api_builder):
        """
        test create_lun_cb_task works correctly when lun exists
        """
        sg_name = "sg123"
        san_type = "vnx1"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        lun_name = "APPLUN1"
        lun_bootable = "true"
        lun_size = "100000"
        user = "admin"
        passwd_key = "key-for-san"
        passwd = "shroot"
        create = "true"
        sp_name = "mypool"
        sp_id = "12"
        sp_raid = "5"
        sp_size = "1Tb"
        sp_available = "500Gb"
        san_scope = "Global"
        lun_fudge_size = 4
        container_type = "Storage Pool"

        self.setup_valid_san_model_no_shared_luns()
        callbackapi = self.context
        linfo = LunInfo("33", lun_name,
                        "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                        sp_name, str(int(lun_size) + lun_fudge_size),
                        "StoragePool", "5")
        lun_uuid = "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E"
        spinfo = StoragePoolInfo(sp_name, sp_id, sp_raid, sp_size,
                                 sp_available)
        san = mock_api_builder("vnx1", None)
        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)
        self.plugin._saninit = MagicMock("_saninit")
        san.get_lun = MagicMock("get_lun", return_value=linfo)
        self.plugin._createlun = MagicMock("_createlun")
        self.plugin._getpoolinfo = MagicMock("_getpoolinfo",
                                             return_value=spinfo)
        self.plugin._existinglun = MagicMock("_existinglun", return_value=True)
        self.plugin.create_lun_cb_task(callbackapi, san_type, lun_name,
                                       sp_name, container_type, lun_size,
                                       lun_bootable, spa_ip,
                                       spb_ip, user, passwd_key, create,
                                       san_scope, "A", [])
        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd,
                                                san_scope)
        self.plugin._existinglun.assert_called_with(san, lun_name, lun_size,
                                                    sp_name,
                                                    container_type)
        self.assertFalse(self.plugin._createlun.called)
        # check that the lun-disk uuid updated in model
        mylun = self.context.query("lun-disk", lun_name=lun_name)[0]
        self.assertEqual(mylun.uuid, lun_uuid.translate(None, ":-_"))

    def test_rewrite_lun_uuid(self):
        lun1 = MagicMock(lun_name='lun1',
                        uuid='5cbb0b9e-d50c-4076-be0e-cc5c77df3534')
        lun2 = MagicMock(lun_name='lun2',
                        uuid='84d2f3b9_ad14_415d_b5a5_ca038684a0cb')
        lun3 = MagicMock(lun_name='lun3',
                        uuid='60:05:08:b1:00:1c:6b:f1:43:c5:d4:43:20:e4:c3:82')

        for lun in [lun1, lun2, lun3]:
            api = MagicMock(query=MagicMock(return_value=[lun]))
            self.plugin.rewrite_lun_uuid(api, lun.lun_name, lun.uuid)

        self.assertTrue(lun1.uuid.find('-') > 0)
        self.assertTrue(lun2.uuid.find('_') > 0)
        self.assertTrue(lun3.uuid.find(':') == -1)

    def test_validate_fen_luns_valid_rgid(self):
        """
        test that san plugin validates fencing luns in valid RG
        """

        self.setup_san_model_with_valid_fencing_luns()
        errors = self.plugin.validate_model(self)
        self.assertEqual(0, len(errors))

    def test_validate_update_luns_right_size(self):
        """
        test that an updated lun size should be bigger than previous value
        in the model
        """
        n1 = NodeMock('n1')
        lun_with_size_error = LunMock('lun_error',
                                      properties={'size': '9M'},
                                      applied_properties={'size': '10M'},
                                      is_updated=True)
        lun_with_no_errors = LunMock('lun_ok',
                                     properties={'size': '10M'},
                                     applied_properties={'size': '9M'},
                                     is_updated=True)
        n1.add_luns([lun_with_size_error, lun_with_no_errors])
        errors = self.plugin_validator._check_updated_luns_right_size([n1])
        self.assertEqual(len(errors), 1)
        error = errors[0]
        self.assertEqual(error.item_path, lun_with_size_error.name)
        self.assertTrue("Invalid Size" in error.error_message)

    def test_check_snaps_in_lun_expansion(self):
        """
        test that there is no snapshots in the luns
        that will be expanded
        """
        n1 = NodeMock('n1')
        lun_to_be_updated = LunMock('lun_error',
                                    properties={'size': '10M',
                                                'external_snap': 'false',
                                                'snap_size': 100},
                                    applied_properties={'size': '9M'},
                                    is_updated=True)
        n1.add_luns([lun_to_be_updated])
        snaps = [ItemMock("snapshot", external_snap="false",
                          snap_size=100, item_id="snapshot")]
        errors = self.plugin_validator._check_snaps_in_lun_expansion(
                snaps, [n1])
        self.assertEqual(len(errors), 1)
        error = errors[0]
        self.assertEqual(error.item_path, lun_to_be_updated.name)
        self.assertTrue("contains a snapshot" in error.error_message)

    def test_validate_update_no_updated_luns(self):
        """
        test that _check_updated_luns_right_size only applies if any lun
        is updated
        """
        n1 = NodeMock('n1')
        lun_with_size_error = LunMock('lun_error',
                                      properties={'size': '9M'},
                                      applied_properties={'size': '10M'},
                                      is_updated=False)
        lun_with_no_errors = LunMock('lun_ok',
                                     properties={'size': '10M'},
                                     applied_properties={'size': '9M'},
                                     is_updated=False)
        n1.add_luns([lun_with_size_error, lun_with_no_errors])
        errors = self.plugin_validator._check_updated_luns_right_size([n1])
        self.assertEqual(len(errors), 0)

    def test_check_validate_update_new_size_too_small(self):
        """
        test that _check_updated_luns_right_size fails validation if
        the new size is 1% or less bigger than the old size
        is updated
        """
        n1 = NodeMock('n1')
        lun_with_size_error = LunMock('lun_error',
                                      properties={'size': '201M'},
                                      applied_properties={'size': '200M'},
                                      is_updated=True)
        lun_with_no_errors = LunMock('lun_ok',
                                     properties={'size': '102M'},
                                     applied_properties={'size': '100M'},
                                     is_updated=True)
        n1.add_luns([lun_with_size_error, lun_with_no_errors])
        errors = self.plugin_validator._check_updated_luns_new_size_too_small(
                [n1])
        self.assertEqual(len(errors), 1)
        error = errors[0]
        self.assertEqual(error.item_path, lun_with_size_error.name)
        self.assertTrue("Invalid Size" in error.error_message)

    def test_validate_update_only_some_props_can_be_change_one_prop(self):
        """
        Test only some properties could be changed (only one prop)
        """
        n1 = NodeMock('n1')
        lun_with_size_error = LunMock('lun_will_update',
                                      properties={'size': '10M'},
                                      applied_properties={'size': '9M'},
                                      is_updated=True)
        lun_with_no_errors = LunMock('lun_with_snap_change',
                                     properties={'size': '9M',
                                                 'shared': 'true'},
                                     applied_properties={'size': '9M',
                                                         'shared': 'false'},
                                     is_updated=True)
        n1.add_luns([lun_with_size_error, lun_with_no_errors])
        errors = self.plugin_validator._check_valid_lun_updates([n1])
        self.assertEqual(len(errors), 1)
        error = errors[0]
        print error
        self.assertTrue("Only the size" in error.error_message)
        self.assertEqual(lun_with_no_errors.get_vpath(), error.item_path)

    def test_validate_update_only_some_props_can_be_change_many_prop(self):
        """
        Test only the size could be changed (more than one prop includ size)
        """
        n1 = NodeMock('n1')
        # size is ok, but snap_size could not be changed
        lun_with_error = LunMock('lun_will_update',
                                 properties={'size': '10M', 'shared': 'true',
                                             'lun_name': 'lun1'},
                                 applied_properties={'size': '9M',
                                                     'shared': 'false',
                                                     'lun_name': 'lun2'},
                                 is_updated=True)
        # size is not changin, but snap_size could not be changed
        lun_without_error = LunMock('lun_no_error',
                                    properties={'size': '10M'},
                                    applied_properties={'size': '9M'},
                                    is_updated=True)
        n1.add_luns([lun_with_error, lun_without_error])
        errors = self.plugin_validator._check_valid_lun_updates([n1])
        self.assertEqual(len(errors), 2)
        error = errors[0]
        print error
        self.assertTrue("Only the size" in error.error_message)
        self.assertEqual(lun_with_error.get_vpath(), error.item_path)

    def _setup_expand_lun_test(self):
        self.api_ctx = SanPluginContextMock()
        self.api_ctx.add_san(SanMock('san1'))
        self.api_ctx.add_storage('san1', StorageContainerMock('st1'))
        self.api_ctx.add_node('st1', NodeMock('n1'))
        self.api_ctx.add_node('st1', NodeMock('n2'))

    @patch('san_plugin.sanplugin.SanPlugin.get_lun_real_size')
    @patch('san_plugin.sanplugin.SanPlugin._get_sanapi')
    def test_updated_luns_generate_tasks_new_size_too_small(self,
                                                            mock_api_builder,
                                                            mock_get_lun_size_func):
        """
        Check that SAN plugin generate correct tasks for expanding luns
        case a) navi_size < new_size & navi_size < old_size
                error("new size of the lun is too small")
        """

        def sort_tasks(t1, t2):
            return cmp(t1.name, t2.name)

        new_size = '90M'
        old_size = '75M'
        navi_sizes = ['51', '1000']
        mock_get_lun_size_func.side_effect = navi_sizes
        mock_api_builder.side_effect = MagicMock()
        self._setup_expand_lun_test()
        self.api_ctx.add_lun('n1', LunMock('n1-lun_to_be_updated',
                                           properties={'size': new_size},
                                           applied_properties={
                                               'size': old_size},
                                           is_updated=True))
        self.api_ctx.add_lun('n1', LunMock('n1-neutral_lun',
                                           properties={},
                                           applied_properties={},
                                           is_updated=False))
        self.api_ctx.add_lun('n2', LunMock('n2-neutral_lun',
                                           properties={},
                                           applied_properties={},
                                           is_updated=False))
        self.api_ctx.add_lun('n2', LunMock('n2-lun_to_be_updated',
                                           properties={'size': '1000M'},
                                           applied_properties={'size': '100M'},
                                           is_updated=True))

        try:
            task = self.plugin.update_lun_task('callbackapi',
                                               'n1-lun_to_be_updated',
                                               True, 'santype', 'ip_a_mock',
                                               'ib_p_mock',
                                               old_size, new_size, 'size',
                                               'username', 'pkey',
                                               'login_scope')
            s = task
        except CallbackExecutionException, excep:
            self.assertTrue(
                "The new real size of the lun {lun_name} does not".format(
                        lun_name='n1-lun_to_be_updated') in str(excep))

    # Not needed anymore
    # @patch('san_plugin.sanplugin.SanPlugin.get_lun_real_size')
    # @patch('san_plugin.sanplugin.SanPlugin._get_sanapi')
    # def test_updated_luns_generate_tasks_manual_procedure_missing(self,
    #     mock_api_builder, mock_get_lun_size_func):
    #     """
    #     Check that SAN plugin generate correct tasks for expanding luns
    #     case b) navi_size < new_size & navi_size == old_size
    #             error("manual procedure for expanding the lun missed")
    #     """
    #     def sort_tasks(t1, t2):
    #         return cmp(t1.name, t2.name)

    #     new_size = '100M'
    #     old_size = '50M'
    #     # real size from lun should 51 because is bootable
    #     navi_sizes = ['51', '1000']
    #     mock_get_lun_size_func.side_effect = navi_sizes
    #     mock_api_builder.side_effect = MagicMock()

    #     self._setup_expand_lun_test()
    #     self.api_ctx.add_lun('n1', LunMock('n1-lun_to_be_updated',
    #         properties={'size': new_size},
    #         applied_properties={'size': old_size},
    #         is_updated=True))
    #     self.api_ctx.add_lun('n1', LunMock('n1-neutral_lun',
    #         properties={},
    #         applied_properties={},
    #         is_updated=False))
    #     self.api_ctx.add_lun('n2', LunMock('n2-neutral_lun',
    #         properties={},
    #         applied_properties={},
    #         is_updated=False))
    #     self.api_ctx.add_lun('n2', LunMock('n2-lun_to_be_updated',
    #         properties={'size': '1000M'},
    #         applied_properties={'size': '100M'},
    #         is_updated=True))
    #     from nose.tools import set_trace; set_trace()
    #     try:
    #       self.plugin.update_lun_task('callbackapi', 'n1-lun_to_be_updated',
    #             True, 'santype', 'ip_a_mock', 'ib_p_mock',
    #             old_size, new_size, 'size', 'username', 'pkey',
    #             'login_scope', True)
    #     except CallbackExecutionException, excep:
    #       self.assertTrue("Manual procedure for expanding the lun" in str(excep))

    # Not needed anymore
    # @patch('san_plugin.sanplugin.SanPlugin.get_lun_real_size')
    # @patch('san_plugin.sanplugin.SanPlugin._get_sanapi')
    # def test_updated_luns_generate_tasks_new_size_dont_match_model(self,
    #     mock_api_builder, mock_get_lun_size_func):
    #     """
    #     Check that SAN plugin generate correct tasks for expanding luns
    #     case c) navi_size < new_size & navi_size > old_size
    #             error("new size of the lun does not match new size in model")
    #     """
    #     def sort_tasks(t1, t2):
    #         return cmp(t1.name, t2.name)

    #     new_size = '100M'
    #     old_size = '40M'
    #     navi_sizes = ['51', '1000']
    #     mock_get_lun_size_func.side_effect = navi_sizes
    #     mock_api_builder.side_effect = MagicMock()

    #     self._setup_expand_lun_test()
    #     self.api_ctx.add_lun('n1', LunMock('n1-lun_to_be_updated',
    #         properties={'size': new_size},
    #         applied_properties={'size': old_size},
    #         is_updated=True))
    #     self.api_ctx.add_lun('n1', LunMock('n1-neutral_lun',
    #         properties={},
    #         applied_properties={},
    #         is_updated=False))
    #     self.api_ctx.add_lun('n2', LunMock('n2-neutral_lun',
    #         properties={},
    #         applied_properties={},
    #         is_updated=False))
    #     self.api_ctx.add_lun('n2', LunMock('n2-lun_to_be_updated',
    #         properties={'size': '1000M'},
    #         applied_properties={'size': '100M'},
    #         is_updated=True))
    #     from nose.tools import set_trace; set_trace()
    #     try:
    #       self.plugin.update_lun_task('callbackapi', 'n1-lun_to_be_updated',
    #             True, 'santype', 'ip_a_mock', 'ib_p_mock',
    #             old_size, new_size, 'size', 'username', 'pkey',
    #             'login_scope', True)
    #     except CallbackExecutionException, excep:
    #       self.assertTrue(
    #         ('The new real size of the lun {lun_name} does not match'
    #          'the current size in the litp model {real} != {new}').format(
    #           lun_name='n1-lun_to_be_updated', real='50', new='100') in str(excep))


    @patch('san_plugin.sanplugin.SanPlugin.get_lun_real_size')
    @patch('san_plugin.sanplugin.SanPlugin._get_sanapi')
    def test_updated_luns_generate_tasks_right_size(self,
                                                    mock_api_builder,
                                                    mock_get_lun_size_func):
        """
        Check that SAN plugin generate correct tasks for expanding luns
        case d) navi_size == new_size
                task must be generated, and message reported in the log
        """

        def sort_tasks(t1, t2):
            return cmp(t1.args[0], t2.args[0])

        new_size = '10M'
        old_size = '9M'
        navi_size = new_size
        mock_get_lun_size_func.side_effect = ['10', '1000']
        mock_api_builder.side_effect = MagicMock()

        self._setup_expand_lun_test()
        self.api_ctx.add_lun('n1', LunMock('n1-lun_to_be_updated',
                                           properties={'size': new_size},
                                           applied_properties={
                                               'size': old_size},
                                           is_updated=True))
        self.api_ctx.add_lun('n1', LunMock('n1-neutral_lun',
                                           properties={},
                                           applied_properties={},
                                           is_updated=False))
        self.api_ctx.add_lun('n2', LunMock('n2-neutral_lun',
                                           properties={},
                                           applied_properties={},
                                           is_updated=False))
        self.api_ctx.add_lun('n2', LunMock('n2-lun_to_be_updated',
                                           properties={'size': '1000M'},
                                           applied_properties={'size': '100M'},
                                           is_updated=True))

        tasks = self.plugin._create_updated_luns_tasks(self.api_ctx)
        self.assertEqual(len(tasks), 2)
        tasks.sort(sort_tasks)

        self.assertEqual(tasks[0].args[0], 'n1-lun_to_be_updated')
        self.assertEqual(tasks[0].callback, self.plugin.update_lun_task)

        self.assertEqual(tasks[1].args[0], 'n2-lun_to_be_updated')
        self.assertEqual(tasks[1].callback, self.plugin.update_lun_task)

    @patch('logging.Logger.info')
    @patch('san_plugin.sanplugin.SanPlugin.get_lun_real_size')
    @patch('san_plugin.sanplugin.SanPlugin._get_sanapi')
    def test_updated_luns_generate_tasks_lun_size_too_big(self,
                                                          mock_api_builder,
                                                          mock_get_lun_size_func,
                                                          log_mock):
        """
        Check that SAN plugin generate correct tasks for expanding luns
        case e) navi_size > new_size
                generate the task, but report the warning
        """

        def sort_tasks(t1, t2):
            return cmp(t1.name, t2.name)

        # log_mock.trace = MagicMock()
        # log_mock.trace.info = MagicMock()

        new_size = '10M'
        inew_size = '10'
        old_size = '9M'
        navi_size = new_size
        mock_get_lun_size_func.side_effect = ['11', '1000']
        mock_api_builder.side_effect = MagicMock()

        self._setup_expand_lun_test()
        lun_to_be_updated = LunMock('n1-lun_to_be_updated',
                                    properties={'size': new_size},
                                    applied_properties={'size': old_size},
                                    is_updated=True)
        self.api_ctx.add_lun('n1', lun_to_be_updated)

        self.api_ctx.add_lun('n1', LunMock('n1-neutral_lun',
                                           properties={},
                                           applied_properties={},
                                           is_updated=False))

        tasks = self.plugin._create_updated_luns_tasks(self.api_ctx)

        # The task is generated
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].args[0], 'n1-lun_to_be_updated')

        # If the task is executed, no exceptios is received, and a message
        # is logged in /var/log/messages
        mock_get_lun_size_func.side_effect = ['12', '1000']
        try:
            self.plugin.update_lun_task('callbackapi', 'n1-lun_to_be_updated',
                                        True, 'santype', 'ip_a_mock',
                                        'ib_p_mock',
                                        old_size, new_size, 'size', 'username',
                                        'pkey',
                                        'login_scope')
        except CallbackExecutionException, excep:
            msg = (
            'New real size of lun {lun_name} is bigger than new size set '
            'in the model {real_size} > {new_size}').format(
                    lun_name=lun_to_be_updated.name,
                    real_size='11',
                    new_size=inew_size)
            self.assertTrue(msg in str(excep))

        print
        for callm in log_mock.mock_calls:
            print callm
        log_mock.assert_any_call(msg)

    def test_validate_fen_luns_duplicate_names(self):
        """
        test that san plugin detects duplicate fencing lun names
        """
        self.setup_san_model_with_dup_fencing_luns()
        errors = self.plugin.validate_model(self)
        self.assertEqual(1, len(errors))

    def test_validate_fen_luns_invalid_size(self):
        """
        test that san plugin detects invalid fencing lun size
        """
        self.setup_san_model_with_bad_fencing_lun_size()
        errors = self.plugin.validate_model(self)
        self.assertEqual(2, len(errors))

    def test_validate_fen_luns_shared_not_bootable(self):
        """
        test that san plugin detects fencing luns marked shared
        test that san plugin detects fencing luns not marked bootable
        """
        self.setup_san_model_with_fencing_invalidprops()
        errors = self.plugin.validate_model(self)
        self.assertEqual(4, len(errors))

    def test_fencing_lun_task_generation(self):
        """
        Test that create_configuration generates appropriate fencing lun creation tasks
        """
        self.setup_san_model_with_valid_fencing_luns()
        tasks = self.plugin.create_configuration(self)

        # check the total number of tasks
        self.assertEqual(9, len(tasks))
        # look for create lun tasks one for each lun
        self.assertEqual(3, len([task for task in tasks
                                 if task.call_type == "create_lun_cb_task"]))
        # look for add lun to sg tasks one for each lun
        self.assertEqual(6, len([task for task in tasks
                                 if
                                 task.call_type == "create_reglun_cb_task"]))

        #
        # Phase 2 - examine tasks in more detail
        #
        lun_tasks = [task for task in tasks
                     if task.call_type == "create_lun_cb_task"]
        reg_tasks = [task for task in tasks
                     if task.call_type == "create_reglun_cb_task"]

        for tasklist in (lun_tasks, reg_tasks):
            self.check_task_args(tasklist)

    @patch("san_plugin.sanplugin.api_builder")
    def test_getrglun_foundlun(self, mock_api_builder):
        """
        Test _getrglun returns matching linfo object
        """
        san = mock_api_builder("vnx1", None)
        rg_id = "0"
        search_lun_name = "FEN1"
        linfolist = [LunInfo("12", "FEN1",
                             "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                             rg_id, "100M",
                             "RaidGroup", "5"),
                     LunInfo("13", "FEN2",
                             "50:01:43:80:15:7D:C4:5F:50:01:43:80:16:7D:C4:5E",
                             rg_id, "100M",
                             "RaidGroup", "5")]
        san.get_luns = MagicMock("get_luns", return_value=linfolist)
        linfo = self.plugin._getrglun(san, search_lun_name, rg_id)
        san.get_luns.assert_called_with(container=rg_id,
                                        container_type='RaidGroup')
        self.assertEqual(linfo.id, "12")

    @patch("san_plugin.sanplugin.api_builder")
    def test_getrglun_notfoundlun(self, mock_api_builder):
        """
        Test _getrglun throws exception if LUN not found
        """
        san = mock_api_builder("vnx1", None)
        rg_id = "0"
        search_lun_name = "FEN1"
        linfolist = []
        san.get_luns = MagicMock("get_luns", return_value=linfolist)
        myassert_raises_regexp(self, SanApiEntityNotFoundException,
                               "not found",
                               self.plugin._getrglun, san, rg_id,
                               search_lun_name)

    @skip
    def test_create_configuration_bg_luns(self):
        """
        test SAN plugin generates correct SP balancing from balancing groups
        edders TODO: this test no longer valid.  Need to write new bg tests
        """
        self.setup_san_model_with_balancing_group_luns()

        tasks = self.plugin.create_configuration(self)

        # Retrieve only create_lun tasks.
        # For shared LUNs, only 1 of 2+ tasks are to create the LUN
        # We are only interested in these tasks, so we filter with
        # args[10] == True - which is to control LUN creation.
        tasks = [task for task in tasks
                 if task.call_type == "create_lun_cb_task"]
        tasks = [t for t in tasks if t.args[10] == True]

        # Get LUNs from model. Shared LUNs are defined 2+ times.
        # here we make sure we only retrieve one occurence of them.
        luns = self.context.query("lun-disk")
        lun_names = list(set([lun.lun_name for lun in luns]))
        temp_luns = []
        for name in lun_names:
            for lun in luns:
                if name == lun.lun_name:
                    temp_luns.append(lun)
                    break
        luns = temp_luns

        # Get list of balancing groups from LUNs
        balancing_groups = []
        for lun in luns:
            bg = self.get_bg(lun)
            if bg not in balancing_groups:
                balancing_groups.append(bg)
                self.tprint(bg)

        # Verify: for each balancing group find matching luns
        # get tasks which match the LUN and count how many
        # assignments for sp_a or sp_b there are.
        # As long as the numbers are either balanced or out by
        # one, then all is good.
        for bg in balancing_groups:
            bg_luns = [l for l in luns if l.balancing_group == bg]
            sp_a = 0
            sp_b = 0
            for lun in bg_luns:
                lun_found = False
                for task in tasks:
                    if lun.lun_name == task.args[1]:
                        self.tprint("found task for lun %s" % lun.lun_name)
                        lun_found = True
                        if task.args[12] == 'A':
                            sp_a += 1
                        elif task.args[12] == 'B':
                            sp_b += 1
                self.assertTrue(lun_found)
            if abs(sp_a - sp_b) > 1:
                result = False
            else:
                result = True
            self.tprint("bg %s has %s A and %s B" % (bg, sp_a, sp_b))
            self.assertTrue(result)

    # TEST FUNCTIONS IN SAN_UTILS
    # ---------------------------
    def test_cmp_values(self):
        """
        Test cmp_values util function
        """
        self.assertEquals(0, cmp_values('1G', '1G'))
        self.assertEquals(0, cmp_values('1', '1'))
        self.assertEquals(1, cmp_values('2G', '1G'))
        self.assertEquals(1, cmp_values('2', '1'))

    def test_values_are_equal(self):
        """
        Test values_are_equal util function
        """
        self.assertTrue(values_are_equal('1', '1'))
        self.assertFalse(values_are_equal('1', '2'))

    def test_get_balancing_sp(self):
        """
        Test get_balancing_sp util function.
        """
        self.setup_san_model_with_balancing_group_luns()
        luns = self.context.query("lun-disk")

        # Get list of balancing groups from LUNs
        balancing_groups = []
        for lun in luns:
            bg = self.get_bg(lun)
            if bg not in balancing_groups:
                balancing_groups.append(bg)

        sps = get_balancing_sp(luns)

        for group in balancing_groups:
            group_found = False
            if group in sps:
                group_found = True
            self.assertEqual(True, group_found)

        sp_a = len([s for s in sps.values() if s == 'A'])
        sp_b = len([s for s in sps.values() if s == 'B'])

        if abs(sp_a - sp_b) > 1:
            result = False
        else:
            result = True
        self.assertTrue(result)

    def test_get_bg(self):
        """
        Test get_bg util function
        """
        self.setup_san_model_with_balancing_group_luns()
        luns = self.context.query("lun-disk")
        lun_names = list(set([lun.lun_name for lun in luns]))

        for lun in luns:
            bg = self.get_bg(lun)
            self.assertEqual(bg, get_bg_san_utils(lun))

    def test_toggle_sp(self):
        """
        Test toggle_sp util function
        """
        self.assertEqual('A', toggle_sp('B'))
        self.assertEqual('B', toggle_sp('A'))
        self.assertEqual('auto', toggle_sp('auto'))

    def test_get_lun_names_for_bg(self):
        """
        Test get_lun_names_for_bg util function
        """

        self.setup_san_model_with_balancing_group_luns()
        model_luns = self.context.query("lun-disk")
        returned_luns_for_bg = get_lun_names_for_bg(model_luns, "even")
        lun_names_bg_even = ["lun1_1", "lun1_2", "lun1_3", "lun2_1", "lun2_2",
                             "lun2_3", ]
        for name in lun_names_bg_even:
            self.assertTrue(name in returned_luns_for_bg,
                            "LUN not found in retrieved list")
        returned_luns_for_nonexistant_bg = get_lun_names_for_bg(model_luns,
                                                                "FAKE")
        empty_list_of_luns = get_lun_names_for_bg(model_luns, "FAKE")
        self.assertTrue(len(empty_list_of_luns) == 0,
                        "Length of non existant LUN list somehow not 0")

    @patch("san_plugin.sanplugin.api_builder")
    def test_get_balanced_sp(self, mock_api_builder):
        """
        Test _get_balanced_sp function
        """

        # SETUP LUN DATA
        bg_a = ("a1", "a2", "a3", "a4")
        bg_b = ("b1", "b2", "b3", "b4")
        bg_mix = ("mix1", "mix2", "mix3", "mix4")
        san_luns = []
        uuid = "50:01:43:80:16:7D:C4:5F:50:01:43:80:16:7D:C4:5E"
        args = (uuid, "pool1", "5", "StoragePool", "5")
        for lun_name in bg_a:
            san_luns.append(LunInfo(1, lun_name, *args, controller="A"))
        for lun_name in bg_b:
            san_luns.append(LunInfo(1, lun_name, *args, controller="B"))
        sp = 'A'
        for lun_name in bg_mix:
            san_luns.append(LunInfo(1, lun_name, *args, controller=sp))
            sp = "A" if sp == "B" else "B"

        # SETUP MOCKING
        san = mock_api_builder("vnx1", None)
        san.get_luns = MagicMock(name="get_luns", return_value=san_luns)

        # TESTS
        self.assertTrue(self.plugin._get_balanced_sp(san, 'A', bg_mix) == 'A')
        self.assertTrue(self.plugin._get_balanced_sp(san, 'B', bg_mix) == 'B')
        self.assertTrue(self.plugin._get_balanced_sp(san, 'B', bg_a) == 'B')
        self.assertTrue(self.plugin._get_balanced_sp(san, 'A', bg_a) == 'B')
        self.assertTrue(self.plugin._get_balanced_sp(san, 'A', bg_b) == 'A')
        self.assertTrue(self.plugin._get_balanced_sp(san, 'B', bg_b) == 'A')

    def test_validate_update_san_ok(self):
        updated_name = 'vnx-02'

        applied_props = {'username' : 'admin1',
                         'name' : 'vnx-01',
                         'storage_network' : 'storage',
                         'storage_site_id' : 'ENM666',
                         'login_scope' : 'global',
                         'password_key' : 'key-for-san1',
                         'ip_b' : '10.10.10.10',
                         'san_type' : 'vnx2',
                         'ip_a' : '10.10.10.11'}

        updated_props = {'username' : 'admin2',
                         'name' : updated_name,
                         'storage_network' : 'storage',
                         'storage_site_id' : 'ENM666',
                         'login_scope' : 'global',
                         'password_key' : 'key-for-san2',
                         'ip_b' : '10.10.10.12',
                         'san_type' : 'vnx2',
                         'ip_a' : '10.10.10.13'}

        san = SanMock('san1',
                      properties=updated_props,
                      applied_properties=applied_props,
                      is_updated=True)

        san_context = SanPluginContextMock()
        san_context.add_san(san)
        tasks = self.plugin._create_san_update_tasks(san_context)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].args[0], updated_name)
        self.assertEqual(tasks[0].callback, self.plugin.update_san_cb_task)

    def test_validate_no_update_to_san(self):

        applied_props = {'username' : 'admin1',
                         'name' : 'vnx-01',
                         'storage_network' : 'storage',
                         'storage_site_id' : 'ENM666',
                         'login_scope' : 'global',
                         'password_key' : 'key-for-san1',
                         'ip_b' : '10.10.10.10',
                         'san_type' : 'vnx2',
                         'ip_a' : '10.10.10.11'}

        san = SanMock('san1',
                      applied_properties=applied_props,
                      is_updated=False)

        san_context = SanPluginContextMock()
        san_context.add_san(san)
        tasks = self.plugin._create_san_update_tasks(san_context)
        self.assertEqual(tasks, [])

    def test_update_lun_task_is_true(self):
        ret = self.plugin.update_san_cb_task('callback', 'san1')
        self.assertEqual(ret, True)

    def test_gen_storage_pool_task(self):
        self.setup_valid_san_model_no_shared_luns()
        san = self.context.query("san-emc")[0]
        pool_name = 'ENM1234'
        disk_count = '15'
        raid_level = '5'

        res = self.plugin._gen_storage_pool_task(san, pool_name, disk_count,
                                                 raid_level)

        self.assertTrue(isinstance(res, CallbackTask))

    @patch("san_plugin.sanplugin.api_builder")
    def test_create_storagepool_cb_task(self, mock_api_builder):
        san_type = "unity"
        spa_ip = "1.2.3.4"
        spb_ip = "4.5.6.7"
        user = "admin"
        login_scope = "Global"
        passwd_key = "key-for-san"
        passwd = "shroot"
        callbackapi = "Foo"
        san_name = "SAN01"
        pool_name = 'ENM1234'
        disk_count = '15'
        raid_level = '5'
        san = mock_api_builder(san_type, None)

        self.plugin._get_san_password = MagicMock("_get_san_password",
                                                  return_value=passwd)

        self.plugin._saninit = MagicMock("_saninit")
        self.plugin._createsp = MagicMock("_createsp")

        res = self.plugin.create_storagepool_cb_task(callbackapi, san_type,
                                                     san_name, spa_ip, spb_ip,
                                                     user, passwd_key,
                                                     login_scope, pool_name,
                                                     disk_count, raid_level)
        self.assertTrue(res)

        self.plugin._get_san_password.assert_called_with(callbackapi, user,
                                                         passwd_key)
        self.plugin._saninit.assert_called_with(san, spa_ip, spb_ip, user,
                                                passwd, login_scope)

        self.plugin._createsp.assert_called_with(san, pool_name, disk_count,
                                                 san_name, raid_level)

    @patch("san_plugin.sanplugin.api_builder")
    @patch("san_plugin.sanplugin.SanPlugin._validate_existing_storage_pool")
    def test_createsp(self, mock_validate_pool, mock_api_builder):
        san = mock_api_builder("unity", None)

        # Happy path test
        san.check_storage_pool_exists.return_value = False
        create_pool = self.plugin._createsp(san, 'ENM1234', '15', 'SAN01', '5')
        self.assertTrue(create_pool)

        # Pool already exists, but passes validation
        san.check_storage_pool_exists.return_value = True
        mock_validate_pool.return_value = True
        create_pool = self.plugin._createsp(san, 'ENM1234', '15', 'SAN01', '5')
        self.assertTrue(create_pool)

        # Pool already exists, but fails validation
        san.check_storage_pool_exists.return_value = True
        mock_validate_pool.return_value = False
        self.assertRaises(CallbackExecutionException, self.plugin._createsp,
                          san, 'ENM1234', '15', 'SAN01', '5')


    @patch("san_plugin.sanplugin.api_builder")
    def test_validate_existing_storage_pool(self, mock_api_builder):
        san = mock_api_builder("unity", None)
        san.get_storage_pool.side_effect = [MagicMock(disks='15', raid='5'),
                                            MagicMock(disks='7', raid='5'),
                                            MagicMock(disks='15', raid='10')]

        # Happy Path test
        valid_pool = self.plugin._validate_existing_storage_pool('ENM1234',
                                                                 '15',
                                                                 '5',
                                                                 san)
        self.assertTrue(valid_pool)

        # Fail verification if number of disks don't match
        valid_pool = self.plugin._validate_existing_storage_pool('ENM1234',
                                                                 '15',
                                                                 '5',
                                                                 san)
        self.assertFalse(valid_pool)

        # Fail verification if RAID level doesn't match
        valid_pool = self.plugin._validate_existing_storage_pool('ENM1234',
                                                                 '15',
                                                                 '5',
                                                                 san)
        self.assertFalse(valid_pool)

    def test_hba_wwn_task_generated(self):
        """
        Verify that SAN plugin can generate HBA WWN update tasks
        """
        self.setup_basic_vcs_model()
        self.model.set_all_applied()
        self.model.update_item("/infrastructure/systems/system1/controllers/hba1",hba_porta_wwn="aa:bb:cc:dd:ee:ff:11:22")
        self.model.update_item("/infrastructure/systems/system1/controllers/hba1",hba_portb_wwn="33:44:55:66:aa:bb:cc:dd")
        self.model.update_item("/infrastructure/systems/system2/controllers/hba2",hba_portb_wwn="22:11:ff:ee:dd:cc:bb:aa")
        tasks = self.plugin.create_configuration(self)
        # Generate task for each hba wwn parameter
        self.assertEqual(3, len(tasks))
