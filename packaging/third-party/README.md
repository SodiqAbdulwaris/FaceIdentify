# Third-party licence texts that a package does not carry itself

`scripts/generate_notices.py` adds these to the notices file of a build.

| File | What it is | Source |
|---|---|---|
| `DirectML-LICENSE.txt` | Microsoft Software License Terms for DirectX Machine Learning (DirectML) | `LICENSE.txt` of the `Microsoft.AI.DirectML` 1.15.4 NuGet package (nupkg SHA-256 `4e7cb7ddce8cf837a7a75dc029209b520ca0101470fcdf275c1f49736a3615b9`, read 2026-11-10) |

The `onnxruntime-windowsml` wheel ships `DirectML.dll` but not these terms. The wheel's `DirectML.dll`
(SHA-256 `89fcd116...`) is **not** byte-identical to the NuGet package's `bin/x64-win/DirectML.dll`
(`9c9e6d82...`), so that these terms govern the wheel's copy is an inference, not a verified fact
(`docs/research/licensing-and-commercialization.md` section 4b). Only the licence text is kept here,
never the library.
