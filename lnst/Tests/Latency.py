import os
import socket
import time
import logging
import signal


from lnst.Common.Parameters import IpParam, IntParam, ListParam
from .BaseTestModule import BaseTestModule


class LatencyClient(BaseTestModule):
    samples_count = IntParam(default=10)
    data_size = IntParam(default=64)
    host = IpParam()
    port = IntParam(default=19999)
    cpu_pin = ListParam(default=[])

    duration = IntParam(default=60)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._samples: list[tuple(float, float)] = []

        if self.params.cpu_pin != -1:
            logging.info(f"Setting CPU affinity of LatencyClient to {self.params.cpu_pin}")
            os.sched_setaffinity(0, self.params.cpu_pin)
        else:
            logging.warning("No CPU affinity set for LatencyClient. Is that intended?")

    def run(self):
        self._connection = socket.socket(self.params.host.family, socket.SOCK_STREAM)
        self._connection.connect((str(self.params.host), self.params.port))

        logging.debug("LatencyMeasurement: connection established")

        for i in range(
            self.params.samples_count - 1
        ):  # last sample is measured after the sleep
            sample = self._measure_latency(self._connection, i)
            logging.info(
                f"{i+1}/{self.params.samples_count} data transfer: {sample:.9f} s"
            )

        try:
            time.sleep(self.params.duration)
        except KeyboardInterrupt:
            pass

        sample = self._measure_latency(self._connection, self.params.samples_count)
        logging.info(f"Last data transfer: {sample:.9f} s")

        self._connection.close()

        self._res_data = self._samples

        return True

    def _measure_latency(self, client_socket, i):
        packet_id = f"{i+1:03}"
        message = packet_id.ljust(self.params.data_size, " ")

        start_time = time.perf_counter_ns()
        client_socket.sendall(message.encode())
        data = client_socket.recv(1024)
        end_time = time.perf_counter_ns()

        latency = end_time - start_time
        self._samples.append((latency, start_time))

        return latency

    def runtime_estimate(self):
        return self.params.duration + 5


class LatencyServer(BaseTestModule):
    host = IpParam()
    port = IntParam(default=19999)
    samples_count = IntParam(default=10)
    data_size = IntParam(default=64)
    cpu_pin = ListParam(default=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.params.cpu_pin != -1:
            logging.info(f"Setting CPU affinity of LatencyServer to {self.params.cpu_pin}")
            os.sched_setaffinity(0, self.params.cpu_pin)
        else:
            logging.warning("No CPU affinity set for LatencyServer. Is that intended?")

    def run(self):
        with socket.socket(
            self.params.host.family, socket.SOCK_STREAM
        ) as server_socket:
            server_socket.bind((str(self.params.host), self.params.port))
            server_socket.listen()
            logging.info(
                f"Latency server is listening on {self.params.host}:{self.params.port}"
            )

            i = 0
            try:
                conn, addr = server_socket.accept()
                with conn:
                    logging.debug(f"Connected by {addr}")

                    for i in range(self.params.samples_count):
                        data = conn.recv(self.params.data_size)
                        if not data:
                            break
                        conn.sendall(data)
                    logging.debug(f"Connection with {addr} closed")
            except KeyboardInterrupt:
                pass

            if i < (self.params.samples_count - 1):
                logging.error(
                    f"Server was interrupted before all samples were measured. {i} samples measured"
                )
                return False

        return True
