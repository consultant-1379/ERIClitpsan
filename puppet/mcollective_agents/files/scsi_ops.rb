require 'json'
module MCollective
  module Agent
    class Scsi_ops<RPC::Agent
      begin
        PluginManager.loadclass("MCollective::Util::LogAction")
        log_action = Util::LogAction
      rescue LoadError => e
        raise "Cannot load logaction util: %s" % [e.to_s]
      end
            
      action "scan_scsi" do
        cmd = "for host in $(ls /sys/class/fc_host/); do  echo 1 > /sys/class/fc_host/$host/issue_lip; echo \'- - -\' > /sys/class/scsi_host/$host/scan; done"

        log_action.debug(cmd, request)
        reply[:retcode] = run(cmd,
                              :stdout => :out,
                              :stderr => :err,
                              :chomp => true)
      end

      action "rescan_DM" do
        uuid = request[:uuid]
        cmd = "/usr/bin/python /opt/mcollective/mcollective/agent/rescan_DM.py " + uuid
        log_action.debug(cmd, request)
        reply[:retcode] = run(cmd,
                              :stdout => :out,
                              :stderr => :err,
                              :chomp => true)
      end

      action "rescan_VX" do
        lunid = request[:lunid]
        cmd = "/usr/bin/python /opt/mcollective/mcollective/agent/rescan_VX.py " + lunid
        log_action.debug(cmd, request)
        reply[:retcode] = run(cmd,
                              :stdout => :out,
                              :stderr => :err,
                              :chomp => true)
      end

      action "add_multipath" do
        uuid = request[:uuid]
        cmd = "/usr/bin/python /opt/mcollective/mcollective/agent/add_multipath.py " + uuid
        log_action.debug(cmd, request)
        reply[:retcode] = run(cmd,
                              :stdout => :out,
                              :stderr => :err,
                              :chomp => true)
      end
    end
  end
end
