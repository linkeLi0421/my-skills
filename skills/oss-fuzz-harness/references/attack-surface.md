# Attack Surface Analysis Methodology

How to identify the best fuzz targets in a C/C++ project by analyzing its
attack surface — the paths through which untrusted input enters and gets
processed.

## Why not just use automated tools?

Tools like `fuzz_target_selector` use regex heuristics to score functions by
complexity and security-relevant patterns (malloc, memcpy, pointer arithmetic).
This finds complex functions, but misses the critical question: **does this
function actually process untrusted input?**

A highly complex internal function that only receives validated, pre-processed
data is a poor fuzz target. A simpler public API function that directly parses
user-supplied strings is a much better one.

**Use automated tools to rank candidates, not to discover them.**

## The analysis workflow

### 1. Orient: understand the project

Before diving into code, answer:
- What does this project do? (media processing, networking, crypto, etc.)
- What are its input formats? (files, network packets, config strings, URLs)
- What is the public API prefix? (`av_`, `SSL_`, `pcap_`, etc.)
- What's already fuzzed? (check `projects/<name>/` in oss-fuzz, and in-tree fuzzers)

### 2. Find input entry points

Search for where untrusted data enters the codebase:

```bash
# I/O functions
grep -rn "fread\|fgets\|recv\|read(" /tmp/<project>/lib*/ | head -30

# Public API accepting strings or buffers
grep -rn "^int\|^void\|^char\|^const" /tmp/<project>/include/*.h | \
    grep "const char \*\|const uint8_t \*" | head -30

# Handler registrations (function pointer tables)
grep -rn "\.parse\s*=\|\.decode\s*=\|\.read_header\s*=" /tmp/<project>/ | head -20
```

### 3. Trace input flow

For each entry point, read the source and follow the data:
- What function is called first with the raw input?
- Does it delegate to sub-parsers? (format-specific handlers, protocol decoders)
- Where does actual parsing happen? (byte-by-byte loops, sscanf, state machines)

### 4. Evaluate each candidate

A function is a good fuzz target if it scores well on ALL of these:

| Criterion | Good | Bad |
|-----------|------|-----|
| **Input source** | Takes untrusted user input | Only receives pre-validated data |
| **Parsing complexity** | Has loops, switches, sscanf over input | Simple getter/setter |
| **Standalone callability** | Can be called with just input + simple args | Requires complex state machine setup |
| **Existing coverage** | Not reached by existing fuzz harnesses | Already exercised transitively |
| **API stability** | Public API with stable signature | Internal function that changes often |

## Example: FFmpeg

### Orientation

FFmpeg is a multimedia framework. Input: media files, URLs, codec parameters,
format strings. Public API prefix: `av_`. Internal prefix: `ff_`.

### Entry points found

Searching `libavutil/` and `libavformat/` for public functions taking string input:

| Function | Input | What it does |
|----------|-------|-------------|
| `av_parse_time()` | `const char *timestr` | Parses time strings like "12:34:56.789", "2h30m", ISO 8601 |
| `av_parse_color()` | `const char *color_string` | Parses color names and hex values like "#FF0000", "red" |
| `av_expr_parse_and_eval()` | `const char *expr` | Evaluates math expressions like "1+2*sin(PI)" |
| `av_url_split()` | `const char *url` | Splits URL into proto/auth/host/port/path components |
| `ff_make_absolute_url()` | `const char *base, const char *rel` | Resolves relative URLs against base (2 untrusted inputs) |
| `av_dict_parse_string()` | `const char *str` + delimiters | Parses key=value pairs with configurable delimiters |
| `av_channel_layout_from_string()` | `const char *layout` | Parses channel layout descriptions |
| `av_strptime()` | `const char *buf, const char *fmt` | strptime variant (2 untrusted inputs: data + format) |
| `ff_htmlmarkup_to_ass()` | `const char *markup` | Converts HTML markup to ASS subtitle format |

### Targets rejected

| Function | Reason |
|----------|--------|
| `ff_htmlmarkup_to_ass()` | Already exercised by subtitle decoder fuzz harnesses. Internal API (`ff_`). |
| `avformat_open_input()` | Too broad — the existing FFmpeg OSS-Fuzz coverage already fuzzes demuxers. |
| `av_packet_unref()` | Cleanup function, no parsing logic. |

### Targets selected

All the `av_*` functions above were selected because they:
1. Are public API functions (stable, easy to link)
2. Take untrusted string input directly
3. Have non-trivial parsing logic (loops, state machines, format handling)
4. Can be called standalone with minimal setup
5. Were NOT already covered by existing FFmpeg fuzz harnesses

The `ff_htmlmarkup_to_ass()` function was also included despite being internal,
because it has a clear HTML parsing attack surface and a simple call signature.
However, its value is lower since subtitle decoders already exercise it.

### Harness patterns used

**String parser (single input):**
```c
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Null-terminate the fuzz input for string APIs
    char *str = malloc(size + 1);
    if (!str) return 0;
    memcpy(str, data, size);
    str[size] = '\0';

    // Call the target
    int64_t result;
    av_parse_time(&result, str, 0);

    free(str);
    return 0;
}
```

**Multi-input parser (split fuzz input into 2+ strings):**
```c
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Split input at first null byte to get two independent strings
    const char *str = (const char *)data;
    size_t first_len = strnlen(str, size);

    if (first_len >= size) return 0;  // need at least 2 strings

    const char *first = str;
    const char *second = str + first_len + 1;
    // ... use both strings as input
}
```

## Example: tcpdump

### Orientation

tcpdump is a network packet dissector. Input: raw network packets (binary
format from pcap files or live capture). Uses libpcap for capture, has its own
protocol dissection layer. No public API prefix — dissector functions are named
`<protocol>_print()`.

### Entry points found

tcpdump processes packets through a dissection chain. The entry point is
`pretty_print_packet()` which dispatches to per-protocol printers based on
the link-layer type, then each protocol printer dispatches to the next layer.

Key dissector functions:

| Function | Protocol | Input |
|----------|----------|-------|
| `ip_print()` | IPv4 | Raw IP packet bytes |
| `ip6_print()` | IPv6 | Raw IPv6 packet bytes |
| `tcp_print()` | TCP | TCP segment bytes (after IP header) |
| `icmp_print()` | ICMP | ICMP message bytes |
| `cdp_print()` | CDP | Cisco Discovery Protocol bytes |
| `olsr_print()` | OLSR | Optimized Link State Routing bytes |
| `isoclns_print()` | ISO CLNS | ISO connectionless network bytes |

### Two-level fuzzing strategy

1. **Broad harness** (`fuzz_pcap`): Feed a complete pcap file through
   `pcap_offline_read()`. This exercises the full dissection pipeline but the
   fuzzer has less control over individual protocols.

2. **Targeted harnesses** (`fuzz_ip`, `fuzz_tcp`, etc.): Feed raw bytes
   directly to individual protocol printers. This bypasses pcap overhead and
   lets the fuzzer focus mutations on one protocol parser.

### Key implementation details

tcpdump dissectors require a `netdissect_options` context struct with:
- Output function pointers (set to no-ops for fuzzing)
- `setjmp`/`longjmp` for truncation recovery (set `ndo_snapend`)
- Various flags (suppress DNS lookups with `ndo_nflag = 1`)

This led to creating a `fuzz_common.h` shared header — see
`references/harness-template.md` for the pattern.

## Checklist

Use this checklist when analyzing a new project:

- [ ] Read project README, identify what it does and its input formats
- [ ] Identify public API prefix
- [ ] Check for existing fuzz targets (in-tree and in OSS-Fuzz)
- [ ] Search for public functions that accept `const char *` or `const uint8_t *`
- [ ] Search for handler/decoder registration tables
- [ ] For each candidate: can it be called standalone? Does it parse untrusted input?
- [ ] Reject functions already covered transitively by existing harnesses
- [ ] Prefer public API (`av_*`) over internal (`ff_*`) functions
- [ ] Classify targets by type (string parser, binary parser, multi-input, etc.)
- [ ] Optionally run fuzz_target_selector to rank by complexity
