# pyOCD debugger
# Copyright (c) 2017-2019 Arm Limited
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import print_function

import os
import sys
import traceback
import argparse
from collections import namedtuple
import logging

from pyocd.core.helpers import ConnectHelper
from pyocd.core.target import Target
from pyocd.flash.loader import FileProgrammer

from test_util import (
    Test,
    TestResult,
    get_session_options,
    )

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATE_NAMES = {
    Target.TARGET_RUNNING : "running",
    Target.TARGET_HALTED : "halted",
    Target.TARGET_RESET : "reset",
    Target.TARGET_SLEEPING : "sleeping",
    Target.TARGET_LOCKUP : "lockup",
    }

RUNNING = Target.TARGET_RUNNING
HALTED = Target.TARGET_HALTED

class ConnectTestCase(object):
    def __init__(self, prev_exit_state, connect_mode, expected_state, disconnect_resume, exit_state):
        self.prev_exit_state = prev_exit_state
        self.connect_mode = connect_mode
        self.expected_state = expected_state
        self.disconnect_resume = disconnect_resume
        self.exit_state = exit_state

class ConnectTestResult(TestResult):
    def __init__(self):
        super(ConnectTestResult, self).__init__(None, None, None)
        self.name = "connect"

class ConnectTest(Test):
    def __init__(self):
        super(ConnectTest, self).__init__("Connect Test", connect_test)

    def run(self, board):
        try:
            result = self.test_function(board)
        except Exception as e:
            print("Exception %s when testing board %s" % (e, board.unique_id))
            result = ConnectTestResult()
            result.passed = False
            traceback.print_exc(file=sys.stdout)
        result.board = board
        result.test = self
        return result


def connect_test(board):
    board_id = board.unique_id
    binary_file = os.path.join(parentdir, 'binaries', board.test_binary)
    print("binary file: %s" % binary_file)

    test_pass_count = 0
    test_count = 0
    result = ConnectTestResult()

    # Install binary.
    live_session = ConnectHelper.session_with_chosen_probe(unique_id=board_id, **get_session_options())
    live_session.open()
    live_board = live_session.board
    memory_map = board.target.get_memory_map()
    rom_region = memory_map.get_boot_memory()
    rom_start = rom_region.start

    def test_connect(connect_mode, expected_state, resume):
        print("Connecting with connect_mode=%s" % connect_mode)
        live_session = ConnectHelper.session_with_chosen_probe(
                        unique_id=board_id,
                        init_board=False,
                        connect_mode=connect_mode,
                        resume_on_disconnect=resume,
                        **get_session_options())
        live_session.open()
        live_board = live_session.board
        print("Verifying target is", STATE_NAMES.get(expected_state, "unknown"))
        actualState = live_board.target.get_state()
        # Accept sleeping for running, as a hack to work around nRF52840-DK test binary.
        # TODO remove sleeping hack.
        if (actualState == expected_state) \
                or (expected_state == RUNNING and actualState == Target.TARGET_SLEEPING):
            passed = 1
            print("TEST PASSED")
        else:
            passed = 0
            print("TEST FAILED (state={}, expected={})".format(
                STATE_NAMES.get(actualState, "unknown"),
                STATE_NAMES.get(expected_state, "unknown")))
        print("Disconnecting with resume=%s" % resume)
        live_session.close()
        live_session = None
        return passed

    # TEST CASE COMBINATIONS
    test_cases = [
    #                <prev_exit> <connect_mode>    <expected_state> <disconnect_resume> <exit_state>
    ConnectTestCase( RUNNING,    'attach',         RUNNING,         False,              RUNNING  ),
    ConnectTestCase( RUNNING,    'halt',           HALTED,          False,              HALTED   ),
    ConnectTestCase( HALTED,     'halt',           HALTED,          True,               RUNNING  ),
    ConnectTestCase( RUNNING,    'halt',           HALTED,          True,               RUNNING  ),
    ConnectTestCase( RUNNING,    'attach',         RUNNING,         True,               RUNNING  ),
    ConnectTestCase( RUNNING,    'halt',           HALTED,          False,              HALTED   ),
    ConnectTestCase( HALTED,     'attach',         HALTED,          False,              HALTED   ),
    ConnectTestCase( HALTED,     'halt',           HALTED,          False,              HALTED   ),
    ConnectTestCase( HALTED,     'attach',         HALTED,          True,               RUNNING  ),
    ConnectTestCase( RUNNING,    'attach',         RUNNING,         False,              RUNNING  ),
    ]

    print("\n\n----- TESTING CONNECT/DISCONNECT -----")
    print("Flashing new binary")
    FileProgrammer(live_session).program(binary_file, base_address=rom_start)
    live_board.target.reset()
    test_count += 1
    print("Verifying target is running")
    if live_board.target.is_running() or live_board.target.get_state() == Target.TARGET_SLEEPING:
        test_pass_count += 1
        print("TEST PASSED")
    else:
        print("TEST FAILED")
    print("Disconnecting with resume=True")
    live_session.options['resume_on_disconnect'] = True
    live_session.close()
    live_session = None
    # Leave running.

    # Run all the cases.
    for case in test_cases:
        test_count += 1
        did_pass = test_connect(
            connect_mode=case.connect_mode,
            expected_state=case.expected_state,
            resume=case.disconnect_resume
            )
        test_pass_count += did_pass
        case.passed=did_pass

    print("\n\nTest Summary:")
    print("\n{:<4}{:<12}{:<19}{:<12}{:<21}{:<11}{:<10}".format(
        "#", "Prev Exit", "Connect Mode", "Expected", "Disconnect Resume", "Exit", "Passed"))
    for i, case in enumerate(test_cases):
        print("{:<4}{:<12}{:<19}{:<12}{:<21}{:<11}{:<10}".format(
            i,
            STATE_NAMES[case.prev_exit_state],
            case.connect_mode,
            STATE_NAMES[case.expected_state],
            repr(case.disconnect_resume),
            STATE_NAMES[case.exit_state],
            "PASS" if case.passed else "FAIL"))
    print("\nPass count %i of %i tests" % (test_pass_count, test_count))
    if test_pass_count == test_count:
        print("CONNECT TEST SCRIPT PASSED")
    else:
        print("CONNECT TEST SCRIPT FAILED")

    result.passed = (test_count == test_pass_count)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='pyOCD connect test')
    parser.add_argument('-d', '--debug', action="store_true", help='Enable debug logging')
    args = parser.parse_args()
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=level)
    session = ConnectHelper.session_with_chosen_probe(**get_session_options())
    test = ConnectTest()
    result = [test.run(session.board)]
    test.print_perf_info(result)
