"""Check executed magnitudes and retained decisions, including stay and undo."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import probe


class VariableActions(unittest.TestCase):
    def fake_api(self, outputs):
        outputs = iter(outputs)
        def api(base, path, body, **kwargs):
            if path == '/tokenize':
                return {'tokens': [1]}
            return {'content': next(outputs), 'stop_type': 'eos',
                    'tokens_predicted': 8, 'timings': {'cache_n': 0, 'prompt_n': 1}}
        return api

    def test_move_stay_undo_preserve_actual_displacements(self):
        args = argparse.Namespace(dims=2, k=1, step=.2, rounds=3, warmup=4,
            seed=39, execution_mode='vector', mode='mountain', landscape='parabola',
            regret=True, model_url='unused', prompt_layout='suffix', thinking=False,
            action_space='variable', max_step=2)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(probe, 'ROOT', Path(folder)), patch.object(
                    probe, 'api', self.fake_api(['[0.125,-0.75]', '[0,0]', '"undo"'])), \
                    contextlib.redirect_stdout(io.StringIO()):
                probe.run(args)
            doc = json.loads((Path(folder)/'runs/latest.json').read_text(encoding='utf-8'))
        initial = doc['warmup'][-1]['x']
        move, stay, undo = doc['steps']
        self.assertEqual(move['x'], [initial[0]+.125, initial[1]-.75])
        self.assertEqual(stay['x'], move['x'])
        self.assertEqual(stay['decision'], 'stay')
        self.assertEqual(stay['undo_depth'], 1)
        self.assertEqual(undo['x'], initial)
        history = json.JSONDecoder().raw_decode(stay['audit']['prompt'].split('Raw history:\n')[1])[0]
        self.assertEqual(history[-1]['decision']['displacement'], [.125, -.75])

    def test_invalid_vectors_are_rejected_instead_of_clipped(self):
        for output in ('[2.001,0]', '[0.0001,0]', '[NaN,0]', '[true,0]', '[1]'):
            with self.subTest(output=output), patch.object(probe, 'api', self.fake_api([output])):
                with self.assertRaises(RuntimeError):
                    probe.choose_vector('unused', [], 2, 1, .2, action_space='variable')

    def test_fixed_route_still_requires_fixed_step_and_k(self):
        with patch.object(probe, 'api', self.fake_api(['[0.125,-0.75]'])):
            with self.assertRaises(RuntimeError):
                probe.choose_vector('unused', [], 2, 1, .2, action_space='fixed')


if __name__ == '__main__':
    unittest.main()
