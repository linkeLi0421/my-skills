# Common Harness Pitfalls

Issues discovered during real harness development, ordered by frequency.

## 1. Wrong function signatures

Auto-generated harnesses routinely get signatures wrong:
- Missing the context/state pointer as the first argument
- Wrong parameter types (e.g., `size` instead of `u_int`)
- Wrong parameter count (missing `fragmented` flag, `caplen`, etc.)
- Passing `size` where a pointer is expected

**Fix:** Always `grep` the actual source for the real function definition.
Don't trust auto-generated code.

## 2. Missing context initialization

Most C projects pass a context struct through their call chain. Common issues:
- Not initializing function pointers (printf, error, warning handlers)
- Not setting bounds/limits fields (snaplen, max packet size)
- Not calling library init functions

**Fix:** Study how `main()` initializes the context. Replicate the essential
parts.

## 3. Error handlers that call exit()

Many projects have error handlers that call `exit()` or `abort()`. This kills
the entire fuzzer process on the first malformed input.

**Fix:** Replace the error handler with one that calls `longjmp()` back to the
fuzzer's main loop. Make sure it's declared `NORETURN` to match the original
signature.

```c
static jmp_buf error_jmpbuf;

static void NORETURN
fuzz_error(context_t *ctx, int status, const char *fmt, ...)
{
    longjmp(error_jmpbuf, 1);
}
```

## 4. DNS/network lookups causing timeouts

Network protocol parsers often resolve IP addresses to hostnames. In a fuzzing
environment with no network, `gethostbyaddr()` blocks for 25+ seconds per call.

**Fix:** Set the "numeric output" flag (e.g., `ndo_nflag = 1` for tcpdump) to
suppress DNS resolution.

## 5. Memory leaks from repeated initialization

If `LLVMFuzzerTestOneInput` calls init functions that allocate memory (lookup
tables, name caches), LeakSanitizer will flag every iteration as a leak.

**Fix:** Move one-time initialization to `LLVMFuzzerInitialize()` and keep the
context as a static global.

## 6. Missing bounds/truncation setup

Protocol dissectors typically check whether they're reading past the end of
the packet using a "snapend" pointer or similar mechanism. If your harness
doesn't set this up, the dissector may read out of bounds.

**Fix:** Before calling the target function, set:
- The start-of-packet pointer
- The end-of-packet pointer (data + size)
- The setjmp buffer for truncation recovery

## 7. Missing link-time dependencies

The target project's static library may depend on OpenSSL, zlib, or other
system libraries. The build will succeed but linking fails.

Common missing libraries:
- `-lcrypto` — OpenSSL (MD5, EVP, HMAC)
- `-lssl` — OpenSSL TLS
- `-lz` — zlib compression
- `-lm` — math library
- `-lpthread` — threading

## 8. Auto-generated include paths

The skeleton harnesses include headers like `"print-ip.h"` that don't exist.
The actual headers are usually `"netdissect.h"`, `"config.h"`, etc.

**Fix:** Look at what the real source files include and replicate that.

## 9. Not setting verbosity flags

Many dissectors have verbosity-gated code paths. If verbosity is 0 (the
default from memset), large portions of the code are never exercised.

**Fix:** Set verbosity to maximum (e.g., `ndo_vflag = 3`) to exercise all
code paths. Also enable link-layer header printing, extended output, etc.

## 10. Forgetting the seed corpus

A good seed corpus dramatically accelerates fuzzing. Most projects have test
files that exercise their parsers.

**Fix:** Zip up the test files and copy to `$OUT/<target>_seed_corpus.zip`.
Use `-j` flag with zip to flatten directory structure.
