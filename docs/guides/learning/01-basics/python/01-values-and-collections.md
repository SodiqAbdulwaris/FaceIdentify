# Python 01 Values, operators, strings and collections

## 1. What this is and why it exists

A program is a list of instructions a computer follows from top to bottom. Python reads a file
(`something.py`), turns it into instructions and runs them. Everything in Python is a **value** with a
**type**. This lesson covers the building blocks you will see on every page of the code: numbers, text,
yes/no, "nothing", and the four ways to hold many values (list, tuple, dict, set).

## 2. Where it lives

You meet these in every file. Two concrete places to look at once you finish the lesson:

- `evaluation/measure_operating_point.py` line 66: `TAIL_FLOOR = (0.326)`, a constant, and line 266,
  where scores are rounded: `round(max(owner_floor, float(np.percentile(scores, 99.9)) ...), 4)`.
- `backend/app/recognition/reasoner.py`: the policy numbers (`match_threshold`, `margin`, ...) are floats.

## 3. How it works

### Types

| Type | Example | What it is |
|---|---|---|
| `int` | `42`, `-7` | whole number, any size |
| `float` | `0.5`, `1e-6` | number with a fraction (approximate) |
| `bool` | `True`, `False` | yes/no |
| `str` | `"abc"`, `'abc'` | text |
| `bytes` | `b"\x00\xff"` | raw bytes (files, hashes, images in memory) |
| `None` | `None` | "no value" |
| `list` | `[1, 2, 3]` | ordered, changeable collection |
| `tuple` | `(1, 2, 3)` | ordered, **unchangeable** collection |
| `dict` | `{"a": 1}` | key-to-value map |
| `set` | `{1, 2, 3}` | unordered, no duplicates |

`type(x)` tells you the type of `x`.

### Floats are approximate

`0.1 + 0.2` is `0.30000000000000004` because computers store fractions in binary. So never test two
floats for exact equality; compare with a margin (`abs(a - b) < 1e-9`). That is one reason this project
rounds similarity scores to four places before comparing them to a threshold.

### Variables and names

A variable is a name attached to a value. `=` *attaches*; it does not mean "equals" as in mathematics.

```python
threshold = 0.3544        # attach the name `threshold` to a float
threshold = 0.5           # now the name points at a different value
name, age = "Ada", 36     # two names at once (tuple unpacking)
```

Names are `lower_snake_case` for variables and functions, `CapitalizedWords` for classes and `UPPER_CASE` for
constants (values never meant to change). Python does not stop you changing a constant; it is a
convention, and the type checker can enforce it with `Final`.

### Operators

```python
7 + 2       # 9      7 - 2   # 5      7 * 2   # 14
7 / 2       # 3.5    true division, always a float
7 // 2      # 3      floor division      7 % 2   # 1   remainder
2 ** 10     # 1024   power
"ab" + "c"  # "abc"  strings join with +  "ab" * 3  # "ababab"
a == b      # equal?   a != b   # different?   a < b  # also <=, >, >=
a and b     # both true    a or b   # either    not a   # opposite
x is None   # identity: the very same object (use `is` only for None, True, False)
x in items  # membership: is x one of the items?
```

`and`/`or` *short-circuit*: `a or b` does not look at `b` if `a` is already true. The idiom
`value or default` yields the default when `value` is empty, zero or `None`.

### Strings

```python
name = "Ada"
f"Hello {name}, you are {2 + 2} years old"   # an f-string: values inside text
name.upper(); name.strip()                    # methods return NEW strings; strings never change
"a,b,c".split(",")                            # ['a', 'b', 'c']
"-".join(["a", "b"])                          # 'a-b'
name[0]; name[-1]; name[0:2]                  # 'A', 'a', 'Ad' (first index is 0; slices stop before the end)
```

An **f-string** appears in error messages across the code: `f"{package_key} is not installed"`.

### Collections

```python
faces = ["a", "b"]; faces.append("c")          # list: ordered, changeable
point = (3, 4)                                  # tuple: ordered, fixed (safe to share)
policy = {"match_threshold": 0.35, "margin": 0.02}
policy["margin"]; policy.get("ceiling"); policy.get("ceiling", -1.0)   # 0.02, None, -1.0
seen = {1, 2, 2, 3}                             # set: {1, 2, 3}; `2 in seen` is True and fast
```

A function that returns two things returns a **tuple**: `return accepted, correct`.

**JSON**, which the API and several database columns use, is just nested dicts, lists, strings,
numbers, booleans and null (`None` in Python). `json.dumps(obj)` makes text; `json.loads(text)` reads it.

## 4. Try it

**Works with no models. Verified 2026-10-12.** In `uv run python`:

1. Types and the float trap:

   ```python
   >>> type(0.5), type(b"a"), type(None)
   (<class 'float'>, <class 'bytes'>, <class 'NoneType'>)
   >>> 0.1 + 0.2
   0.30000000000000004
   >>> 0.1 + 0.2 == 0.3
   False
   >>> abs((0.1 + 0.2) - 0.3) < 1e-9
   True
   ```

2. Operators and strings: `7 / 2` is `3.5`, `7 // 2` is `3`, `7 % 2` is `1`, `2 ** 10` is `1024`;
   `"ab" * 3` is `'ababab'`; `"Ada"[0:2]` is `'Ad'`.
3. A tuple refuses to change; a dict answers politely when a key is missing:

   ```python
   >>> t = (1, 2); t[0] = 5
   TypeError: 'tuple' object does not support item assignment
   >>> {"match_threshold": 0.35}.get("ceiling", -1.0)
   -1.0
   ```

4. JSON round trip:

   ```python
   >>> import json
   >>> text = json.dumps({"a": [1, 2, None], "ok": True}); text
   '{"a": [1, 2, null], "ok": true}'
   >>> json.loads(text)
   {'a': [1, 2, None], 'ok': True}
   ```

   Note `None` became `null` and `True` became `true`: JSON is a text format with its own spelling.

## 5. Change it

Open `evaluation/measure_operating_point.py` and find `TAIL_FLOOR`. **Do not** change a real constant
to experiment; copy the idea instead: in `uv run python`, put `TAIL_FLOOR = 0.326` and then
`TAIL_FLOOR = 0.5` and notice the name now points at a different value. Python allowed it; that is why
constants are a convention. The script itself reads the value from `--tail-floor` (default
`TAIL_FLOOR`), which is the safe way to vary it without editing the file (see
[`measure_operating_point`](../../06-evaluation-and-operations/02-measure-operating-point.md)).

## 6. Break it on purpose

Mix types: `"3" + 4`. Expected: `TypeError: can only concatenate str (not "int") to str`. Python will
not guess whether you meant `"34"` or `7`. Fix it explicitly: `int("3") + 4` is `7`, `"3" + str(4)` is `'34'`.
Then `int("abc")` gives `ValueError: invalid literal for int() with base 10: 'abc'`.

## 7. Exercises

1. What are the types of `3`, `3.0`, `"3"`, `(3,)` and `{3}`?
2. Why is `0.1 + 0.2 == 0.3` false and what do you do instead?
3. Write the dict `{"a": 1}` as JSON text and back, in code.
4. `p = {"margin": 0.02}`. What does `p.get("ceiling", -1.0)` return and what would `p["ceiling"]` do?
5. Open `backend/app/recognition/reasoner.py` and find the type of `match_threshold`. What value
   disables automatic matching, and why can a similarity never reach it?

**Answers**

1. `int`, `float`, `str`, `tuple`, `set`.
2. Floats are stored in binary and are approximate; compare with a small margin, or round both sides.
3. `json.loads(json.dumps({"a": 1}))` returns `{'a': 1}`; the text is `'{"a": 1}'`.
4. `-1.0`; `p["ceiling"]` raises `KeyError: 'ceiling'`.
5. `float`. A value above `1.0` (the field is allowed up to `2.0`), because a cosine similarity is never
   above 1.

## 8. Related files

- Next: [02 Conditions and loops](02-conditions-and-loops.md) · [Python index](README.md)
- [`backend/app/recognition/reasoner.py`](../../../../../backend/app/recognition/reasoner.py)
- Python's own tutorial: <https://docs.python.org/3/tutorial/>
