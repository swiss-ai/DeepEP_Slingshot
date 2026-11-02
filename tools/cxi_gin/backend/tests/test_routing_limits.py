import unittest

from routing import routes


class RoutingTests(unittest.TestCase):
    def test_ep8_two_destination_skew_limit(self):
        # A token may reach each rank once, so the maximum received-row skew
        # with two destinations is four, not eight.
        for skew in [1, 2, 4]:
            ids, matrix = routes(128, 8, 256, 6, skew, 1)
            self.assertEqual(ids.shape, (1024, 6))
            self.assertEqual(matrix.sum(), 2048)
            self.assertAlmostEqual(matrix.sum(axis=0).max() / 256, skew)
        with self.assertRaises(ValueError):
            routes(128, 8, 256, 6, 8, 1)

    def test_local_remote_domains(self):
        for locality in ['local', 'remote']:
            _, matrix = routes(128, 8, 256, 6, 1, 1, locality)
            for source in range(8):
                for destination in range(8):
                    forbidden = (source // 4 != destination // 4) if locality == 'local' else (source // 4 == destination // 4)
                    if forbidden:
                        self.assertEqual(matrix[source, destination], 0)


if __name__ == '__main__':
    unittest.main()
