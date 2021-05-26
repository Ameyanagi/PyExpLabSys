import datetime
import paramiko


class PowerWalkerEthernet(object):
    """
    This driver uses the fact that the PowerWalker allows ssh-access,
    and thus gives access the actual binary files that reads the internal
    values. SNMP could also be used, but apparently most values miss a
    digit compared to the internal tools.
    """
    def __init__(self, ip_address):
        self.latest_event = datetime.datetime.min
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(ip_address, username='root',
                         password='12345678', look_for_keys=False)

    def read_dynamic_data(self):
        command = '/var/www/html/web_pages_Galleon/cgi-bin/realInfo.cgi'
        stdin, stdout, stderr = self.ssh.exec_command(command)
        raw_lines = stdout.readlines()

        lines = []
        for line in raw_lines:
            if line.strip():
                lines.append(line.strip())

        values = {
            'ups_temperature': int(lines[2]) / 10.0,
            'battery_voltage': int(lines[8]) / 10.0,
            'battery_capacity': int(lines[9]),
            'remaining_battery': lines[10],  # minutes
            'input_frequency': int(lines[11]) / 10.0,
            'input_voltage': int(lines[12]) / 10.0,
            'output_frequency': int(lines[14]) / 10.0,
            'output_voltage': int(lines[15]) / 10.0,
            'load_level': int(lines[17]),
            'output_current': int(lines[35]) / 10.0,
        }
        # WARNING (appears in front-end)
        # FAULT (appears in front-end)
        print(values)

    def read_static_data(self):
        command = '/var/www/html/web_pages_Galleon/cgi-bin/baseInfo.cgi'
        stdin, stdout, stderr = self.ssh.exec_command(command)
        raw_lines = stdout.readlines()

        lines = []
        for line in raw_lines:
            if line.strip():
                lines.append(line.strip())

        nominal_input = int(lines[4][0:3])
        nominal_output = int(lines[4][4:])
        values = {
            'model': lines[2],
            'nominal_input_voltage': nominal_input,
            'nominal_output_voltage': nominal_output,
            'nominal_output_frequency': int(lines[10]) / 10.0,
            'rated_battery_voltage': int(lines[12]) / 10.0,
            'rated_va': int(lines[8]),
            'rated_output_current': int(lines[11])
        }
        print(values)

    def read_events(self, only_new=False):
        command = 'cd /var/log/eventlog; cat "$(ls -1rt | tail -n1)"'
        stdin, stdout, stderr = self.ssh.exec_command(command)
        raw_lines = stdout.readlines()

        if len(raw_lines) < 2:
            print('PowerWalker Ethernet: Too few lines in event file')
            return None

        events = []
        for line in raw_lines[1:]:
            split_line = line.strip().split(',')
            timestamp = datetime.datetime.strptime(split_line[0],
                                                   '%Y/%m/%d %H:%M:%S')
            if only_new and timestamp < self.latest_event:
                continue
            event = {
                'timestamp': timestamp,
                'event': split_line[1],
                'source': split_line[2]
            }
            events.append(event)
            self.latest_event = timestamp
        print(events)


if __name__ == '__main__':
    pw = PowerWalkerEthernet(ip_address='192.168.1.149')

    # pw.read_data()
    # pw.read_static_data()
    pw.read_events()
