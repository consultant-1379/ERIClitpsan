metadata    :name        => "scsi_ops",
            :description => "API to SCAN/RESCAN the SCSI bus on a host",
            :author      => "ecoophi",
            :license     => "Ericsson",
            :version     => "1.0",
            :url         => "http://ericsson.com/",
            :timeout     => 60
 
action "scan_scsi", :description => "Scans all SCSI busses" do
    display :always

    output :retcode,
           :description => "The output of the command",
           :display_as  => "Command result",
           :default     => "no output"
end

action "rescan_DM", :description => "Re-scans a selected set of SCSI devices" do
    display :always
 
    input  :uuid,
           :prompt      => "uuid",
           :description => "The UUID of the LUN to be added",
           :type        => :string,
           :validation  => '',
           :optional    => false,
           :maxlength   => 32

    output :retcode,
           :description => "The exit code from running the command",
           :display_as => "Result code"
    output :out,
           :description => "The stdout from running the command",
           :display_as => "out"
    output :err,
           :description => "The stderr from running the command",
           :display_as => "err"
end

action "rescan_VX", :description => "Re-scans a selected set of SCSI devices" do
    display :always
 
    input  :lunid,
           :prompt      => "lunid",
           :description => "The LUN ID of the LUN to be expanded",
           :type        => :string,
           :validation  => '',
           :optional    => false,
           :maxlength   => 10

    output :retcode,
           :description => "The exit code from running the command",
           :display_as => "Result code"
    output :out,
           :description => "The stdout from running the command",
           :display_as => "out"
    output :err,
           :description => "The stderr from running the command",
           :display_as => "err"
end

action "add_multipath", :description => "Add a new LUN record to /etc/multipath.conf" do
    display :always

    input  :uuid,
           :prompt      => "uuid",
           :description => "The UUID of the LUN to be added",
           :type        => :string,
           :validation  => '',
           :optional    => false,
           :maxlength   => 32

    output :retcode,
           :description => "The exit code from running the command",
           :display_as => "Result code"
    output :out,
           :description => "The stdout from running the command",
           :display_as => "out"
    output :err,
           :description => "The stderr from running the command",
           :display_as => "err"
end

