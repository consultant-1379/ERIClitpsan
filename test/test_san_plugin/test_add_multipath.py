# COPYRIGHT Ericsson AB 2015
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

import os, StringIO, unittest
from nose.plugins.skip import SkipTest
from mock import patch
from mock import MagicMock
import sys

sys.path.append('./puppet/mcollective_agents/files')

from add_multipath import (get_index, uuid_exists, blacklist_exception_exists, multipath_entry_exists,
normalise_uuid, read_mpath_file, add_blacklist_exceptions, add_multipath, write_mpath_file,
reload_mpath, add_uuid_to_multipath)


class TestMultipath(unittest.TestCase):


    def test_get_index(self):
        """
        Verify correct index returned for final closing curly brace in file.
        """

        lines = ["multipaths {", "banana", "orange", "multipath {", "snapple",
                 "bean", "}", "multipath {", "bread", "milk", "}", "butter",
                 "multipath {", "}", "blue", "}", "CHeck", "some", "stuff"]
        print get_index(lines, 'bread')
        self.assertTrue(8 == get_index(lines, 'bread'))

    def test_uuid_exists(self):
        """
        Verify UUID found correctly
        """

        lines = ["{ a4f6212c13491ff122d7a1b8c", "}"]
        self.assertEqual(True,
                         uuid_exists(lines, "a4f6212c13491ff122d7a1b8c",
                                            "{ a4f6212c13491ff122d7a1b8c"),
                         "UUID %s not found correctly" % "a4f6212c13491ff122d7a1b8c")

    def test_add_blacklist_exceptions(self):
        """
        Verify uuid inserted into blacklist exceptions
        """

        # uuid will be inserted into sample empty blacklist exceptions block
        uuid = "test_uuid"
        lines = ["adnkdna", "fajfna", "blacklist_exceptions", "{", "}", "aaa"]
        result = add_blacklist_exceptions(lines, uuid)
        full_uuid_string = "        wwid \"%s\"\n" % uuid.lower()
        self.assertEqual(result, ["adnkdna", "fajfna", "blacklist_exceptions",
                                   "{", full_uuid_string, "}", "aaa"])

    def test_add_blacklist_exceptions_previous_entries(self):
        """
        Verify new uuid last entry populated blacklist exceptions
        """

        # uuid will be inserted into sample populated blacklist exceptions block
        uuid = "test_uuid"
        lines = ["adnkdna", "fajfna", "blacklist_exceptions", "{", 
            '        wwid "3UUIDnumberOne"\n',
            '        wwid "3this_isAUUid"\n',
            "}", "aaa"]
        result = add_blacklist_exceptions(lines, uuid)
        full_uuid_string = "        wwid \"%s\"\n" % uuid
        self.assertTrue(result == ["adnkdna", "fajfna", "blacklist_exceptions",
                                   "{", '        wwid "3UUIDnumberOne"\n',
                                    '        wwid "3this_isAUUid"\n', 
                                    full_uuid_string, "}", "aaa"])

    def test_insert_multipath_block(self):
        """
        Verify the multipath block is inserted at the end of multipaths block
        """

        # create input block containing no entries
        uuid = "test_uuid"
        lines = ["multipaths {", "}"]
        for i in range(len(lines)):
            lines[i] = lines[i] + "\n"
        # create result block with new block added at end
        expected_result_lines = ["multipaths {", "        multipath {",
                 "                uid 0",
                 "                gid 0",
                 '                wwid "test_uuid"',
                 "                mode 0600", "        }", "}"]
        for i in range(len(expected_result_lines)):
            expected_result_lines[i] = expected_result_lines[i] + "\n"
        # verify result is as expected
        result = add_multipath(lines, uuid)

        self.assertEqual(result, expected_result_lines)

    def test_insert_multipath_block_extra_info(self):
        """
        Verify the multipath block is inserted at the end of multipaths block
        if extra data in file
        """

        # create input block containing entries
        uuid = "test_uuid"
        lines = ["multipaths {", "                multipath {",
                 "                uid 0" , "                gid 0",
                 '                wwid "3600601604f213400d8adc704b278e511"',
                 "                mode 0600", "        }",
                 "        multipath {", "                uid 0",
                 "                gid 0",
                 '                wwid "3600601604f21340090428e37b278e511"',
                 "                mode 0600", "        }", "}"]
        for i in range(len(lines)):
            lines[i] = lines[i] + "\n"
        # create result block containing entries with new block added at end
        expected_result_lines = ["multipaths {", "                multipath {",
                 "                uid 0" , "                gid 0",
                 '                wwid "3600601604f213400d8adc704b278e511"',
                 "                mode 0600", "        }",
                 "        multipath {", "                uid 0",
                 "                gid 0",
                 '                wwid "3600601604f21340090428e37b278e511"',
                 "                mode 0600", "        }",
                 "        multipath {", "                uid 0",
                 "                gid 0",
                 '                wwid "test_uuid"',
                 "                mode 0600", "        }", "}"]
        for i in range(len(expected_result_lines)):
            expected_result_lines[i] = expected_result_lines[i] + "\n"
        # verify result is as expected
        result = add_multipath(lines, uuid)

        self.assertEqual(result, expected_result_lines)

    def test_normalise_uuid(self):
        """
        Verify the UUID is modified to removed all colons, convert chars to
        lower case and prepend 3 to the return string.
        """

        # create example UUIDs
        test_UUID = "2:A:4:F:6:2:1:2:C:1:3:4:9:1:F:F:1:2:4:E:9:B:1:B:8:C:4:F:6:2:1:2"
        test_UUID2 = "2:A:4:F:6:2:1:2:C:1:3:4:9:1:F:F:1:2:4:E:1:C:1:B:8:C:4:F:6:2:1:2"
        test_UUID3 = "2:A:4:F:6:2:1:2:C:1:3:4:9:1:F:F:1:2:4:E:2:1:1:B:8:C:4:F:6:2:1:2"

        # verify the examples are modified as expected
        self.assertTrue("32a4f6212c13491ff124e9b1b8c4f6212" == normalise_uuid(test_UUID),
                        "Modified UUID result not correct")
        self.assertTrue("32a4f6212c13491ff124e1c1b8c4f6212" == normalise_uuid(test_UUID2),
                        "Modified UUID result not correct")
        self.assertTrue("32a4f6212c13491ff124e211b8c4f6212" == normalise_uuid(test_UUID3),
                        "Modified UUID result not correct")

    @patch("add_multipath.reload_mpath")
    @patch("add_multipath.read_mpath_file")
    @patch("add_multipath.write_mpath_file")
    def test_add_uuid_to_multipath(self, mock_write, mock_read,
                                   mock_mpath_reload):
        """
        Verify that the multipath.conf file will have the uuid added into
        both the blacklist exceptions and multipaths sections correctly.
        """

        # read data into in memory file
        TEST_DATA_LOCATION = os.path.join(os.path.dirname(__file__),
                                          'test_add_multipath.dat')
        file_in_memory = StringIO.StringIO()
        data_lines = open(TEST_DATA_LOCATION).readlines()
        print "data \n"
        print data_lines
        print "\n"
        for line_of_data in data_lines:
            file_in_memory.write(line_of_data)

        # return lines from data file
        lines_to_pass = file_in_memory.getvalue().splitlines(True)
        mock_read.return_value = lines_to_pass

        # call function with test uuid
        test_uuid =\
            "3:A:4:F:6:2:1:2:C:1:3:4:9:1:F:F:1:2:4:E:7:A:1:B:8:C:4:F:6:2:1:2"
        add_uuid_to_multipath(test_uuid)
        test_result = file_in_memory.readlines()

        # retrieve test result data
        TEST_RESULT_LOCATION = os.path.join(os.path.dirname(__file__),
                                            'test_add_multipath2.dat')
        data_lines = open(TEST_RESULT_LOCATION).readlines()

        # assert function ended with write called with modified input data
        # equal to expected data present in result data
        mock_write.assert_called_with(data_lines)
