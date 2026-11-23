"""Armazenamento de cálculos em SQLite e JSON, com tipos e precisão preservados."""

from collections import OrderedDict
from dataclasses import asdict, fields, is_dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import sqlite3
import warnings

import numpy as np

from hthp.thermo.state import ThermodynamicState


SCHEMA_VERSION = 1


def _pack(value, *, canonical=False):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        return {"type": "float", "value": value.hex()}
    if isinstance(value, np.generic):
        return {"type": "numpy_scalar", "dtype": value.dtype.str,
                "value": _pack(value.item(), canonical=canonical)}
    if isinstance(value, complex):
        return {"type": "complex", "real": _pack(value.real), "imag": _pack(value.imag)}
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "biufcUS":
            raise TypeError(f"Unsupported cached array dtype: {value.dtype}")
        return {"type": "array", "dtype": value.dtype.str, "shape": list(value.shape),
                "value": [_pack(item, canonical=canonical) for item in value.flat]}
    if isinstance(value, ThermodynamicState):
        return {"type": "thermodynamic_state",
                "value": {field.name: _pack(getattr(value, field.name), canonical=canonical)
                          for field in fields(value)}}
    if isinstance(value, dict):
        pairs = [[_pack(key, canonical=canonical), _pack(item, canonical=canonical)]
                 for key, item in value.items()]
        if canonical:
            pairs.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True))
        return {"type": "dict", "value": pairs}
    if isinstance(value, (list, tuple)):
        return {"type": "tuple" if isinstance(value, tuple) else "list",
                "value": [_pack(item, canonical=canonical) for item in value]}
    raise TypeError(f"Unsupported cached value type: {type(value).__name__}")


def _unpack(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if not isinstance(value, dict) or "type" not in value:
        raise ValueError("Invalid calculation cache value")
    tag = value["type"]
    if tag == "float":
        return float.fromhex(value["value"])
    if tag == "complex":
        return complex(_unpack(value["real"]), _unpack(value["imag"]))
    if tag in ("numpy_scalar", "array"):
        dtype = np.dtype(value["dtype"])
        if dtype.kind not in "biufcUS":
            raise ValueError("Unsupported cached array dtype")
        if tag == "numpy_scalar":
            return np.asarray(_unpack(value["value"]), dtype=dtype)[()]
        data = [_unpack(item) for item in value["value"]]
        return np.asarray(data, dtype=dtype).reshape(value["shape"])
    if tag == "thermodynamic_state":
        data = value["value"]
        names = {field.name for field in fields(ThermodynamicState)}
        if set(data) != names:
            raise ValueError("Invalid cached thermodynamic state fields")
        return ThermodynamicState(**{key: _unpack(item) for key, item in data.items()})
    if tag == "dict":
        return {_unpack(key): _unpack(item) for key, item in value["value"]}
    if tag in ("list", "tuple"):
        items = [_unpack(item) for item in value["value"]]
        return tuple(items) if tag == "tuple" else items
    raise ValueError(f"Unknown calculation cache type: {tag}")


def _dumps(value, *, canonical=False):
    return json.dumps(_pack(value, canonical=canonical), ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _default_signature():
    from hthp.comparisons import solver_signature

    digest = hashlib.sha256(solver_signature().encode("ascii"))
    # As linhas salvas também dependem de record(), em analyses.py.
    digest.update(Path(__file__).with_name("analyses.py").read_bytes())
    return digest.hexdigest()


def _dependency_versions():
    result = {}
    for distribution in ("CoolProp", "scipy", "numpy"):
        try:
            result[distribution] = version(distribution)
        except PackageNotFoundError:
            result[distribution] = "not-installed"
    return result


class CalculationCache:
    """Guarda cada ponto sem arredondar. Se faltar ou estiver corrompido, retorna o valor padrão."""

    def __init__(self, path, signature=None, enabled=True, max_memory_entries=1024,
                 dependency_versions=None):
        if max_memory_entries < 0:
            raise ValueError("max_memory_entries must be non-negative")
        self.path = Path(path)
        self.enabled = enabled
        self.max_memory_entries = max_memory_entries
        self.signature = _default_signature() if signature is None else signature
        self.dependency_versions = (_dependency_versions() if dependency_versions is None
                                    else dict(dependency_versions))
        self._memory = OrderedDict()
        self._connection = None
        self._warned = False
        self.hits = self.misses = self.disk_hits = self.writes = 0

    def _key(self, kind, parameters, coordinates):
        if not isinstance(kind, str) or not kind:
            raise ValueError("Cache kind must be a non-empty string")
        if is_dataclass(parameters) and not isinstance(parameters, type):
            parameters = asdict(parameters)
        metadata = dict(schema=SCHEMA_VERSION, signature=self.signature,
                        dependencies=self.dependency_versions, kind=kind,
                        parameters=parameters, coordinates=coordinates)
        return hashlib.sha256(_dumps(metadata, canonical=True).encode("utf-8")).hexdigest()

    def _warn(self, error):
        if not self._warned:
            warnings.warn(f"Cache de cálculos indisponível ou inválido; os pontos necessários "
                          f"serão calculados normalmente ({error}).", RuntimeWarning,
                          stacklevel=3)
            self._warned = True

    def _connect(self, *, create):
        if self._connection is not None:
            return self._connection
        connection = None
        try:
            if not create and not self.path.exists():
                return None
            if create:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS calculations "
                    "(key TEXT PRIMARY KEY, payload TEXT NOT NULL, checksum TEXT NOT NULL)")
            self._connection = connection
            return connection
        except (OSError, sqlite3.Error) as error:
            if connection is not None:
                connection.close()
            self._warn(error)
            return None

    def _remember(self, key, payload):
        if not self.max_memory_entries:
            return
        self._memory[key] = payload
        self._memory.move_to_end(key)
        while len(self._memory) > self.max_memory_entries:
            self._memory.popitem(last=False)

    def get(self, kind, parameters, coordinates=None, default=None):
        if not self.enabled:
            self.misses += 1
            return default
        key = self._key(kind, parameters, coordinates)
        payload = self._memory.get(key)
        from_disk = False
        if payload is None:
            connection = self._connect(create=False)
            try:
                row = (connection.execute(
                    "SELECT payload, checksum FROM calculations WHERE key=?", (key,)).fetchone()
                       if connection is not None else None)
            except sqlite3.Error as error:
                self._warn(error)
                row = None
            if row is None:
                self.misses += 1
                return default
            payload, checksum = row
            if not isinstance(payload, str) or hashlib.sha256(payload.encode("utf-8")).hexdigest() != checksum:
                self._warn("checksum não confere")
                self.misses += 1
                return default
            from_disk = True
        try:
            result = _unpack(json.loads(payload))
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            self._warn(error)
            self._memory.pop(key, None)
            self.misses += 1
            return default
        self._remember(key, payload)
        self.hits += 1
        self.disk_hits += int(from_disk)
        return result

    def set(self, kind, parameters, coordinates, value):
        if not self.enabled:
            return
        key = self._key(kind, parameters, coordinates)
        payload = _dumps(value)
        self._remember(key, payload)
        connection = self._connect(create=True)
        if connection is not None:
            try:
                with connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO calculations (key, payload, checksum) VALUES (?, ?, ?)",
                        (key, payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()))
            except sqlite3.Error as error:
                self._warn(error)
        self.writes += 1

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
