import socket
import unittest
from unittest import mock

from hermes import net


class PreferIPv4Tests(unittest.TestCase):
    def test_ipv4_goes_first_and_ipv6_stays_as_fallback(self):
        v6a = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
        v6b = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::2", 443, 0, 0))
        v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
        with mock.patch.object(net, "_original", return_value=[v6a, v4, v6b]):
            self.assertEqual(net._ipv4_first("example.org", 443), [v4, v6a, v6b])

    def test_ipv6_only_hosts_still_resolve(self):
        v6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
        with mock.patch.object(net, "_original", return_value=[v6]):
            self.assertEqual(net._ipv4_first("example.org", 443), [v6])


if __name__ == "__main__":
    unittest.main()
