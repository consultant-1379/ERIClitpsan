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
import subprocess
import re

def info(msg):
    preamble = "%s: INFO: " % sys.argv[0]
    sys.stdout.write(preamble + msg + '\n')


def err(msg, exit_code=1):
    preamble = "%s: ERROR: " % sys.argv[0]
    sys.stderr.write(preamble + msg + '\n')
    sys.exit(exit_code)


def run_command(cmd):
    """
    Runs a command on the OS.

    :param cmd: The command to run.
    :type cmd: :class:`str`
    :returns: The standard output of the command.
    :rtype: :class:`str`
    """

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             shell=True)
    stdout, stderr = proc.communicate()

    if proc.returncode != 0:
        err(" cmd exited with %s: %s %s" % (proc.returncode, stdout, stderr))
    return stdout


def get_multipath_device(uuid):
    """
    Gets the multipath device for a given UUID.

    :param uuid: The UUID.
    :type path: :class:`str`
    :returns: The multipath device.
    :rtype: :class:`str`
    """

    cmd = 'multipath -lvv'
    stdout = run_command(cmd)
    mpath_lines = stdout.split("\n")
    # mpath device will be first piece in line where UUID is in that line
    mpath = [i for i in mpath_lines if uuid in i][0].split()[0]
    return mpath


def get_lun_size(uuid):
    """
    Get the size of the LUN for the given UUID.

    :param uuid: The UUID.
    :type uuid: :class:`str`
    :returns: The size of the LUN.
    :rtype: :class:`str`
    """

    cmd = 'multipath -lvv'
    stdout = run_command(cmd)
    mpath_lines = stdout.split("\n")
    # size will get piece containing size e.g. "10G" in line after
    # line containing uuid
    # retrieve line after line containing uuid
    size = mpath_lines[[[i, j] for i, j in enumerate(mpath_lines)\
           if uuid in j][0][0] + 1]
    # split on whitespace and get piece containing size
    size = size.split()[0]
    # split string e.g. "size=10G" and get "10G" piece
    size = size.split("=")[1]
    return size


def get_scsi_paths(uuid):
    """
    Gets the SCSI paths to a LUN of the given UUID.

    :param uuid: The UUID of the LUN.
    :type uuid: :class:`str`
    :returns: A list of SCSI paths
    :rtype: :class:`list`
    """

    cmd = 'multipath -lvv'
    stdout = run_command(cmd)
    mpath_lines = stdout.split("\n")
    # get lines containing mpath
    mpaths = [(i, j) for i, j in enumerate(mpath_lines) if "mpath" in j]
    # get the index of the line containing the UUID
    uuid_line_index = [i[0] for i in mpaths if uuid in i[1]][0]
    path_list = []
    # if the index is the last one in the list of indexed lines containing
    # mpath, get all lines until end of file from that index
    if uuid_line_index == mpaths[-1][0]:
        for line in range(uuid_line_index + 2, len(mpath_lines)):
            path_list.append(mpath_lines[line])
    # otherwise get all up until next index
    else:
        # lines we need are the lines 2 after our line containing the UUID
        # up until the next line containing mpath. To get this, the index
        # in our tuple list is needed, retrieved using code below
        for line_index in range(uuid_line_index + 2,
                                mpaths[[x for x, y in enumerate(mpaths)
                                if y[0] == uuid_line_index][0] + 1][0]):
            path_list.append(mpath_lines[line_index])
    for i in range(len(path_list)):
        for path in path_list[i].split():
            if re.match("^[0-9][0-9]?:[0-9][0-9]?:[0-9][0-9]?:[0-9][0-9]?",
                        path):
                path_list[i] = path

    for i in path_list:
        if "policy" in i:
            path_list.remove(i)
    path_list = filter(None, path_list)
    return path_list


def scan_scsi_paths(path_list):
    """
    Scans the SCSI paths in a list of paths.

    :param path_list: The list of SCSI paths to scan.
    :type path_list: :class:`list`
    """

    for p in path_list:
        cmd = "echo 1 > /sys/class/scsi_device/" + p + "/device/rescan"
        run_command(cmd)


def resize_multipath(device):
    """
    Resize multipath_device

    """
    cmd = "/sbin/multipathd resize map " + device
    run_command(cmd)


if __name__ == "__main__":
    uuid = None
    if len(sys.argv) > 1:
        uuid = sys.argv[1].lower()
    else:
        err("No UUID supplied")

    device = get_multipath_device(uuid)
    original_size = get_lun_size(uuid)
    paths = get_scsi_paths(uuid)
    scan_scsi_paths(paths)
    resize_multipath(device)
    expanded_size = get_lun_size(uuid)

    if original_size == expanded_size:
        info("LUN expansion ineffective. Size not increased.")

    info("rescan_DM complete for uuid %s, size is %s" % (uuid, expanded_size))
    sys.exit(0)
