# -*- coding: utf-8 -*-
"""The sockets module contains various implementations of UDP socket servers
for transmission of data over the network. The different implementations aim to
be tailored to serve a specific purpose.

Presently the module contains only a date date socket server.

**Module variables:**

The modul contains a set of module variables used either as constants or as a
shared data storage between different instances of the socket servers. The
variables are the following:

.. autodata:: BAD_CHARS
.. autodata:: UNKNOWN_COMMAND
.. autodata:: OLD_DATA
.. autodata:: DATA

"""

import threading
import SocketServer
import time
import json
import logging


LOGGER = logging.getLogger(__name__)
# Make the logger follow the logging setup from the caller
LOGGER.addHandler(logging.NullHandler())
#: The list of characters that are not allowed in code names
BAD_CHARS = ['#', ',', ';', ':']
#: The string returned if an unknown command is sent to the socket
UNKNOWN_COMMAND = 'UNKNOWN_COMMMAND'
#: The string used to indicate old or obsoleted data
OLD_DATA = 'OLD_DATA'
#:The variable used to contain all the data.
#:
#:The format of the DATA variable is the following. The DATA variable is a
#:dict, where each key is an integer port number and the value is the data for
#:the socket server on that port. The data for each individual socket server is
#:always a dict, but the contained values will depend on which kind of socket
#:server it is.
#:
#:For a :class:`DateDataSocket` the dict will resemble this example:
#:
#: .. code-block:: python
#:
#:  {'type': 'date', 'codenames': ['ex1', 'ex2'],
#:   'timeouts': {'ex1': 3, 'ex2': 0.7},
#:   'data': {'ex1': [1234.5, 47.0], 'ex2':[1234.2, 42.0]}
#:  }
#:
DATA = {}


class DataUDPHandler(SocketServer.BaseRequestHandler):
    """Request handler for the :class:`.DateDataSocket` and
    :class:`.DateDataSocket` sockets
    """

    def handle(self):
        """Return data corresponding to the request
        
        The handler understands the following commands:

        :param raw: Returns all values on the form ``x1,y1;x2,y2`` in the
            order the codenames was given to the
            :meth:`.DateDataSocket.__init__` or :meth:`.DataSocket.__init__`
            method
        :param json: Return all values as a list of points (which in themselves
            are lists) e.g: ``[[x1, y1], [x2, y2]]``), contained in a
            :py:mod:`json` string. The order is the same as in ``raw``.
        :param raw_wn: (wn = with names) Same as raw but with names, e.g.
            ``codenam1:x1,y1;codename2:x2,y2``. The order is the same as in
            ``raw``.
        :param json_wn: (wn = with names) Return all data as a
            :py:class:`dict` contained in a :py:mod:`json` string. In the dict
            the keys are the codenames.
        :param codename#raw: Return the value for ``codename`` on the form
            ``x,y``
        :param codename#json: Return the value for ``codename`` as a list (e.g
            ``[x1, y1]``) contained in a :py:mod:`json` string
        :param codenames_raw: Return the list of codenames on the form
            ``name1,name2``
        :param codenames_json: Return a list of the codenames contained in a
            :py:mod:`json` string
        """
        command = self.request[0]
        self.port = self.server.server_address[1]
        socket = self.request[1]

        if command.count('#') == 1:
            data = self._single_value(command)
        else:
            data = self._all_values(command)

        socket.sendto(data, self.client_address)


    def _single_value(self, command):
        """Return a string for a single point"""
        name, command = command.split('#')
        if command == 'raw' and name in DATA[self.port]['data']:
            if self._old_data(name):
                out = OLD_DATA
            else:
                out = '{},{}'.format(*DATA[self.port]['data'][name])

        elif command == 'json' and name in DATA[self.port]['data']:
            if self._old_data(name):
                out = json.dumps(OLD_DATA)
            else:
                out = json.dumps(DATA[self.port]['data'][name])

        else:
            out = UNKNOWN_COMMAND

        return out

    def _all_values(self, command):
        """Return a string for all points or names"""
        # For a string of measurements in codenames order
        if command == 'raw':
            strings = []
            for codename in DATA[self.port]['codenames']:
                if self._old_data(codename):
                    string = OLD_DATA
                else:
                    string = '{},{}'.format(*DATA[self.port]['data'][codename])
                strings.append(string)
            out = ';'.join(strings)

        elif command == 'json':
            points = []
            for codename in DATA[self.port]['codenames']:                
                if self._old_data(codename):
                    data = OLD_DATA
                else:
                    data = DATA[self.port]['data'][codename]
                points.append(data)
            out = json.dumps(points)

        elif command == 'raw_wn':
            strings = []
            for codename in DATA[self.port]['codenames']:
                if self._old_data(codename):
                    string = '{}:{}'.format(codename, OLD_DATA)
                else:
                    string = '{}:{},{}'.format(
                        codename, *DATA[self.port]['data'][codename]
                        )
                strings.append(string)
            out = ';'.join(strings)

        elif command == 'json_wn':
            datacopy = dict(DATA[self.port]['data'])
            for codename in DATA[self.port]['codenames']:
                if self._old_data(codename):
                    datacopy[codename] = OLD_DATA
            out = json.dumps(datacopy)

        elif command == 'codenames_raw':
            out = ','.join(DATA[self.port]['codenames'])

        elif command == 'codenames_json':
            out = json.dumps(DATA[self.port]['codenames'])

        else:
            out = UNKNOWN_COMMAND

        return out

    def _old_data(self, code_name):
        """Check if the data for code_name has timed out"""
        now = time.time()
        if DATA[self.port]['type'] == 'date':
            timeout = DATA[self.port]['timeouts'].get(code_name)
            if timeout is not None:
                point_time = DATA[self.port]['data'][code_name][0]
                out = now - point_time > timeout
            else:
                out = False
        elif DATA[self.port]['type'] == 'data':
            out = False
        else:
            raise NotImplementedError

        return out


class DataSocket(threading.Thread):

    def __init__(self, codenames, port=9000, default_x=47, default_y=47):
        """Init data and UPD server

        :param codenames: List of codenames for the measurements. The names
            must be unique and cannot contain the characters: #,;: and SPACE
        :type codenames: list
        :param port: Network port to use for the socket (deafult 9000)
        :type port: int
        :param default_x: The x value the measurements are initiated with
        :type default_x: float
        :param default_y: The y value the measurements are initiated with
        :type default_y: float
        """
        LOGGER.debug('Initialize')
        # Init thread
        super(DataSocket, self).__init__()
        self.daemon = True
        # Init local data
        self.port = port
        # Check for existing servers on this port
        global DATA
        if port in DATA:
            message = 'A UDP server already exists on port: {}'.format(port)
            raise ValueError(message)
        # Prepare DATA
        DATA[port] = {'type': 'data', 'codenames': list(codenames),
                      'data': {}}
        for name in codenames:
            # Check for duplicates
            if codenames.count(name) > 1:
                message = 'Codenames must be unique; \'{}\' is present more '\
                    'than once'.format(name)
                raise ValueError(message)
            # Check for bad characters in the name
            for char in BAD_CHARS:
                if char in name:
                    message = 'The character \'{}\' is not allowed in the '\
                        'codenames'.format(char)
                    raise ValueError(message)
            # Init the point
            DATA[port]['data'][name] = (default_x, default_y)
        # Setup server
        self.server = SocketServer.UDPServer(('', port), DataUDPHandler)
        LOGGER.info('Initialized')

    def run(self):
        """Start the UPD socket server"""
        LOGGER.info('Start')
        self.server.serve_forever()
        LOGGER.info('Run ended')

    def stop(self):
        """Stop the UDP server"""
        LOGGER.debug('Stop requested')
        self.server.shutdown()
        # Wait 0.1 sec to prevent the interpreter to destroy the environment
        # before we are done
        time.sleep(0.1)
        # Delete the data, to allow forming another socket on this port
        del DATA[self.port]
        LOGGER.info('Stopped')

    def set_point(self, codename, point):
        """Set the current point for codename
        
        :param codename: Codename for the measurement whose 
        :type codename: str
        :param value: Current point as a tuple of 2 floats: (x, y)
        :type value: tuple
        """
        DATA[self.port]['data'][codename] = point
        LOGGER.debug('Point {} for \'{}\' set'.format(str(point), codename))


class DateDataSocket(threading.Thread):
    """This class implements a UDP socket for serving data as function of time.
    The UDP server uses the :class:`.DataUDPHandler` class to handle the UDP
    requests. The the commands that can be used with this socket is documented
    in that class.

    The main features of the data data logger is:

    * **Simple single method usage.** After the class is instantiated, a single
      call to :meth:`.DateDataSocket.set_point` or
      :meth:`.DateDataSocket.set_point_now` is all that is needed to make a
      point available via the socket.
    * **Timeout safety to prevent serving obsolete data.** The class can be
      instantiated with a timeout for each measurement type. If the available
      point is too old an error message will be served.
    """

    def __init__(self, codenames, port=9000, default_x=0, default_y=47,
                 timeouts=None):
        """Init data and UPD server

        :param codenames: List of codenames for the measurements. The names
            must be unique and cannot contain the characters: ``#,;:``
        :type codenames: list
        :param port: Network port to use for the socket (deafult 9000)
        :type port: int
        :param default_x: The x value the measurements are initiated with
        :type default_x: float
        :param default_y: The y value the measurements are initiated with
        :type default_y: float
        :param timeouts: The timeouts (in seconds as floats) the determines
            when the date data socket regards the data as being to old and
            reports that
        :type timeouts: Single float or list of floats, one for each codename
        """
        LOGGER.debug('Initialize')
        # Init thread
        super(DateDataSocket, self).__init__()
        self.daemon = True
        # Init local data
        self.port = port
        # Check for existing servers on this port
        global DATA
        if port in DATA:
            message = 'A UDP server already exists on port: {}'.format(port)
            raise ValueError(message)
        # Check and possibly convert timeout
        if hasattr(timeouts, '__len__'):
            if len(timeouts) != len(codenames):
                message = 'If a list of timeouts is supplied, it must have '\
                    'as many items as there are in codenames'
                raise ValueError(message)
            timeouts = list(timeouts)
        else:
            # If only a single value is given turn it into a list
            timeouts = [timeouts] * len(codenames)
        # Prepare DATA
        DATA[port] = {'type': 'date', 'codenames': list(codenames),
                      'data': {}, 'timeouts': {}}
        for name, timeout in zip(codenames, timeouts):
            # Check for duplicates
            if codenames.count(name) > 1:
                message = 'Codenames must be unique; \'{}\' is present more '\
                    'than once'.format(name)
                raise ValueError(message)
            # Check for bad characters in the name
            for char in BAD_CHARS:
                if char in name:
                    message = 'The character \'{}\' is not allowed in the '\
                        'codenames'.format(char)
                    raise ValueError(message)
            # Init the point
            DATA[port]['data'][name] = (default_x, default_y)
            DATA[port]['timeouts'][name] = timeout
        # Setup server
        self.server = SocketServer.UDPServer(('', port), DataUDPHandler)
        LOGGER.info('Initialized')

    def run(self):
        """Start the UPD socket server"""
        LOGGER.info('Start')
        self.server.serve_forever()
        LOGGER.info('Run ended')

    def stop(self):
        """Stop the UDP server

        .. note:: Closing the server **and** deleting the
            :class:`.DateDataSocket` socket instance is necessary to free up the
            port for other usage
        """
        LOGGER.debug('Stop requested')
        self.server.shutdown()
        # Wait 0.1 sec to prevent the interpreter to destroy the environment
        # before we are done
        time.sleep(0.1)
        # Delete the data, to allow forming another socket on this port
        del DATA[self.port]
        LOGGER.info('Stopped')

    def set_point_now(self, codename, value):
        """Set the current y-value for codename using the current time as x
        
        :param codename: Codename for the measurement whose 
        :type codename: str
        :param value: y-value
        :type value: float
        """
        self.set_point(codename, (time.time(), value))
        LOGGER.debug('Added time to value and called set_point')

    def set_point(self, codename, point):
        """Set the current point for codename
        
        :param codename: Codename for the measurement whose 
        :type codename: str
        :param value: Current point as a tuple of 2 floats: (x, y)
        :type value: tuple
        """
        DATA[self.port]['data'][codename] = point
        LOGGER.debug('Point {} for \'{}\' set'.format(str(point), codename))