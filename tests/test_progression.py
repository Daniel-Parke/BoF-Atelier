import itertools
from pathlib import Path
import tempfile
import unittest

from tools.import_games import import_game
from tools.progression import WorkshopError, dragon_records, fnv32a, game_tables, gene_selection, master_comparison, original_growth, recipe_preview
try:
    from .test_import_games import CUE, synthetic_bin
except ImportError:
    from test_import_games import CUE, synthetic_bin


class OriginalRuleCases(unittest.TestCase):
    def setUp(self):
        recipes = bytearray([17, 16, 15] * 11)
        recipes[:3] = bytes([1, 2, 255])
        self.iii = dict(game='bof3', costs=bytes(range(18)), recipes=bytes(recipes), groups=bytes(range(11)))
        growth = bytearray(5600)
        start = (6 * 100 + 99) * 8
        growth[start + 2:start + 4] = bytes([43, 0xD4])
        masters = bytearray(78)
        masters[12:18] = bytes([1, 255, 2, 254, 3, 253])
        self.iv = dict(game='bof4', masters=bytes(masters), growth=bytes(growth), skills=bytes(3072))

    def test_gene_permutations_cost_affordability_and_recipe_priority(self):
        for genes in itertools.permutations([1, 2, 3]):
            result = gene_selection(self.iii, genes, available_ap=6)
            self.assertEqual((result['initial_ap'], result['special_recipe'], result['group_id']), (6, 0, 0))
            self.assertTrue(result['affordable'])
        self.assertFalse(gene_selection(self.iii, [2, 1], available_ap=2)['affordable'])

    def test_fusion_conditional_and_unmatched_are_explicit(self):
        self.assertIn('Fusion', gene_selection(self.iii, [16])['interpretation'])
        self.assertIn('General', gene_selection(self.iii, [16], party_size=2)['interpretation'])
        self.assertIsNone(gene_selection(self.iii, [3])['special_recipe'])
        self.assertEqual(gene_selection(self.iii, [1, 2, 16])['special_recipe'], 0)

    def test_mix_and_fusion_preview_use_rules_and_party(self):
        mix = bytearray(18*14)
        mix[0] = mix[10] = mix[14+10] = 1
        mix[5*14+11] = 1
        tables = self.iii | {"mix_rows": mix}
        self.assertEqual("Whelp", recipe_preview(tables, [0])["form"])
        self.assertEqual("Dragon", recipe_preview(tables, [1,0])["form"])
        self.assertEqual("Warrior", recipe_preview(tables, [5])["form"])
        self.assertEqual("Fusion", recipe_preview(tables, [16])["form"])
        self.assertEqual("Hybrid", recipe_preview(tables, [16], ["Peco", "Rei"])["form"])
        self.assertIn("Shadow Onion", recipe_preview(tables, [3,16], ["Rei", "Peco"])["detail"])
        self.assertEqual("Whelp", recipe_preview(tables, [16], ["Garr", "Momo"])["form"])
        self.assertEqual("Whelp", recipe_preview(tables, [16], ["Rei"])["form"])
        self.assertEqual("random", recipe_preview(tables, [12])["kind"])
        with self.assertRaises(ValueError):
            recipe_preview(tables, [16], ["Rei","Rei"])

    def test_invalid_and_cross_game_selections_are_rejected(self):
        for values in [[], [1, 1], [18], [-1], [0, 1, 2, 3], [False]]:
            with self.assertRaises(WorkshopError):
                gene_selection(self.iii, values)
        for func, args in [(gene_selection, (self.iv, [1])), (gene_selection, (self.iii, [1])),
                           (master_comparison, (self.iii, 1, 2)), (master_comparison, (self.iv, 0, 13)),
                           (original_growth, (self.iv, 7, 3)), (original_growth, (self.iv, 0,-1)),
                           (dragon_records, (self.iii,))]:
            with self.assertRaises(WorkshopError):
                func(*args, **({'party_size': 4} if func is gene_selection else {}))

    def test_iv_signed_growth_and_anonymous_forms(self):
        row = master_comparison(self.iv, 0, 2)
        self.assertEqual(list(row['second_minus_first'].values()), [1,-1,2,-2,3,-3])
        self.assertEqual(list(master_comparison(self.iv, 2, 0)['second_minus_first'].values()), [-1,1,-2,2,-3,3])
        growth = original_growth(self.iv, 6, 99)
        self.assertEqual((growth['hp_entry'], growth['ap_entry']), (43, 13))
        forms = dragon_records(self.iv)
        self.assertEqual([item['skill_id'] for item in forms], list(range(211, 225)))
        self.assertFalse(any('name' in item for item in forms))
        self.assertEqual(dragon_records(self.iv, reveal_names=True)[0]['name'], 'Aura')
        self.assertEqual(fnv32a(b'hello'), 0x4f9f2cab)

    def test_unqualified_realistic_disc_is_not_interpreted_at_fixed_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cue = base / 'game.cue'
            cue.write_bytes(CUE)
            (base / 'game.bin').write_bytes(synthetic_bin())
            receipt = import_game(cue, base / 'games')
            with self.assertRaisesRegex(WorkshopError, 'no qualified'):
                game_tables(base / 'games' / receipt['library_id'])


if __name__ == '__main__':
    unittest.main()
