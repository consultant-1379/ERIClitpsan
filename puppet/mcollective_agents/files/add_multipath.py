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
from subprocess import Popen, PIPE, STDOUT

MPATH_FILE = "/etc/multipath.conf"


def err(msg, exit_code=1):
    preamble = "%s: ERROR: " % sys.argv[0]
    sys.stderr.write(preamble + msg + '\n')
    sys.exit(exit_code)


def get_index(lines, match):
    return [i for i, s in enumerate(lines) if s.startswith(match)][0]


def uuid_exists(lines, uuid, str):
    try:
        start = get_index(lines, str)
        end = get_index(lines[start::], '}') + start
        for line in lines[start:end]:
            if uuid in line:
                return True
    except Exception, e:
        err("Unable to check \"%s\" entry in multipath.conf: %s" % (str, e))

    return False


def blacklist_exception_exists(lines, uuid):
    return uuid_exists(lines, uuid, 'blacklist_exceptions')


def multipath_entry_exists(lines, uuid):
    return uuid_exists(lines, uuid, 'multipaths')


def normalise_uuid(uuid):
    """
    Modifies the UUID to remove any colons, makes all chars lowercase and
    prepends 3 to the result.

    :param uuid: The UUID to modify.
    :type uuid: :class:`str`
    :returns: The modified UUID.
    :rtype: :class:`str`
    """

    try:
        normalised_uuid = uuid.replace(":", "")
        normalised_uuid = normalised_uuid.lower()
        normalised_uuid = "3" + normalised_uuid
    except Exception, e:
        err("Failed to normalise UUID %s: %s" % (uuid, e))

    try:
        int(normalised_uuid, 16)
    except:
        err("UUID is not valid hex string %s " % uuid)

    if len(normalised_uuid) != 33:
        err("Invalid UUID length %s " % uuid)

    return normalised_uuid


def read_mpath_file(path=MPATH_FILE):
    """
    Returns the multipath.conf contents as a list of strings.

    :param path: The path to the file.
    :type path: :class:`str`
    :returns: The lines from the as a list.
    :rtype: :class:`list`
    """

    try:
        mpath_handle = open(path, "r")
    except Exception, e:
        err("Failed to open multipath.conf: %s" % e)

    try:
        contents = mpath_handle.readlines()
        mpath_handle.close()
    except Exception, e:
        err("Failed to read multipath.conf: %s" % e)

    return contents


def add_blacklist_exceptions(lines, uuid):
    """
    Inserts the uuid of a newly created LUN into the blacklist exception
    section in the lines of a multipath.conf file.

    :param lines: A list of lines from the multipath.conf file.
    :type lines: :class:`list`
    :param uuid: The UUID of the newly created LUN.
    :type uuid: :class:`str`
    :returns: The lines with the newly added uuid.
    :rtype: :class:`list`
    """

    blacklist_exception = "        wwid \"%s\"\n" % uuid

    try:
        start = get_index(lines, 'blacklist_exceptions')
        end = get_index(lines[start::], '}') + start
        lines.insert(end, blacklist_exception)
    except Exception, e:
        err("Unable to parse blacklist exceptions in multipath.conf: %s" % (e))

    return lines


def add_multipath(lines, uuid):
    """
    Inserts a multipath block containing the uuid of a newly created LUN into
    the multipaths section section in the lines of a multipath.conf file.

    :param lines: A list of lines from the multipath.conf file.
    :type lines: :class:`list`
    :param uuid: The UUID of the newly created LUN.
    :type uuid: :class:`str`
    :returns: The lines with the newly added multipath block.
    :rtype: :class:`list`
    """

    multipath_entry = [
        "        multipath {\n",
        "                uid 0\n",
        "                gid 0\n",
        "                wwid \"%s\"\n" % uuid,
        "                mode 0600\n",
        "        }\n"]

    start = get_index(lines, 'multipaths')
    end = get_index(lines[start::], '}') + start

    for entry in reversed(multipath_entry):
        lines.insert(end, entry)

    return lines


def write_mpath_file(lines, path=MPATH_FILE):
    """
    Writes a line or sequence of lines to a file.

    :param path: The path to the file.
    :type path: :class:`str`
    :param line: A string if supplied, otherwise None.
    :type line: :class:`str` or :class:`None`
    :param lines: A list of strings if supplied, otherwise None.
    :type lines: :class:`list` or :class:`None`
    """

    try:
        mpath_handle = open(path, "w")
        mpath_handle.writelines(lines)
        mpath_handle.close()
    except Exception, e:
        err("Failed to write changes to multipath.conf: %s" % e)


def reload_mpath():
    cmd = "/sbin/multipath -r"
    try:
        proc = Popen(cmd, stdout=PIPE, stderr=STDOUT,
                        shell=True)
        stdout, stderr = proc.communicate()

        if proc.returncode != 0:
            err("Multipath reload exit %s: %s" % (proc.returncode, stdout))

    except Exception, e:
        err("Failed to reload multipath device maps: %s" % e)


def add_uuid_to_multipath(uuid):
    """
    Makes the modifications the multipath.conf file as expected;
    adds a new blacklist exception
    adds a new multipaths block.

    :param uuid: The UUID to insert to both areas.
    :type uuid: :class:`str`
    """

    uuid = normalise_uuid(uuid)
    mpath_contents = read_mpath_file()

    mpath_modified = False

    if not blacklist_exception_exists(mpath_contents, uuid):
        mpath_contents = add_blacklist_exceptions(mpath_contents, uuid)
        mpath_modified = True

    if not multipath_entry_exists(mpath_contents, uuid):
        mpath_contents = add_multipath(mpath_contents, uuid)
        mpath_modified = True

    if mpath_modified:
        write_mpath_file(mpath_contents)
        reload_mpath()
        print ("Multipath.conf edited successfully")
    else:
        print ("No need to edit multipath.conf")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        add_uuid_to_multipath(sys.argv[1])
    else:
        err("No UUID argument supplied", 1)

    sys.exit(0)
