# Harness Template

Complete template for a shared harness header and per-function fuzz targets.
Adapt this to your specific project by replacing the project-specific types
and function names.

## Shared header: fuzz_common.h

This header handles all the boilerplate that every harness needs. The key
components are:

1. No-op output handlers (silence all printing)
2. longjmp-based error recovery (replace exit() with longjmp())
3. One-time initialization in LLVMFuzzerInitialize
4. FUZZ_CALL macro for bounds setup + truncation + error recovery

```c
#ifndef FUZZ_COMMON_H
#define FUZZ_COMMON_H

#include <config.h>              /* Project's generated config header */
#include "project-stdinc.h"      /* Project's standard includes */

#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "project.h"             /* Project's main header with context struct */

/* Extern declarations for project init functions */
extern void project_init(context_t *, uint32_t, uint32_t);

static jmp_buf fuzz_error_jmpbuf;
static context_t g_ctx;

/* --- No-op output handlers --- */

static int
fuzz_printf(context_t *ctx, const char *fmt, ...)
{
    (void)ctx; (void)fmt;
    return 0;
}

static void
fuzz_default_print(context_t *ctx, const u_char *bp, u_int length)
{
    (void)ctx; (void)bp; (void)length;
}

/*
 * Error handler: the original calls exit(), which would kill the fuzzer.
 * We longjmp back to the fuzz loop instead.
 * Must be declared NORETURN to match the original function pointer type.
 */
static void NORETURN
fuzz_error(context_t *ctx, int status, const char *fmt, ...)
{
    (void)ctx; (void)status; (void)fmt;
    longjmp(fuzz_error_jmpbuf, 1);
}

static void
fuzz_warning(context_t *ctx, const char *fmt, ...)
{
    (void)ctx; (void)fmt;
}

char *program_name = "fuzzer";

/*
 * One-time initialization. Runs before the first fuzz iteration.
 * Put anything here that allocates persistent state (lookup tables,
 * library init, etc.) to avoid per-iteration memory leaks.
 */
int LLVMFuzzerInitialize(int *argc, char ***argv)
{
    char errbuf[256];

    /* Initialize the library (if needed) */
    if (lib_init(errbuf, sizeof(errbuf)) == -1)
        return -1;

    /* Set up the context with no-op handlers */
    memset(&g_ctx, 0, sizeof(g_ctx));
    g_ctx.printf_func   = fuzz_printf;
    g_ctx.print_func    = fuzz_default_print;
    g_ctx.error_func    = fuzz_error;
    g_ctx.warning_func  = fuzz_warning;
    g_ctx.max_length    = MAX_INPUT_SIZE;  /* e.g., MAXIMUM_SNAPLEN */
    g_ctx.numeric_only  = 1;              /* Disable DNS lookups */
    g_ctx.verbosity     = 3;              /* Max verbosity for coverage */
    g_ctx.program_name  = program_name;

    /* One-time address/name table initialization */
    project_init(&g_ctx, 0, 0);
    return 0;
}

/*
 * Macro to call a target function with proper setup:
 * - Sets bounds pointers so the parser knows where the input ends
 * - Catches truncation (longjmp from bounds-check macros)
 * - Catches fatal errors (longjmp from fuzz_error)
 *
 * Usage: FUZZ_CALL(target_func(&g_ctx, data, size));
 *
 * Assumes 'data' and 'size' are in scope from LLVMFuzzerTestOneInput params.
 */
#define FUZZ_CALL(call)                                                 \
    do {                                                                \
        g_ctx.input_start = data;          /* start of input */         \
        g_ctx.input_end   = data + size;   /* end of input */           \
        g_ctx.protocol    = "";                                         \
        g_ctx.header_len  = 0;                                          \
        if (setjmp(fuzz_error_jmpbuf) == 0) {                          \
            switch (setjmp(g_ctx.truncation_jmpbuf)) {                 \
            case 0:                                                     \
                call;                                                   \
                break;                                                  \
            case TRUNCATED:                                             \
                break; /* Input was too short; not a bug */             \
            }                                                           \
        }                                                               \
    } while (0)

#endif /* FUZZ_COMMON_H */
```

## Per-function harness: fuzz_<protocol>.c

Each per-function harness is minimal — just the function declaration, minimum
size check, and the call:

```c
/*
 * Fuzz target for <protocol>_parse() — <Protocol Name> parser.
 * Identified by fuzz_target_selector (score: XX, priority: critical).
 */

#include "fuzz_common.h"

/* Declare the target function with its REAL signature from the source */
extern void protocol_parse(context_t *, const u_char *, u_int);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    /* Minimum valid input size for this protocol */
    if (size < 20)
        return 0;

    FUZZ_CALL(protocol_parse(&g_ctx, data, (u_int)size));
    return 0;
}
```

## Harness for functions needing enclosing headers

Some functions need a pointer to the enclosing protocol header (e.g., TCP
needs the IP header). Split the fuzz input:

```c
#include "fuzz_common.h"

extern void tcp_parse(context_t *, const u_char *tcp_hdr, u_int tcp_len,
    const u_char *ip_hdr, int fragmented);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    /* Need at least 20 bytes IP header + 20 bytes TCP header */
    if (size < 40)
        return 0;

    const u_char *ip_hdr  = data;
    const u_char *tcp_hdr = data + 20;
    u_int tcp_len = (u_int)(size - 20);

    FUZZ_CALL(tcp_parse(&g_ctx, tcp_hdr, tcp_len, ip_hdr, 0));
    return 0;
}
```

## Harness for functions with mode/variant flags

Use a byte from the fuzz input to select between code paths:

```c
#include "fuzz_common.h"

extern void olsr_parse(context_t *, const u_char *, u_int, int is_ipv6);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (size < 4)
        return 0;

    /* Use first byte to select IPv4 vs IPv6 code path */
    int is_ipv6 = (data[0] & 1);
    FUZZ_CALL(olsr_parse(&g_ctx, data, (u_int)size, is_ipv6));
    return 0;
}
```

## Broad harness: fuzz_<format>.c (file-format level)

For fuzzing the entire parsing pipeline via the project's file format:

```c
#include "fuzz_common.h"
#include <pcap.h>  /* or whatever file-format library */

extern if_printer get_if_printer(int);
extern void pretty_print_packet(context_t *,
    const struct pcap_pkthdr *, const u_char *, u_int);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    FILE *fp;
    pcap_t *pd;
    char errbuf[256];
    struct pcap_pkthdr *hdr;
    const u_char *pkt_data;
    u_int packets = 0;

    if (size == 0)
        return 0;

    fp = fmemopen((void *)data, size, "rb");
    if (fp == NULL)
        return 0;

    pd = pcap_fopen_offline(fp, errbuf);
    if (pd == NULL) {
        fclose(fp);
        return 0;
    }

    int dlt = pcap_datalink(pd);
    g_ctx.if_printer = get_if_printer(dlt);

    while (pcap_next_ex(pd, &hdr, &pkt_data) == 1) {
        packets++;
        if (setjmp(fuzz_error_jmpbuf) == 0)
            pretty_print_packet(&g_ctx, hdr, pkt_data, packets);
        if (packets > 1000)
            break;
    }

    pcap_close(pd);
    return 0;
}
```
