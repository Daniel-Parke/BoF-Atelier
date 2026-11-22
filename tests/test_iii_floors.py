import struct
import unittest

from tools.iii_floors import FLOOR_ADDRESS, floor_grid


def fixture():
    data = bytearray(2048 + 128)
    struct.pack_into("<II8s", data, 0, 1, 1, b"MATH_TBL")
    struct.pack_into("<IIIH", data, 16, 128, FLOOR_ADDRESS, 0, 0)
    data[2048:2050] = bytes((4, 2))
    struct.pack_into("<H", data, 2048 + 20, 19)
    data[2048+76:2048+84] = bytes((0, 0x11, 0x20, 0xc0, 0x30, 0x41, 0xbe, 0x90))
    return data


class Image:
    def __init__(self, data):
        self.data = data

    def read_logical(self, lba, size):
        return self.data[lba*2048:lba*2048+size]


class FieldPlaneTests(unittest.TestCase):
    def test_static_grid_and_solid_high_nibbles(self):
        raw = fixture()
        self.assertEqual(floor_grid(Image(raw), {"bytes":len(raw),"lba":0}, 0),
                         [bytes((1,0,0,1)), bytes((0,0,0,1))])

    def test_refuses_invalid_sections_and_extents(self):
        raw = fixture()
        for field, value in [(20, FLOOR_ADDRESS + 8), (16, 3000)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                changed = raw.copy()
                struct.pack_into("<I", changed, field, value)
                floor_grid(Image(changed), {"bytes":len(raw),"lba":0}, 0)
        for section in (1, -1, False):
            with self.subTest(section=section), self.assertRaises(ValueError):
                floor_grid(Image(raw), {"bytes":len(raw),"lba":0}, section)
        struct.pack_into("<H", raw, 2048+20, 800)
        with self.assertRaises(ValueError):
            floor_grid(Image(raw), {"bytes":len(raw),"lba":0}, 0)
