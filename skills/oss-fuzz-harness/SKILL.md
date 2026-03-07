---
name: oss-fuzz-harness
description: >
  End-to-end workflow for adding C/C++ projects to OSS-Fuzz: analyze source code
  to identify high-value fuzz targets, generate correct fuzz harnesses, create
  OSS-Fuzz project files, build and verify everything. Use this skill whenever
  the user wants to fuzz a C/C++ project, add a project to OSS-Fuzz, write fuzz
  harnesses, find critical functions to fuzz, or improve fuzzing coverage. Also
  trigger when the user mentions fuzzing, libFuzzer, AFL, honggfuzz, sanitizers
  (ASAN/UBSAN/MSAN), or asks about fuzz target selection for any C/C++ codebase.
---

# OSS-Fuzz Harness Generator

This skill automates the full pipeline from source analysis to running fuzzers
for C/C++ projects in the OSS-Fuzz framework.

## Overview

The workflow has five phases:

1. **Attack Surface Analysis** — Identify high-value fuzz targets by analyzing how untrusted input enters and flows through the codebase
2. **Research** — Study actual function signatures and internal APIs
3. **Generate** — Write correct harnesses and OSS-Fuzz project files
4. **Build** — Compile and verify with OSS-Fuzz infrastructure
5. **Run** — Execute fuzzers and confirm they work

Each phase has common pitfalls. This skill captures the lessons learned from
real harness development so you avoid the usual traps.

## Phase 1: Attack Surface Analysis

Analyze the project's attack surface to find the best fuzz targets. Do not
rely solely on automated tools — understand how untrusted input enters and
flows through the code. See `references/attack-surface.md` for detailed
methodology and real examples.

### Step 1: Clone and orient

```bash
git clone --depth 1 <repo-url> /tmp/<project>
```

Get oriented quickly:
- Read the project README for an overview of what the project does
- Identify the project's public API prefix (e.g., `av_` for FFmpeg, `pcap_` for libpcap)
- Check for existing fuzz targets — don't duplicate coverage that already exists

```bash
# Check for existing fuzz targets in the project
find /tmp/<project> -name "*fuzz*" -o -name "*fuzzer*" | head -20

# Check what OSS-Fuzz already covers
ls projects/<project>/ 2>/dev/null
```

### Step 2: Identify input entry points

Find where untrusted data enters the codebase:

- **I/O functions**: `read()`, `recv()`, `fread()`, `fopen()`, `pcap_*`
- **Public API functions**: Functions with the project's API prefix that accept
  user-supplied data (e.g., `av_parse_time()`, `SSL_read()`)
- **Format/protocol handlers**: Function pointer tables, vtables, codec/format
  registration structs
- **Command-line parsers**: `getopt`, option parsing, config file readers

```bash
# Find public API functions that take string or buffer input
grep -rn "^[a-z].*\(.*const char \*\|const uint8_t \*\|const unsigned char \*" \
    /tmp/<project>/include/ /tmp/<project>/lib*/ 2>/dev/null | head -40

# Find format/protocol handler registrations
grep -rn "\.read\s*=\|\.parse\s*=\|\.decode\s*=\|\.dissect\s*=" \
    /tmp/<project>/ | head -20
```

### Step 3: Trace input flow

From each entry point, follow the data through the call graph:
- Which functions directly parse or process the untrusted input?
- Where does the parsing logic live (string parsing, binary decoding, etc.)?
- What intermediate functions transform or validate the data?

Read the actual source code of promising functions. Prioritize functions that:
- Take raw input buffers and parse structured data from them
- Have complex control flow (switches, loops over input bytes)
- Do memory allocation based on input-controlled values

### Step 4: Classify and select targets

Categorize candidates into target types. Each type has different fuzzing value:

| Target Type | Description | Example |
|---|---|---|
| **String parsers** | Take `const char *`, parse with sscanf/strtol/char loops | `av_parse_time()`, `av_parse_color()` |
| **Binary format parsers** | Take `uint8_t *` + length, decode structured data | Codec decode functions, packet parsers |
| **URL/path manipulation** | URL splitting, path joining, encoding/decoding | `av_url_split()`, `ff_make_absolute_url()` |
| **Expression evaluators** | Math/query/format string processors | `av_expr_parse_and_eval()` |
| **Multi-input parsers** | Take 2+ independent untrusted strings | `av_dict_parse_string()` (input + delimiters) |
| **Recursive descent parsers** | Self-calling or mutually recursive parsing | HTML/XML parsers, nested format parsers |

**Target selection criteria — a function is a good fuzz target if:**
1. It takes untrusted input (string, buffer, or structured data)
2. It has non-trivial parsing logic (not just a thin wrapper)
3. It can be called standalone without complex state setup
4. It is not already fuzzed transitively by existing harnesses

**Prefer public API functions** (e.g., `av_*`) over internal functions (e.g.,
`ff_*`) — they have stable signatures, are easier to link, and represent the
actual attack surface that external callers use.

### Step 5 (optional): Use fuzz_target_selector for complexity ranking

The `fuzz_target_selector` tool can help prioritize among candidates by
measuring code complexity. Use it as a **supplement** to your analysis, not
as the primary discovery method.

```bash
cd fuzz_target_selector/
python3 fuzz_target_selector.py analyze /tmp/<project> \
    --project <project-name> -o /tmp/<project>_targets.json -n 100

python3 fuzz_target_selector.py list /tmp/<project>_targets.json \
    --priority critical -n 20
```

Cross-reference the complexity scores with your attack surface analysis.
High-complexity functions that also sit on input paths are the best targets.

## Phase 2: Research the Target Project

Before writing harnesses, study the actual source code to understand:

1. **Exact function signatures** — The auto-generator often gets parameter
   types and counts wrong. Grep the source for the real declarations.

2. **Context/state objects** — Many C projects pass a context struct through
   their call chain (like tcpdump's `netdissect_options`). Identify what fields
   must be initialized and what function pointers need to be set.

3. **Error handling** — Find functions that call `exit()` or `abort()`. These
   will kill the fuzzer. You need `longjmp`-based recovery instead.

4. **Bounds checking** — Find how the project checks for truncated/short input.
   Many use `setjmp`/`longjmp` for early termination on truncated data. Your
   harness must set up the same mechanism.

5. **Network/DNS calls** — Functions that do DNS lookups or network I/O will
   cause timeouts during fuzzing. Find flags that disable these.

6. **Build system** — Read CMakeLists.txt or Makefile to understand what
   libraries are built (especially static libs) and what dependencies exist.

7. **Test files** — Look for a `tests/` directory with sample inputs that can
   serve as seed corpus.

```bash
# Example: find function signatures
grep -rn "^function_name\|^void.*function_name\|^int.*function_name" *.c

# Find context struct definitions
grep -n "struct.*options\|typedef.*context" *.h

# Find exit/abort calls in the library
grep -rn "exit(\|abort(" lib/ src/
```

## Phase 3: Generate Harnesses

### OSS-Fuzz project files

Create `projects/<project>/` with four file types:

**project.yaml:**
```yaml
homepage: "<project-homepage>"
language: c  # or c++
primary_contact: "<security-contact>"
fuzzing_engines:
  - libfuzzer
  - afl
  - honggfuzz
sanitizers:
  - address
  - undefined
  # Only add 'memory' if the project compiles cleanly with MSAN.
  # Projects using many system headers often don't.
main_repo: '<git-repo-url>'
```

**Dockerfile:**
```dockerfile
FROM gcr.io/oss-fuzz-base/base-builder
RUN apt-get update && apt-get install -y <build-deps>
RUN git clone --depth 1 <dependency-repos>
RUN git clone --depth 1 <main-repo>
WORKDIR $SRC
COPY build.sh *.h *.c $SRC/
```

**build.sh** — See `references/build-patterns.md` for templates.

### Writing correct harnesses

The most important lesson: **auto-generated harnesses are almost always wrong.**
You must manually verify every function signature against the actual source.

For projects with a shared context object, create a `fuzz_common.h` that handles
all the boilerplate. This avoids duplicating the same setup code in every harness.

The common header should provide:

1. **No-op output functions** — The project's print/log functions should be
   silenced during fuzzing. They waste time and can trigger false positives.

2. **longjmp-based error recovery** — Replace any `exit()`-calling error
   handler with one that does `longjmp()` back to the fuzzer loop.

3. **Warning suppression** — No-op warning handlers.

4. **One-time initialization** — Use `LLVMFuzzerInitialize()` for setup that
   should happen once (lookup table init, library init). This avoids memory
   leaks from repeated initialization.

5. **A dissector/parser call macro** — Wrap the target function call with
   proper bounds setup and truncation recovery.

See `references/harness-template.md` for a complete template with examples.

### Per-function harnesses

Each harness should be minimal — just include the common header, declare the
extern function with its real signature, and call it through the macro:

```c
#include "fuzz_common.h"

extern void target_func(context_t *, const u_char *, u_int);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (size < MINIMUM_INPUT_SIZE)
        return 0;

    FUZZ_CALL(target_func(&g_ctx, data, (u_int)size));
    return 0;
}
```

Choose minimum input sizes based on the protocol's minimum header:
- IPv4: 20 bytes
- IPv6: 40 bytes
- TCP: 20 bytes (+ 20 for enclosing IP = 40 total)
- UDP: 8 bytes
- ICMP: 8 bytes
- Generic TLV protocols: 4 bytes
- Single-byte dispatch: 1 byte

### build.sh patterns

The build script should:

1. Build dependencies as static libraries
2. Build the target project (generates config headers and static libs)
3. Loop over all fuzz_*.c files, compile and link each one
4. Create seed corpus from test files

```bash
COMMON_CFLAGS="-I$SRC/<project> -I$SRC/<project>/build -I$SRC/<dep>"
COMMON_LIBS="$SRC/<project>/build/lib<name>.a $SRC/<dep>/build/lib<dep>.a \
    $LIB_FUZZING_ENGINE <extra-libs>"

for fuzzer in $SRC/fuzz_*.c; do
    target=$(basename "$fuzzer" .c)
    $CC $CFLAGS $COMMON_CFLAGS -c "$fuzzer" -o "$SRC/${target}.o"
    $CXX $CXXFLAGS "$SRC/${target}.o" -o "$OUT/$target" $COMMON_LIBS
done
```

Watch for missing library dependencies at link time — if the project uses
OpenSSL, zlib, etc., add `-lcrypto`, `-lz`, etc. to COMMON_LIBS.

## Phase 4: Build and Verify

Run the three verification steps in order:

```bash
# 1. Build the Docker image
echo "n" | python3 infra/helper.py build_image <project>

# 2. Compile fuzzers inside the container
echo "n" | python3 infra/helper.py build_fuzzers <project>

# 3. Verify binaries pass OSS-Fuzz checks
echo "n" | python3 infra/helper.py check_build <project>
```

Common build failures and fixes:

| Error | Fix |
|-------|-----|
| `undefined reference to MD5_Init` | Add `-lcrypto` to link flags |
| `undefined reference to inflate` | Add `-lz` to link flags |
| `LeakSanitizer: detected memory leaks` | Move init code to `LLVMFuzzerInitialize` |
| `ALARM: timeout after N seconds` | Set flags to disable DNS/network I/O |
| Wrong function signature | Check actual source, fix extern declaration |
| Missing `config.h` | Build the project with cmake/configure first |

## Phase 5: Run Fuzzers

```bash
# Quick smoke test (10 seconds)
echo "n" | python3 infra/helper.py run_fuzzer <project> <target> \
    -- -max_total_time=10

# Longer validation (1+ minutes)
echo "n" | python3 infra/helper.py run_fuzzer <project> <target> \
    -- -max_total_time=60

# Run multiple in parallel for extended testing
bash -c '
(echo "n" | python3 infra/helper.py run_fuzzer <project> fuzz_a -- -max_total_time=3600 2>&1 | tail -50 > /tmp/fuzz_a.log) &
(echo "n" | python3 infra/helper.py run_fuzzer <project> fuzz_b -- -max_total_time=3600 2>&1 | tail -50 > /tmp/fuzz_b.log) &
wait
'
```

A healthy fuzzer should show:
- Steadily increasing `cov:` (coverage) numbers
- Thousands of `runs` per second (varies by complexity)
- No `ERROR`, `SUMMARY`, `leak`, `timeout` lines
- `Done N runs in M second(s)` at the end

## Decision Guide

**One broad harness vs. many targeted harnesses?**

Do both. A broad harness (like `fuzz_pcap` that feeds full file format input
through the main parsing pipeline) exercises all code paths but gives the fuzzer
less direct control. Per-function harnesses (like `fuzz_ip`, `fuzz_tcp`) bypass
format overhead and let the fuzzer focus mutations on the specific protocol
parser. The broad harness catches integration bugs; targeted harnesses find
deeper protocol-specific bugs.

**Which functions to target?**

Use Phase 1's attack surface analysis to identify candidates, then apply these
filters:

- **Prefer public API over internal functions** — `av_parse_time()` over
  `ff_parse_time()`. Public APIs have stable signatures, are easier to link,
  and represent the real attack surface.
- **Check what's already fuzzed transitively** — If the project has a broad
  harness that exercises a parser pipeline, individual parsers in that pipeline
  may already get coverage. Focus on functions that are NOT reached by existing
  harnesses. Example: FFmpeg's subtitle decoders already exercise
  `ff_htmlmarkup_to_ass()` transitively, so a standalone harness adds less value.
- **Skip `main()`** — It's not useful to fuzz directly.
- **A good target function**: takes untrusted input, has non-trivial parsing
  logic, and can be called standalone without complex state setup.

**Naming conventions by target type:**
- String/expression parsers: `target_<name>_fuzzer.c` (e.g., `target_parse_time_fuzzer.c`)
- Protocol parsers: `fuzz_<protocol>.c` (e.g., `fuzz_tcp.c`)
- Format parsers: `fuzz_<format>.c` (e.g., `fuzz_pcap.c`)

**When to skip memory sanitizer (MSAN)?**

Skip MSAN when the project uses many system headers or third-party libraries
that aren't MSAN-instrumented. ASAN + UBSAN cover most bugs. Add MSAN only
if the project compiles cleanly with it.
