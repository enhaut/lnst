from lnst.Devices.Device import Device


class MockedDevice(Device):
    def __init__(self, hwaddr, ips, name):
        self._hwaddr = hwaddr
        self._ips = ips
        self._name = name

    @property
    def hwaddr(self):
        return self._hwaddr

    @property
    def ips(self):
        return self._ips
    
    @property
    def name(self):
        return self._name


