"""Recorded reaction windows must return complete advice within the real budget."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

import advisor


class TimeoutReplayTests(unittest.TestCase):
    def test_pon_and_daiminkan_timeouts_return_all_offered_choices(self):
        path = Path(__file__).parent / 'fixtures/advisor_timeout_cases.json'
        for case in json.loads(path.read_text())['cases']:
            with self.subTest(case=case['id']):
                snapshot = deepcopy(case['state'])
                result = advisor.advise(snapshot, ranked_limit=2)
                self.assertEqual(result['status'], 'ready', result)
                choices, warnings = advisor._action_choices(snapshot)
                self.assertEqual(warnings, [])
                self.assertEqual({c['actionId'] for c in result['candidates']},
                                 {'pass', *(choice['actionId'] for choice in choices)})
                self.assertEqual(result['rankedCandidateCount'], 2)
                self.assertEqual(result['best'], result['candidates'][0])
                self.assertEqual(snapshot, case['state'])


if __name__ == '__main__':
    unittest.main()
