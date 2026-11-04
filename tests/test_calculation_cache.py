"""Exact persisted results, defensive reads and fail-safe resume behaviour."""

from dataclasses import dataclass
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
import warnings
from unittest.mock import patch

import numpy as np

from hthp.calculation_cache import CalculationCache
from hthp.thermo.state import ThermodynamicState


@dataclass
class Parameters:
    temperature: float = 45.0
    load: float = 170000.0
    subcooler: bool = True


class CalculationCacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "nested" / "cache.sqlite3"

    def cache(self, **kwargs):
        options = dict(signature="test-solver", dependency_versions={"numpy": "test"})
        options.update(kwargs)
        cache = CalculationCache(self.path, **options)
        self.addCleanup(cache.close)
        return cache

    def test_missing_read_does_not_create_database(self):
        cache = self.cache()
        sentinel = object()
        self.assertIs(cache.get("point", Parameters(), 45., sentinel), sentinel)
        self.assertFalse(self.path.parent.exists())
        self.assertEqual(cache.misses, 1)

    def test_restart_roundtrip_preserves_full_cycle_and_ph_states(self):
        state = ThermodynamicState(12e5, 42., 356.25, 1.3, None)
        cycle = dict(COP=np.float64(2.6), low={"component_states": {1: state, "3E": state}},
                     array=np.array([[1., 2.], [3., 4.]], dtype="<f8"),
                     indices=(np.int32(1), 2), missing=float("nan"), infinite=float("inf"))
        cache = self.cache()
        cache.set("optimum", Parameters(), None, (cycle, [cycle]))
        cache.close()
        resumed = self.cache()
        result, history = resumed.get("optimum", Parameters())
        self.assertIsInstance(result["low"]["component_states"][1], ThermodynamicState)
        self.assertEqual(result["low"]["component_states"][1], state)
        self.assertEqual(result["low"]["component_states"]["3E"].pressure_bar, 12.)
        self.assertIsInstance(result["COP"], np.float64)
        self.assertEqual(result["array"].dtype.str, "<f8")
        np.testing.assert_array_equal(result["array"], cycle["array"])
        self.assertIsInstance(result["indices"], tuple)
        self.assertIsInstance(result["indices"][0], np.int32)
        self.assertTrue(math.isnan(result["missing"]))
        self.assertEqual(result["infinite"], float("inf"))
        self.assertEqual(history[0]["COP"], result["COP"])
        self.assertEqual(resumed.disk_hits, 1)

    def test_key_requires_exact_parameters_coordinates_kind_signature_and_versions(self):
        cache = self.cache()
        cache.set("point", Parameters(), 45., {"COP": 2.6})
        self.assertIsNone(cache.get("point", Parameters(load=120000.), 45.))
        self.assertIsNone(cache.get("point", Parameters(subcooler=False), 45.))
        self.assertIsNone(cache.get("point", Parameters(), np.nextafter(45., 46.)))
        self.assertIsNone(cache.get("other", Parameters(), 45.))
        self.assertIsNone(self.cache(signature="other").get("point", Parameters(), 45.))
        self.assertIsNone(self.cache(dependency_versions={"numpy": "changed"}).get("point", Parameters(), 45.))
        self.assertEqual(cache.get("point", {"subcooler": True, "load": 170000., "temperature": 45.}, 45.),
                         {"COP": 2.6})

    def test_values_are_defensive_and_none_false_are_not_missing(self):
        cache = self.cache()
        cache.set("point", {}, 1., {"values": [1, 2]})
        cache.get("point", {}, 1.)["values"].append(3)
        self.assertEqual(cache.get("point", {}, 1.), {"values": [1, 2]})
        sentinel = object()
        for value in (None, False):
            cache.set("value", {}, None, value)
            self.assertIs(cache.get("value", {}, default=sentinel), value)

    def test_memory_bounded_and_evicted_points_still_on_disk(self):
        cache = self.cache(max_memory_entries=1)
        cache.set("point", {}, 1., {"COP": 1.})
        cache.set("point", {}, 2., {"COP": 2.})
        self.assertEqual(len(cache._memory), 1)
        self.assertEqual(cache.get("point", {}, 1.), {"COP": 1.})
        self.assertEqual(cache.disk_hits, 1)

    def test_disabled_does_not_read_or_write(self):
        cache = self.cache(enabled=False)
        cache.set("point", {}, None, 1.)
        self.assertIsNone(cache.get("point", {}))
        self.assertFalse(self.path.exists())

    def test_partial_run_keeps_completed_points_after_restart(self):
        cache = self.cache()
        for temperature in (30., 35.):
            cache.set("map", Parameters(), (temperature, 20.), {"COP": temperature / 10})
        cache.close()
        resumed = self.cache()
        self.assertEqual(resumed.get("map", Parameters(), (30., 20.))["COP"], 3.)
        self.assertEqual(resumed.get("map", Parameters(), (35., 20.))["COP"], 3.5)
        self.assertIsNone(resumed.get("map", Parameters(), (40., 20.)))

    def test_corrupt_payload_ignored_and_replaceable(self):
        cache = self.cache()
        cache.set("point", {}, None, {"COP": 2.6})
        cache.close()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE calculations SET payload='broken'")
            connection.commit()
        resumed = self.cache()
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            self.assertIsNone(resumed.get("point", {}))
            self.assertIsNone(resumed.get("point", {}))
        self.assertEqual(len(observed), 1)
        resumed.set("point", {}, None, {"COP": 2.7})
        self.assertEqual(resumed.get("point", {}), {"COP": 2.7})

    def test_unknown_saved_classes_never_imported_or_constructed(self):
        cache = self.cache()
        cache.set("point", {}, None, False)
        cache.close()
        malicious = json.dumps({"type": "arbitrary.class", "value": "ignored"})
        checksum = hashlib.sha256(malicious.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE calculations SET payload=?, checksum=?", (malicious, checksum))
            connection.commit()
        with self.assertWarns(RuntimeWarning):
            self.assertIsNone(self.cache().get("point", {}))

    def test_inaccessible_storage_keeps_memory_warns_once(self):
        cache = self.cache()
        with patch.object(Path, "mkdir", side_effect=PermissionError("read-only")):
            with warnings.catch_warnings(record=True) as observed:
                warnings.simplefilter("always")
                cache.set("point", {}, 1., {"COP": 2.6})
                cache.set("point", {}, 2., {"COP": 2.7})
        self.assertEqual(len(observed), 1)
        self.assertEqual(cache.get("point", {}, 1.), {"COP": 2.6})

    def test_bad_database_ignored_without_blocking(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"not a sqlite database")
        with self.assertWarns(RuntimeWarning):
            self.assertIsNone(self.cache().get("point", {}))

    def test_inaccessible_read_is_a_miss_not_a_solver_failure(self):
        cache = self.cache()
        with patch.object(Path, "exists", side_effect=PermissionError("read-only")):
            with self.assertWarns(RuntimeWarning):
                self.assertIsNone(cache.get("point", {}))

    def test_unsupported_objects_raise_instead_of_pickle(self):
        with self.assertRaises(TypeError):
            self.cache().set("point", {}, None, object())


if __name__ == "__main__":
    unittest.main()
