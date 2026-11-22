import base64
import struct
import unittest

from tools.guide_floors import floor_image, iv_floor_grid


class FieldFloorTests(unittest.TestCase):
    def test_enclosed_deck_door_does_not_turn_the_empty_margin_into_a_floor(self):
        block = bytearray(384)
        block[3] = 1
        struct.pack_into("<I", block, 196, 216)
        struct.pack_into("<I", block, 4, 224)
        struct.pack_into("<HH", block, 224, 4, 4)
        struct.pack_into("<I", block, 164, 256)
        for x in range(2, 7):
            for y in range(1, 7):
                if x in (2, 6) or y in (1, 6):
                    block[256 + y*8 + x] = 0x10
        block[256 + 3*8 + 2] = 0xa0
        landmarks = [{"x": 4, "z": 3}]
        open_room = iv_floor_grid(block, 0, landmarks)
        deck = iv_floor_grid(block, 0, landmarks, enclosed=True)
        self.assertEqual((1, 3, 1), (open_room[0][0], open_room[3][2], open_room[3][4]))
        self.assertEqual((0, 3, 1), (deck[0][0], deck[3][2], deck[3][4]))

    def test_cropping_preserves_original_coordinates(self):
        rows = [bytes(10) for _ in range(8)]
        rows[3] = bytes([0,0,0,0,0,1,2,3,0,0])
        result = floor_image(rows)
        self.assertEqual((result["left"],result["top"],result["width"],result["height"]), (4,2,5,3))
        self.assertTrue(base64.b64decode(result["url"].split(",")[1]).startswith(b"\x89PNG"))

    def test_floor_rejects_bad_offsets_dimensions_or_empty_data(self):
        for rows in ([], [bytes(8)], [b"\x01", b"\x00\x01"], [b"\xff"]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                floor_image(rows)
        for section in (0, 1, -1):
            block = bytearray(256)
            block[3] = 1
            struct.pack_into("<I",block,196,2**16)
            with self.assertRaises(ValueError):
                iv_floor_grid(block, section)
