"""The shared-memory descriptor (API and Contracts.md sections 44-46).

Large inputs and outputs travel as descriptors, not through the control channel. A descriptor is
validated before anyone touches the segment it names: the claimed shape must fit the claimed size.
That makes a descriptor self-consistent; it does not tie it to a real segment, so whoever attaches
a segment must check that its actual size covers `size_bytes` before reading.
"""

from dataclasses import dataclass
from math import prod
from typing import Any

from backend.ml.contracts.protocol import ContractError, MLErrorCode
from backend.ml.contracts.wire import (
    as_mapping,
    boolean,
    exact_keys,
    integer,
    sequence,
    string,
)

# dtype name -> bytes per element. The canonical image is uint8; embeddings are little-endian
# float32 (Persistence section 23); the rest are allowed for other arrays (float16 is not yet).
ITEM_SIZES = {"uint8": 1, "float32": 4, "float64": 8, "int32": 4, "int64": 8}
LAYOUTS = frozenset({"C"})  # contiguous, row-major


def _bad(message: str) -> ContractError:
    return ContractError(MLErrorCode.SHARED_MEMORY_INVALID, message)


@dataclass(frozen=True, slots=True)
class SharedMemoryDescriptor:
    name: str
    size_bytes: int
    dtype: str
    shape: tuple[int, ...]
    strides: tuple[int, ...]
    layout: str
    readonly: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise _bad("a segment needs a name")
        if self.dtype not in ITEM_SIZES:
            raise _bad(f"unsupported dtype {self.dtype!r}")
        if self.layout not in LAYOUTS:
            raise _bad(f"unsupported layout {self.layout!r}")
        if not self.shape:
            raise _bad("a segment holds an array with at least one dimension")
        if any(dim < 1 for dim in self.shape):
            raise _bad("every dimension must be at least 1")
        item = ITEM_SIZES[self.dtype]
        if self.strides != contiguous_strides(self.shape, item):
            raise _bad("strides must be those of contiguous row-major data")
        if prod(self.shape) * item > self.size_bytes:
            raise _bad("the shape does not fit in the segment")

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
            "dtype": self.dtype,
            "shape": list(self.shape),
            "strides": list(self.strides),
            "layout": self.layout,
            "readonly": self.readonly,
        }

    @classmethod
    def from_wire(cls, value: Any) -> "SharedMemoryDescriptor":
        try:
            data = as_mapping(value, "descriptor")
            exact_keys(
                data,
                "descriptor",
                {"name", "size_bytes", "dtype", "shape", "strides", "layout", "readonly"},
            )
            return cls(
                name=string(data["name"], "name"),
                size_bytes=integer(data["size_bytes"], "size_bytes", minimum=1),
                dtype=string(data["dtype"], "dtype"),
                shape=tuple(
                    integer(d, "shape", minimum=1) for d in sequence(data["shape"], "shape")
                ),
                strides=tuple(
                    integer(s, "strides", minimum=1) for s in sequence(data["strides"], "strides")
                ),
                layout=string(data["layout"], "layout"),
                readonly=boolean(data["readonly"], "readonly"),
            )
        except ContractError as error:  # a malformed descriptor is a shared-memory error
            raise _bad(error.message) from error


def contiguous_strides(shape: tuple[int, ...], item_size: int) -> tuple[int, ...]:
    strides: list[int] = []
    step = item_size
    for dim in reversed(shape):
        strides.append(step)
        step *= dim
    return tuple(reversed(strides))


def describe(
    name: str, dtype: str, shape: tuple[int, ...], *, readonly: bool, size_bytes: int | None = None
) -> SharedMemoryDescriptor:
    """A descriptor for a contiguous array in a segment of `size_bytes` (default: exactly its size;
    the operating system may round a real segment up, which is allowed)."""
    item = ITEM_SIZES.get(dtype)
    if item is None:
        raise _bad(f"unsupported dtype {dtype!r}")
    return SharedMemoryDescriptor(
        name=name,
        size_bytes=prod(shape) * item if size_bytes is None else size_bytes,
        dtype=dtype,
        shape=shape,
        strides=contiguous_strides(shape, item),
        layout="C",
        readonly=readonly,
    )
