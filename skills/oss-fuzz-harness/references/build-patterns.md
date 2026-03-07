# Build Script Patterns

Templates for common build.sh patterns in OSS-Fuzz projects.

## Pattern 1: CMake project with static library dependency

This is the most common pattern for projects like tcpdump (depends on libpcap).

```bash
#!/bin/bash -eu

# Build the dependency as a static library
cd $SRC/<dependency>
mkdir -p build && cd build
cmake ..
make -j$(nproc)

# Build the target project
cd $SRC/<project>
mkdir -p build && cd build
cmake .. -D<DEP>_INCLUDE_DIR=$SRC/<dependency> \
         -D<DEP>_LIBRARY=$SRC/<dependency>/build/lib<dep>.a
make -j$(nproc)

# Common flags for all fuzz targets
COMMON_CFLAGS="-I$SRC/<project> -I$SRC/<project>/build -I$SRC/<dependency> -I$SRC"
COMMON_LIBS="$SRC/<project>/build/lib<project>.a \
    $SRC/<dependency>/build/lib<dep>.a \
    $LIB_FUZZING_ENGINE \
    -lcrypto"  # Add system libs as needed

# Build all fuzz targets
for fuzzer in $SRC/fuzz_*.c; do
    target=$(basename "$fuzzer" .c)
    $CC $CFLAGS $COMMON_CFLAGS -c "$fuzzer" -o "$SRC/${target}.o"
    $CXX $CXXFLAGS "$SRC/${target}.o" -o "$OUT/$target" $COMMON_LIBS
done

# Seed corpus from test files
cd $SRC/<project>
zip -j $OUT/fuzz_<format>_seed_corpus.zip tests/*.<ext>
```

## Pattern 2: Autoconf project

```bash
#!/bin/bash -eu

cd $SRC/<project>
./autogen.sh  # if needed
./configure --disable-shared
make -j$(nproc)

COMMON_CFLAGS="-I$SRC/<project>/include -I$SRC/<project>"
COMMON_LIBS="$SRC/<project>/.libs/lib<project>.a $LIB_FUZZING_ENGINE"

for fuzzer in $SRC/fuzz_*.c; do
    target=$(basename "$fuzzer" .c)
    $CC $CFLAGS $COMMON_CFLAGS -c "$fuzzer" -o "$SRC/${target}.o"
    $CXX $CXXFLAGS "$SRC/${target}.o" -o "$OUT/$target" $COMMON_LIBS
done
```

## Pattern 3: Project with upstream fuzz targets

Some projects already have fuzz targets in their repo. Build and copy them:

```bash
#!/bin/bash -eu

cd $SRC/<project>
mkdir -p build && cd build
cmake .. -DFUZZING=ON
make -j$(nproc)

# Copy upstream fuzzers
cp fuzz_* $OUT/

# Also build custom fuzzers
for fuzzer in $SRC/fuzz_*.c; do
    target=$(basename "$fuzzer" .c)
    $CC $CFLAGS -I.. -c "$fuzzer" -o "${target}.o"
    $CXX $CXXFLAGS "${target}.o" -o "$OUT/$target" lib<project>.a $LIB_FUZZING_ENGINE
done
```

## Common system library flags

| Dependency | Link flag | When needed |
|-----------|-----------|-------------|
| OpenSSL crypto | `-lcrypto` | MD5, SHA, EVP, HMAC functions |
| OpenSSL TLS | `-lssl` | TLS/SSL functions |
| zlib | `-lz` | Compression/decompression |
| math | `-lm` | Math functions (sin, cos, pow) |
| pthreads | `-lpthread` | Threading |
| libxml2 | `-lxml2` | XML parsing |
| libpcap | `libpcap.a` | Packet capture (build from source) |

## Dockerfile dependency packages

Common `apt-get install` packages:

| Package | When needed |
|---------|-------------|
| `cmake` | CMake build system |
| `make` | Make build system |
| `autoconf automake libtool` | Autoconf projects |
| `flex bison` | Projects with lexer/parser generators |
| `pkg-config` | Projects using pkg-config |
| `libssl-dev` | OpenSSL headers |
| `zlib1g-dev` | zlib headers |
| `libxml2-dev` | libxml2 headers |
