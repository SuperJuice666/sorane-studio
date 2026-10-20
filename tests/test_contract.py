import unittest

from song_import.contract import check


class ContractTests(unittest.TestCase):
    def test_pinned_contract(self):
        self.assertEqual(check()["schemaVersion"], 1)
