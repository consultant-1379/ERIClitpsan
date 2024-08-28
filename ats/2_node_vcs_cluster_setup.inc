litp create -t os-profile -p /software/profiles/rhel -o name='sample-profile' path='/profiles/node-iso/'

litp create -t vlan -p /ms/network_interfaces/vlan_270_storage -o ipaddress="10.10.20.11" network_name="storage" device_name="eth1.270"

litp create -t system -p /infrastructure/systems/system1 -o system_name='SYS1'
litp create -t system -p /infrastructure/systems/system2 -o system_name='SYS2'

litp create -t network -p /infrastructure/networking/networks/ms_network -o name='nodes' subnet='10.10.10.0/24' litp_management=true

litp create -t storage-profile-base -p /infrastructure/storage/storage_profiles/profile_1

litp create -t deployment -p /deployments/local
litp create -t vcs-cluster -p /deployments/local/clusters/db_cluster -o default_nic_monitor=mii cluster_type=sfha low_prio_net=services cluster_id=21977 llt_nets=heartbeat1,heartbeat2

litp create -t node  -p /deployments/local/clusters/db_cluster/nodes/node1        -o hostname='node1'
litp inherit -p /deployments/local/clusters/db_cluster/nodes/node1/system -s /infrastructure/systems/system1
litp inherit -p /deployments/local/clusters/db_cluster/nodes/node1/os -s /software/profiles/rhel
litp create -t network-interface -p /deployments/local/clusters/db_cluster/nodes/node1/network_interfaces/if0 -o network_name=nodes ipaddress=10.10.10.101
litp inherit -p /deployments/local/clusters/db_cluster/nodes/node1/storage_profile -s /infrastructure/storage/storage_profiles/profile_1

litp create -t node -p /deployments/local/clusters/db_cluster/nodes/node2        -o hostname='node2'
litp inherit -p /deployments/local/clusters/db_cluster/nodes/node2/system -s /infrastructure/systems/system2
litp inherit -p /deployments/local/clusters/db_cluster/nodes/node2/os -s /software/profiles/rhel
litp create -t network-interface -p /deployments/local/clusters/db_cluster/nodes/node2/network_interfaces/if0 -o network_name=nodes ipaddress=10.10.10.102
litp inherit -p /deployments/local/clusters/db_cluster/nodes/node2/storage_profile -s /infrastructure/storage/storage_profiles/profile_1
