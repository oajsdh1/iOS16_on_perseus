#!/usr/bin/env python3
"""Turn a raw disk image into an Android sparse image.

    img2simg.py IN.raw OUT.simg [BLOCKSIZE]

The phone's bootloader refuses a download larger than max-download-size (768 MiB
on this board), and a 12 GB root image is two orders of magnitude past that.
fastboot will however accept a sparse image and write it in -S sized chunks, so
this is what makes a multi-gigabyte image flashable at all.

The format is libsparse's: a little-endian 28 byte file header, then chunks of
one of four types. Blocks that are entirely zero become DONT_CARE (written as
nothing at the device), which is where most of the saving on a freshly
formatted volume comes from.

Implementation note: chunking is decided in a first pass that records only
(type, block-count) per chunk -- a few kilobytes -- and the data is streamed in
a second pass. Holding the payloads of every chunk in RAM (the previous
implementation) OOM-kills a 7 GB runner on a 12 GB image.
"""
import os, struct, sys

MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4

FILE_HDR_SZ = 28
CHUNK_HDR_SZ = 12
BLK = 4096
MAX_RAW_BYTES = 64 * 1024 * 1024


def classify(fin, size, blk):
    """Pass 1: return [(chunk_type, block_count)] covering the whole image."""
    plan = []
    pos = 0
    while pos < size:
        data = fin.read(blk)
        if not data:
            break
        if len(data) < blk:  # final partial block, pad it out
            data += b"\0" * (blk - len(data))
        if data.count(0) == blk:
            n = 1
            while pos + n * blk < size:
                nxt = fin.read(blk)
                if len(nxt) < blk:
                    nxt += b"\0" * (blk - len(nxt))
                if nxt.count(0) != blk:
                    fin.seek(-len(nxt), 1)
                    break
                n += 1
            plan.append((CHUNK_DONT_CARE, n))
            pos += n * blk
            continue
        n = 1
        while pos + n * blk < size and n * blk < MAX_RAW_BYTES:
            nxt = fin.read(blk)
            if len(nxt) < blk:
                nxt += b"\0" * (blk - len(nxt))
            if nxt.count(0) == blk:
                fin.seek(-len(nxt), 1)
                break
            n += 1
        plan.append((CHUNK_RAW, n))
        pos += n * blk
    return plan


def main(argv):
    if not 3 <= len(argv) <= 4:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: img2simg.py IN.raw OUT.simg [BLOCKSIZE]", file=sys.stderr)
        return 2
    blk = int(argv[3]) if len(argv) == 4 else BLK
    size = os.path.getsize(argv[1])

    with open(argv[1], "rb") as fin:
        plan = classify(fin, size, blk)
    total_blks = (size + blk - 1) // blk

    with open(argv[1], "rb") as fin, open(argv[2], "wb") as out:
        out.write(struct.pack("<I4H4I", MAGIC, 1, 0, FILE_HDR_SZ, CHUNK_HDR_SZ,
                              blk, total_blks, len(plan), 0))
        for ctype, nblocks in plan:
            nbytes = nblocks * blk
            # total_sz includes the 12-byte chunk header; for DONT_CARE there
            # is no payload after the header (libsparse parses it strictly).
            total_sz = CHUNK_HDR_SZ + (nbytes if ctype == CHUNK_RAW else 0)
            out.write(struct.pack("<2H2I", ctype, 0, nblocks, total_sz))
            if ctype == CHUNK_RAW:
                remaining = nbytes
                while remaining:
                    b = fin.read(min(1 << 24, remaining))
                    if not b:
                        raise SystemExit("input shrank unexpectedly")
                    out.write(b)
                    remaining -= len(b)
            else:
                # DONT_CARE carries no payload, but the input cursor must still
                # advance past the region it covers.
                fin.seek(nbytes, 1)
    print("%s -> %s" % (argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
