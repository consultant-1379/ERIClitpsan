##############################################################################
# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################
import sys
import os
import subprocess
import time


def err(msg, exit_code=1):
    preamble = "%s: ERROR: " % sys.argv[0]
    sys.stderr.write(preamble + msg + '\n')
    sys.exit(exit_code)


def run_command(cmd, exit_on_err=True):
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         shell=True)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            if exit_on_err:
                err("Command %s failed with:\n%s\n%s" \
                               % (cmd, stdout, stderr), proc.returncode)
            else:
                return proc.returncode, stderr
    except Exception, e:
        if exit_on_err:
            err("Failed to run command %s" % cmd)
        else:
            return proc.returncode, stderr
    return proc.returncode, stdout


def get_emc_device(lun_number):
    """
    Returns the VX device file for lun_number
    :param lun_number: The LUN number
    :type integer
    :returns: The device name in a list.
    :rtype: :class:`variable`
    """
    try:
        lun_number = str(int(lun_number))
        cmd = "/usr/sbin/vxdisk list -o alldgs"
        pattern = '_%s ' % lun_number
        ret, stdout = run_command(cmd)
        for line in stdout.split('\n'):
            if pattern in line:
                return line.split()[0]
    except Exception, e:
        pass
    raise Exception("No device found")


def get_multipath_devices(emc_device):
    """
    Work out which mutipath devices belong to the device name.
    :param emc_device: The VX device pointing to the LUN.
    :type file: :class:`file`
    :returns: The lines from the as a list.
    :rtype: :class:`list`
    """
    try:
        cmd = "/usr/sbin/vxdmpadm getsubpaths dmpnodename=" + emc_device
        devices = []
        ret, stdout = run_command(cmd)
        for line in stdout.split('\n'):
            if "=======" in line or "ENCLR-TYPE" in line:
                continue
            try:
                devices.append(line.split()[0])
            except:
                pass
        if len(devices) == 0:
            err("get_multipath_devices: Failed to find any devices for %s " \
                            % emc_device)
    except Exception, e:
        err("get_multipath_devices: Failed with %s: " % e)
    return devices


def update_block_devices(devices):
    """
    Update each of the multipath devices.
    :param devices: The list of devices to update
    :type list:
    :returns: Return value of the UNIX command.
    :rtype: integer
    """
    try:
        for dev in devices:
            for retry in range(1, 5):
                cmd = "/sbin/blockdev --rereadpt /dev/" + dev
                ret, out = run_command(cmd, exit_on_err=False)
                if ret == 0:
                    break
                time.sleep(5 * retry)
            if ret != 0:
                err("Failed to update block devices: %s" % out)
    except Exception, e:
        err("update_block_devices: Failed with %s: " % e)
    return True


def rescan_vx(lun_id):
    lun_number = sys.argv[1]
    try:
        emc_device = get_emc_device(lun_number)
    except:
        print "No device found, nothing to do."
        sys.exit(0)

    devices = get_multipath_devices(emc_device)
    update_block_devices(devices)
    print ("%s completed successfully" % sys.argv[0])

if __name__ == '__main__':
    argnum = len(sys.argv)
    if argnum > 1:
        rescan_vx(sys.argv[1])
    else:
        err("No LUN number argument supplied")
    sys.exit(0)
