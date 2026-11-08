import unittest

from mod_environment import ModError
from mod_rstb import encode, merge, parse


class ResourceTableMerge(unittest.TestCase):
    header = b"Yaz0" + bytes(12)

    def packed(self, hashes, names=None):
        return encode((hashes, names or {}), self.header)

    def test_preserves_changes_from_both_packs_in_either_order(self):
        stock = self.packed({1: 100, 2: 100, 3: 100}, {b"collision": 40})
        linkle = self.packed({1: 180, 2: 160}, {b"collision": 40})
        outfit = self.packed({1: 150, 2: 100, 3: 100, 4: 80}, {b"collision": 45})
        for packs in ([("Linkle", linkle), ("Outfit", outfit)], [("Outfit", outfit), ("Linkle", linkle)]):
            self.assertEqual(parse(merge(stock, packs)), ({1: 180, 2: 160, 4: 80}, {b"collision": 45}))

    def test_rejects_conflicting_removal_and_allocation(self):
        stock = self.packed({1: 100})
        with self.assertRaisesRegex(ModError, "disagree"):
            merge(stock, [("A", self.packed({})), ("B", self.packed({1: 180}))])

    def test_rejects_invalid_replacement_with_pack_name(self):
        with self.assertRaisesRegex(ModError, "Outfit has an invalid"):
            merge(self.packed({1: 100}), [("Outfit", b"invalid table")])


if __name__ == "__main__":
    unittest.main()
