import socket
import StringIO
import sys
import os
import signal
import errno

class WSGIServer(object):
    address_family = socket.AF_INET
    socket_type = socket.SOCK_STREAM
    request_queue_size = 1024

    def __init__(self, server_address):
        # Generate a socket to listen in for client requests.
        # Follow the procedure for generating a communication endpoint
        #   on server-side
        # 1. Ceeate the socket
        # 2. (Optional) configure the socket
        # 3. Bind the socket to the server's address
        # 4. Start listening for client connections 
        self.listen_socket = listen_socket = socket.socket(
            self.address_family, # Configure socket for IPv4 addresses)
            self.socket_type     # Configure socket for Stream listening.
        )
        listen_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )
        listen_socket.bind(server_address)
        listen_socket.listen(self.request_queue_size)

        # Get server endpoint information and save it.
        host, port = listen_socket.getsockname()[:2]
        self.server_name = socket.getfqdn(host)
        self.server_port = port

        # Store the headers of the HTTP response we will send
        #   to the client.
        self.headers_set = [] 

    def set_app(self, application):
        self.application = application

    def grim_reaper(self, signum, frame):
        while True:
            try:
                pid, status = os.waitpid(
                    -1, # Wait for any child processes.
                    os.WNOHANG
                )
            except OSError:
                return

            if pid == 0: # no more zombies
                return

    def serve_forever(self):
        # Server serving sequence.
        # 1. Accept a client connection
        # 2. Receive the request body.
        # 3. Parse the request line.
        # 4. Construct an environment for the app.
        # 5. Pass the environment and start_response into the app callable.
        # 6. The callable should set the status and headers, as well as
        #       return the response body.
        # 7. Now construct the HTTP response and send it to the client.
        listen_socket = self.listen_socket

        signal.signal(signal.SIGCHLD, self.grim_reaper)

        while True:
            try:
                self.client_connection, client_address = listen_socket.accept()
            except IOError as e:
                code, msg = e.args

                if code == errno.EINTR:
                    continue
                else:
                    raise

            pid = os.fork()
            if pid == 0:
                listen_socket.close() # Child process should not accept new requests.
                self.handle_one_request()
                self.client_connection.close() # Ensure that open file descriptors are closed.
                os._exit(0)
            else:
                # Close duplicate file-descriptor so that the file is not left open.
                self.client_connection.close()

            # The open file references must be reduced to 0, otherwise, a FIN
            #   packet is not sent, and the client is hanging on their curl.

    def handle_one_request(self):
        self.request_data = request_data = self.client_connection.recv(1024)
        print("".join(
            "< {line}\n".format(line=line)
            for line in request_data.splitlines()
        ))
        self.parse_response(request_data)
        env = self.get_environ()
        result = self.application(env, self.start_response)
        self.finish_response(result)

    def parse_response(self, data):
        request_line = data.splitlines()[0]
        request_line = request_line.rstrip('\r\n')
        (self.request_method,
         self.path,
         self.request_version
        ) = request_line.split()

    def get_environ(self):
        env = {}

        env['wsgi.version'] = (1,0)
        env['wsgi.url_scheme'] = 'http'
        env['wsgi.input'] = StringIO.StringIO(self.request_data)
        env['wsgi.errors'] = sys.stderr
        env['wsgi.multithread'] = False
        env['wsgi.multiprocess'] = False
        env['wsgi.run_once'] = False

        env['REQUEST_METHOD'] = self.request_method
        env['PATH_INFO'] = self.path
        env['SERVER_NAME'] = self.server_name
        env['SERVER_PORT'] = str(self.server_port)

        return env

    def start_response(self, status, response_headers, exc_info=None):
        server_response = [
            ("Date", "Sat 1st Sept 2018 05:59:48 GMT"),
            ("Server", "WSGIServer 0.2")
        ]
        self.headers_set = [status, response_headers + server_response]

    def finish_response(self, result):
        try:
            status, response_headers = self.headers_set
            response = "HTTP/1.1 {status}\r\n".format(status=status)
            for header in response_headers:
                response += "{0}: {1}\r\n".format(*header)
            response += "\r\n"
            for data in result:
                response += data
            print(''.join({
                "> {line}\n".format(line=line)
                for line in response.splitlines()
            }))
            self.client_connection.sendall(response)
        finally:
            self.client_connection.close()

SERVER_ADDRESS = (HOST, PORT) = "", 8888

def make_server(server_address, application):
    server = WSGIServer(server_address)
    server.set_app(application)
    return server

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("PLease input an application as an argument module:application")
    module, application = sys.argv[1].split(":")
    module = __import__(module)
    application = getattr(module, application)
    httpd = make_server(SERVER_ADDRESS, application)
    print("WSGIServer: Serving HTTP on port {port}...\n".format(port=PORT))
    httpd.serve_forever()