/* Byte-bounded whole-free-block reclamation for the audited Unity Mono ABI.
 * No new marking rules, object relocation, heap limit, allocation or OS allocator.
 * Called only by the original finish_collection call site under its original lock.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned long long u64;

typedef struct FreeHeader {
    u64 bytes;
    u64 next;
    u64 previous;
    u64 descriptor;
    u64 free_marker;
    u8 kind;
    u8 flags;
    u16 reclaimed;
} FreeHeader;

typedef struct ReclaimState {
    u64 magic;
    u64 reserve_bytes;
    u64 collections;
    u64 scanned_blocks;
    u64 whole_free_committed_before;
    u64 whole_free_committed_after;
    u64 decommitted_bytes;
    u64 decommitted_blocks;
    u64 rejected;
    u64 last_gc;
    u64 last_returned;
    u64 last_scanned;
} ReclaimState;

typedef FreeHeader* (*FindHeader)(u64 block);
typedef void (*Unmap)(u64 block, u64 bytes);

#define FREE_LIST_RVA 0x269d70
#define FREE_MARKER_RVA 0x269f70
#define GC_COUNT_RVA 0x269b90
#define PAGE_SIZE_RVA 0x26c5c8
#define UNMAPPED_RVA 0x27ea88
#define FIND_HEADER_RVA 0x15ee50
#define UNMAP_RVA 0x15eb8c
#define BUCKETS 61
#define MAGIC 0x31524c5443524347ULL
#define MAX_BLOCKS 1048576ULL
#define MAX_BYTES (1ULL << 44)
#define MIB (1024ULL * 1024ULL)

static u64 pages(u64 block, u64 bytes, u64 page_size)
{
    u64 start = (block + page_size - 1) & ~(page_size - 1);
    u64 end = (block + bytes) & ~(page_size - 1);
    return end > start ? end - start : 0;
}

static int valid(FreeHeader* h, u64 marker, u64 block)
{
    return (u64)h > 4096 && !(block & 4095) && h->free_marker == marker
        && h->bytes && !(h->bytes & 4095) && h->bytes < MAX_BYTES
        && block + h->bytes > block;
}

/* Preserve warm reusable storage. Retire aged blocks first, large blocks before
 * small blocks; only the excess can retire fresh blocks. This replaces fixed GC
 * age admission with one explicit committed-storage budget, not a live-heap cap.
 */
__declspec(dllexport) void reclaim_controller(u8* base, ReclaimState* state)
{
    u64* lists = (u64*)(base + FREE_LIST_RVA);
    u64 marker = *(u64*)(base + FREE_MARKER_RVA);
    u64 gc = *(u64*)(base + GC_COUNT_RVA);
    u64 page_size = *(u64*)(base + PAGE_SIZE_RVA);
    FindHeader find_header = (FindHeader)(base + FIND_HEADER_RVA);
    Unmap unmap = (Unmap)(base + UNMAP_RVA);
    u64 committed = 0, count = 0, returned = 0;
    int bucket, pass;

    if (state->magic != MAGIC || page_size < 4096 || page_size > 65536
        || (page_size & (page_size - 1)) || state->reserve_bytes > 1024 * MIB) {
        state->rejected++;
        return;
    }

    /* Validate the complete inventory before making any retirement decision. */
    for (bucket = BUCKETS - 1; bucket >= 0; --bucket) {
        u64 block = lists[bucket];
        while (block) {
            FreeHeader* h = find_header(block);
            if (++count > MAX_BLOCKS || !valid(h, marker, block)) {
                state->rejected++;
                return;
            }
            if (!(h->flags & 2))
                committed += pages(block, h->bytes, page_size);
            block = h->next;
        }
    }
    state->collections++;
    state->scanned_blocks += count;
    state->last_scanned = count;
    state->last_gc = gc;
    state->whole_free_committed_before = committed;

    /* Pass 0: older whole-free blocks. Pass 1: fresh excess. The collector lock,
     * free-list links and original unmap/remap bookkeeping remain authoritative.
     */
    for (pass = 0; pass < 2 && committed > state->reserve_bytes; ++pass) {
        for (bucket = BUCKETS - 1; bucket >= 0 && committed > state->reserve_bytes; --bucket) {
            u64 block = lists[bucket];
            while (block && committed > state->reserve_bytes) {
                FreeHeader* h = find_header(block);
                u64 next = h->next;
                u64 bytes = pages(block, h->bytes, page_size);
                u16 age = (u16)((u16)gc - h->reclaimed);
                if (!(h->flags & 2) && bytes && (pass == 1 || age > 1)) {
                    u64 before = *(u64*)(base + UNMAPPED_RVA);
                    /* Original routine covers page alignment, reservation
                     * boundaries, VirtualFree failure and native accounting.
                     */
                    unmap(block, h->bytes);
                    h->flags |= 2;
                    returned += *(u64*)(base + UNMAPPED_RVA) - before;
                    committed -= bytes;
                    state->decommitted_blocks++;
                }
                block = next;
            }
        }
    }
    state->decommitted_bytes += returned;
    state->last_returned = returned;
    state->whole_free_committed_after = committed;
}
