import sys
import json
import requests


class TeltonikaRut(object):
    def __init__(self, passwd, ip_address='192.168.1.1'):
        self.ip = ip_address
        self.passwd = passwd
        self.session = '00000000000000000000000000000000'
        self.session = self.init_session()

    def _comm(self, params):
        payload = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'call'
        }
        payload.update(
            {'params': [self.session] + params}
        )

        url = 'http://{}/ubus'.format(self.ip)
        r = requests.post(url, data=json.dumps(payload))
        reply = r.json()
        result = reply['result']
        return result

    def init_session(self):
        params = ['session', 'login', {'username': 'root', 'password': self.passwd}]
        reply = self._comm(params)
        session_key = reply[1]['ubus_rpc_session']
        return session_key

    def rssi(self):
        """
        Obtain signal strength
        """
        params = [
            'file', 'exec', {'command': 'gsmctl', 'params': ["-q"]}
        ]
        reply = self._comm(params)
        rssi = int(reply[1]['stdout'])
        return rssi

    def cell_information(self):
        params = [
            'file', 'exec', {'command': 'gsmctl', 'params': ["--serving"]}
        ]
        reply = self._comm(params)
        info = reply[1]['stdout']

        if info.find('GSM') > 0:
            pos = info.find('GSM') + 5
            data = info[pos:].split(',')
            cell_info = {
                'mcc': data[0],
                'mnc': data[1],
                'lac': int(data[2], 16),
                'cell_id': int(data[3], 16)
            }
        # print('Lac: {}, Lac dec: {}'.format(lac, int(lac, 16)))
        return cell_info


if __name__ == '__main__':
    ip = sys.argv[1]
    pw = sys.argv[2]

    tr = TeltonikaRut(ip_address=ip, passwd=pw)
    tr.init_session()

    print(tr.rssi())
    print()
    print(tr.cell_information())
