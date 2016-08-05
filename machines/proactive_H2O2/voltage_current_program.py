"""My example stepped program"""

from __future__ import print_function, unicode_literals, division

# Import builtins
import sys
import socket
import json
from time import time, sleep
from threading import Thread
from functools import partial
from queue import Queue
import argparse
from pprint import pformat

# Import third party
from numpy import isclose
from PyQt4.QtGui import QApplication

# Import from PyExpLabSys
from PyExpLabSys.apps.stepped_program_runner.stepped_program_runner import SteppedProgramRunner
from PyExpLabSys.common.database_saver import DataSetSaver, CustomColumn
from PyExpLabSys.common.sockets import LiveSocket
from PyExpLabSys.common.utilities import get_logger
LOG = None

import credentials
from steps import parse_ramp


# Setup communication with the power supply server
HOST, PORT = "localhost", 8500
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
def _send_command(output, command, arg=None):
    """Send a command to the power supply server
    
    Args:
        output (str): The output number in a string; either 1 or 2
        command (str): The command/name of the method to call on the power
            supply object
        arg (object): The argument to the command/method
    """
    data_to_send = {'command': command, 'output': output}
    if arg is not None:
        data_to_send['arg'] = arg
    formatted_command = b'json_wn#' + json.dumps(data_to_send).encode('utf-8')

    sock.sendto(formatted_command, (HOST, PORT))
    received = sock.recv(1024).decode('utf-8')

    if received.startswith('ERROR:'):
        raise PowerSupplyComException(received)

    # The return values starts with RET#
    return json.loads(received[4:])


class PowerSupplyComException(Exception):
    pass


class MyProgram(Thread):
    """My fancy program"""

    def __init__(self, args):
        super(MyProgram, self).__init__()

        # Form channel_id e.g: A1
        self.channel_id = args.power_supply + args.output

        ### Required by the stepped program runner
        # Accepted capabilities are: can_edit_line, can_play,
        # can_stop, can_quit
        self.capabilities = ('can_stop', 'can_start')
        # Status fields (in order)
        self.status_fields = (
            # Status
            {'codename': 'status_field', 'title': 'Status'},
            # Voltage
            {'codename': self.channel_id + '_voltage',
            'title': 'Voltage', 'formatter': '{:.3f}', 'unit': 'V'},
            # Voltage setpoint
            {'codename': self.channel_id + '_voltage_setpoint',
             'title': 'Voltage Setpoint', 'formatter': '{:.3f}', 'unit': 'V'},
            # Current
            {'codename': self.channel_id + '_current',
             'title': 'Current', 'formatter': '{:.3f}', 'unit': 'A'},
            # Current limit
            {'codename': self.channel_id + '_current_limit',
             'title': 'Current limit', 'formatter': '{:.3f}', 'unit': 'A'},
            # Charge
            {'codename': self.channel_id + '_accum_charge',
             'title': 'Accumulated charge', 'formatter': '{:.3f}', 'unit': 'C'},
            # Time elapsed (step)
            {'codename': 'elapsed',
             'title': 'Time elapsed (step)', 'unit': 's'},
            # Time remaining (step)
            {'codename': 'remaining',
             'title': 'Time remaining (step)', 'formatter': '{:.2f}', 'unit': 's'},
            # Time elapsed (total)
            {'codename': 'elapsed_total',
             'title': 'Time elapsed (total)', 'unit': 's'},
            # Time remaining (total)
            {'codename': 'remaining_total',
             'title': 'Time remaining (total)', 'formatter': '{:.2f}', 'unit': 's'},
            # Iteration time
            {'codename': 'iteration_time',
             'title': 'Iteration time', 'formatter': '{:.2f}', 'unit': 's'},
        )
        # Queue for GUI updates
        self.message_queue = Queue()
        # The GUI also looks in self.config, see below

        ### Normal program
        # Setup my program
        with open(args.program_file) as file_:
            self.config, self.steps = parse_ramp(file_)
        # The GUI will look for keys: program_title in config
        self.say('Using power supply channel: ' + self.channel_id)
        self.say('Loaded with config:\n' + pformat(self.config))
        self.active_step = 0
        self.send_steps()

        # Base for the status
        self.status = {'status_field': 'Initialized'}

        # General variables
        self.stop = False
        self.ok_to_start = False

        # Setup power supply
        # Create a partial function with the output substitued in
        self.send_command = partial(_send_command, args.output)
        self.power_supply_on_off(True, self.config['maxcurrent_start'])
        # Power supply commands, must match order with self.codenames
        self.power_supply_commands = (
            'read_actual_current', 'read_actual_voltage', 'read_set_voltage',
            'read_current_limit'
        )

        # Setup dataset saver and live socket
        self.codenames = [self.channel_id + id_ for id_ in
                          ('_current', '_voltage', '_voltage_setpoint',
                           '_current_limit')]
        self.live_socket = LiveSocket(
            'H2O2_proactive_' + self.channel_id,
            self.codenames + [self.channel_id + '_accum_charge'],
            no_internal_data_pull_socket=True
        )
        self.live_socket.reset(self.codenames)
        self.live_socket.start()

        self.data_set_saver = DataSetSaver(
            credentials.measurements, credentials.xy_values,
            username=credentials.username, password=credentials.password
        )
        self.data_set_saver.start()

        # Done with init, send status
        self.send_status()

    def command(self, command, args_str):
        """Process commands from the GUI"""
        if command == 'stop':  # stop is sent on quit
            self.stop = True
        elif command == 'start':
            self.ok_to_start = True

    def send_status(self, update_dict=None):
        """Send the status to the GUI"""
        if update_dict:
            self.status.update(update_dict)
        self.message_queue.put(('status', self.status.copy()))

    def send_steps(self):
        """Send the steps list to the GUI"""
        steps = [(index == self.active_step, str(step))
                 for index, step in enumerate(self.steps)]
        self.message_queue.put(('steps', steps))

    def say(self, text):
        """Send a ordinary text message to the gui"""
        self.message_queue.put(('message', text))

    def run(self):
        """The MAIN run method"""
        # Wait for start
        while not self.ok_to_start:
            if self.stop:
                self.send_status({'status_field': 'Stopping'})
                self.power_supply_on_off(False)
                self.send_status({'status_field': 'Stopped'})
                return
            sleep(0.1)

        # Start
        self.send_status({'status_field': 'Starting'})
        self.setup_data_set_saver()

        # Run the MAIN measurement loop
        # (This is where most of the time is spent)
        self.main_measure()

        # Shutdown powersupply and livesocket
        self.send_status({'status_field': 'Stopping'})
        self.stop_everything()
        self.send_status({'status_field': 'Stopped'})

        sleep(0.1)
        self.say("I have stopped")

    def setup_data_set_saver(self):
        """Setup the data set saver"""
        sql_time = CustomColumn(time(), 'FROM_UNIXTIME(%s)')
        for codename in self.codenames:
            metadata = {
                'time': sql_time, 'comment': self.config['comment'],
                'label': codename[3:], 'type': 1,
                'power_supply_channel': self.channel_id,
            }
            self.data_set_saver.add_measurement(codename, metadata)

    def main_measure(self):
        """The main measurement loop"""
        self.send_status({'status_field': 'Running'})
        # Initial setup
        program_start = time()
        last_set_voltage = None
        last_set_max_current = None
        last_time = time()
        iteration_time = 'N/A'
        self.status['elapsed'] = 0.0
        accum_charge_codename = self.channel_id + '_accum_charge'
        self.status[accum_charge_codename] = 0.0
        current_id = self.channel_id + '_current'
        last_measured_current = 0.0

        self.say('I started on step 0')
        for self.active_step, current_step in enumerate(self.steps):
            self.send_status({'status_field': 'Running step {}'.format(self.active_step)})
            # Also give the step an instance name (for steps list)
            if self.active_step > 0:
                self.say('Switched to step: {}'.format(self.active_step))
            self.send_steps()
            current_step.start()

            # While the step hasn't completed yet
            while current_step.elapsed() < current_step.duration:
                # Check if we should stop
                if self.stop:
                    self.say('I have been asked to stop')
                    return

                iteration_start = now = time()
                # Calculate the time for one iteration and update times in status
                iteration_time = now - last_time
                
                last_time = now
                self.status.update({
                    'elapsed': current_step.elapsed(),
                    'remaining': current_step.remaining(),
                    'iteration_time': iteration_time,
                    'elapsed_total': sum(step.elapsed() for step in self.steps),
                    'remaining_total': sum(step.remaining() for step in self.steps),
                })
    
                # Ask the power supply to set a new voltage if needed
                required_voltage, required_max_current = current_step.values()
                if required_max_current != last_set_max_current:
                    self.send_command('set_current_limit', required_max_current)
                    last_set_max_current = required_max_current
                if required_voltage != last_set_voltage:
                    self.send_command('set_voltage', required_voltage)
                    last_set_voltage = required_voltage
    
                # Read value from the power supply
                self._read_values_from_power_supply(program_start)

                # Calculate, set and send accumulated charge
                charge_addition = \
                    (last_measured_current + self.status[current_id])\
                    / 2 * iteration_time
                last_measured_current = self.status[current_id]
                self.status[accum_charge_codename] += charge_addition
                point = (self.status['elapsed_total'], self.status[accum_charge_codename])
                self.live_socket.set_point(accum_charge_codename, point)

                # Send the new status
                self.send_status()
    
                # Calculate time to sleep to use the proper probe interval
                time_to_sleep = current_step.probe_interval - (time() - iteration_start)
                if time_to_sleep > 0:
                    sleep(time_to_sleep)

            # Stop the step(s own time keeping)
            current_step.stop()

        # For loop over steps ended
        self.send_status({'status_field': 'Program Complete'})
        self.say('Stepped program completed')


    def _read_values_from_power_supply(self, program_start):
        """Read all required values from the power supply (used only from run)"""
        for command, codename in zip(self.power_supply_commands, self.codenames):
            # Get a value for the current command
            value = self.send_command(command)
            if command == 'read_set_voltage':
                value = float(value.strip().split(' ')[1])
            if command == 'read_current_limit':
                value = float(value.strip().split(' ')[1])

            # Set/save it on the live_socket, database and in the GUI
            point = (self.status['elapsed_total'], value)
            self.live_socket.set_point(codename, point)
            self.data_set_saver.save_point(codename, point)
            self.status[codename] = value

    def stop_everything(self):
        """Stop power supply and live socket"""
        self.power_supply_on_off(False) 
        self.live_socket.stop()
        self.data_set_saver.stop()

    def power_supply_on_off(self, state, current_limit=0.0):
        """Set power supply on off"""
        # Set voltage to 0
        LOG.debug('Stopping everything. Set voltage to 0.0')
        self.send_command('set_voltage', 0.0)
        start = time()
        while self.send_command('read_actual_voltage') > 1E-2:
            if time() - start > 60:
                LOG.error('Unable to set voltage to 0')
                if state:
                    raise RuntimeError('Unable to set voltage to 0')
                else:
                    self.say('Unable to set voltage to 0')
                    break
            sleep(1)

        # Set current limit
        self.send_command('set_current_limit', current_limit)
        read_current_limit = float(
            self.send_command('read_current_limit').strip().split(' ')[1]
        )
        if not isclose(read_current_limit, current_limit):
            raise RuntimeError('Unable to set current limit')

        # Set state
        self.send_command('output_status', state)
        read_state = self.send_command('read_output_status').strip() == '1'
        if not read_state is state:
            raise RuntimeError('Could not set output state')



def main():
    """Main function"""
    # Parse arguments
    parser = argparse.ArgumentParser(description=('Runs a stepped power supply program on '
                                                  'a specified power supply and channel'))
    parser.add_argument('power_supply', choices=('A'),
                        help='The capital lette of a power supply e.g. A')
    parser.add_argument('output', choices=('1', '2'),
                        help='The output number on that power supply. Must be 1 or 2')
    parser.add_argument('program_file', help="The file that contains the ramp")
    args = parser.parse_args()
    
    global LOG
    LOG = get_logger(
        'STACK TESTER ' + args.power_supply + args.output,
        level='debug', file_log=True,  terminal_log=False,
        file_name='stack_tester_' + args.power_supply + args.output + '.log'
    )

    # Init program
    my_program = MyProgram(args)
    my_program.start()

    # Appearently, it is better to defined app at the module level for
    # clean up: http://stackoverflow.com/questions/27131294/
    # error-qobjectstarttimer-qtimer-can-only-be-used-with-threads-started-with-qt
    global app
    app = QApplication(sys.argv)
    SteppedProgramRunner(my_program)
    sys.exit(app.exec_())

try:
    main()
except Exception as exc:
    LOG.exception("Catched exception at the outer layer")
    if isinstance(exc, ConnectionResetError):
        LOG.info('Unable to connect to the power supply server. '
                 'Did you rememver to start it?')
    raise