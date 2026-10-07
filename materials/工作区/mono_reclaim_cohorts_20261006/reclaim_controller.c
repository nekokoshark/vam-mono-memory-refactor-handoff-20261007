/* Linked allocation/reclamation policies for the audited Unity Mono ABI.
 * Original marking, object layout, maximum heap, locks and OS allocator remain.
 * Five original callsites enter these policies under the original allocator lock.
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
    u64 sort_runs;
    u64 sort_pages;
    u64 sort_lists;
    u64 sort_changed_lists;
    u64 merge_calls;
    u64 merged_blocks;
    u64 remap_calls;
    u64 remap_full_bytes;
    u64 remap_prefix_bytes;
    u64 remap_avoided_bytes;
    u64 split_prefixes;
    u64 growth_calls;
    u64 growth_original_blocks;
    u64 growth_actual_blocks;
    u64 pending_block;
    u64 pending_full;
    u64 pending_bytes;
    u64 warm_batches;
    u64 warm_bytes;
    u64 warm_extra_bytes;
    u64 chain_scans;
    u64 chain_pages_validated;
    u64 chain_header_rejects;
    u64 chain_mark_rejects;
    u64 chain_limit_rejects;
    u64 last_rejected_kind;
    u64 last_rejected_size;
    u64 last_reject_reason;
    u64 max_chain_pages;
    u64 last_pending_pages;
    u64 uniform_chains;
} ReclaimState;

typedef FreeHeader* (*FindHeader)(u64 block);
typedef void (*Unmap)(u64 block, u64 bytes);
typedef void (*NoArgs)(void);
typedef void (*RemoveFree)(FreeHeader* h, int bucket);
typedef void (*AddFree)(u64 block, FreeHeader* h);
typedef u64 (*FirstPart)(u64 block, FreeHeader* h, u64 bytes, int bucket);
typedef int (*Expand)(u64 blocks);
typedef void (*RemoveHeader)(u64 block);

#define FREE_LIST_RVA 0x269d70
#define FREE_MARKER_RVA 0x269f70
#define GC_COUNT_RVA 0x269b90
#define PAGE_SIZE_RVA 0x26c5c8
#define UNMAPPED_RVA 0x27ea88
#define FIND_HEADER_RVA 0x15ee50
#define UNMAP_RVA 0x15eb8c
#define REMAP_RVA 0x15ec50
#define MERGE_RVA 0x15fd18
#define INSTALL_HEADER_RVA 0x15f12c
#define REMOVE_HEADER_RVA 0x15f298
#define REMOVE_FREE_RVA 0x15fa24
#define ADD_FREE_RVA 0x15fc04
#define FIRST_PART_RVA 0x15fecc
#define EXPAND_RVA 0x1580e8
#define KIND_TABLE_RVA 0x2659a0
#define KIND_COUNT_RVA 0x265998
#define FREE_BYTES_RVA 0x27c808
#define HEAP_BYTES_RVA 0x27c7e0
#define BUCKETS 61
#define MAGIC 0x31524c5443524347ULL
#define MAX_BLOCKS 1048576ULL
#define MAX_BYTES (1ULL << 44)
#define MIB (1024ULL * 1024ULL)
#define WARM_QUANTUM 65536ULL

/* Native header marks occupy eight words at +0x30. The size is in eight-byte
 * words for allocated small blocks, but in bytes for whole-free blocks.
 * Reorder only the collector's pending reclaim chains, never object free lists,
 * thread-local lists, marks, object contents or objects themselves.
 */
static u64 marked(FreeHeader* h)
{
    u64 total = 0, i;
    u64* marks = (u64*)((u8*)h + 0x30);
    for (i = 0; i < 8; ++i) {
        u64 x = marks[i];
        x -= (x >> 1) & 0x5555555555555555ULL;
        x = (x & 0x3333333333333333ULL) + ((x >> 2) & 0x3333333333333333ULL);
        x = (x + (x >> 4)) & 0x0f0f0f0f0f0f0f0fULL;
        total += (x * 0x0101010101010101ULL) >> 56;
    }
    return total;
}

__declspec(noinline) static void reject_chain(ReclaimState* state, int kind, u64 size, u64 reason)
{
    state->rejected++;
    state->last_rejected_kind = (u64)kind;
    state->last_rejected_size = size;
    state->last_reject_reason = reason;
    if (reason == 1) state->chain_limit_rejects++;
    else if (reason == 7) state->chain_mark_rejects++;
    else state->chain_header_rejects++;
}

static void order_reclaim(u8* base, ReclaimState* state)
{
    FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
    int kinds = *(int*)(base + KIND_COUNT_RVA), kind;
    u64 heap = *(u64*)(base + HEAP_BYTES_RVA), size;
    u64 page_bound = heap / 4096;
    state->last_pending_pages = 0;
    if (kinds < 1 || kinds > 16 || !page_bound || (heap & 4095) || heap >= MAX_BYTES) {
        reject_chain(state, kinds, 0, 8);
        return;
    }
    state->sort_runs++;
    /* Each (kind,size) chain is its own validation/commit unit. The registered
     * object heap bounds its page count, including cold reserved sections.
     * This is not a larger fixed cap: no valid chain can contain more pages than
     * the heap itself. Invalid/cyclic chains retain their native order and do
     * not deny service to other kinds or sizes. No scratch allocation is used.
     */
    for (kind = 0; kind < kinds; ++kind) {
        u64* pending = *(u64**)(base + KIND_TABLE_RVA + 32 * kind + 8);
        /* Native IS_UNCOLLECTABLE uses (kind & ~1) == 2. Its permanently marked
         * padding bits are not an occupancy measure; retain those chains.
         */
        if ((kind & ~1) == 2) continue;
        if (!pending) continue;
        for (size = 1; size <= 256; ++size) {
            u64 block = pending[size], old = block, count = 0, reason = 0;
            u64 joined = 0, minimum = 8, maximum = 0;
            volatile u64 heads[8];
            volatile u64 tails[8];
            int band;
            if (!block) continue;
            state->chain_scans++;
            while (block) {
                FreeHeader* h;
                u64 marks, density;
                if (count >= page_bound) { reason = 1; break; }
                if (block & 4095) { reason = 2; break; }
                h = find(block);
                if ((u64)h <= 4096) { reason = 3; break; }
                if (h->bytes != size) { reason = 4; break; }
                if (h->kind != kind) { reason = 5; break; }
                if (h->flags & 2) { reason = 6; break; }
                marks = marked(h);
                if (marks > 512 / size) { reason = 7; break; }
                density = marks * 8 / (512 / size);
                if (density > 7) density = 7;
                if (density < minimum) minimum = density;
                if (density > maximum) maximum = density;
                ++count;
                block = h->next;
            }
            state->chain_pages_validated += count;
            if (count > state->max_chain_pages) state->max_chain_pages = count;
            if (reason) { reject_chain(state, kind, size, reason); continue; }
            state->sort_pages += count;
            state->last_pending_pages += count;
            /* Uniform-density chains already satisfy the ordering contract. */
            if (minimum == maximum) { state->uniform_chains++; continue; }
            block = old;
            for (band = 0; band < 8; ++band) { heads[band] = 0; tails[band] = 0; }
            while (block) {
                FreeHeader* h = find(block);
                u64 next = h->next;
                band = (int)(marked(h) * 8 / (512 / size));
                if (band > 7) band = 7;
                h->next = 0;
                if (tails[band]) find(tails[band])->next = block;
                else heads[band] = block;
                tails[band] = block;
                block = next;
            }
            for (band = 0; band < 8; ++band) {
                if (heads[band]) { find(tails[band])->next = joined; joined = heads[band]; }
            }
            pending[size] = joined;
            state->sort_lists++;
            state->sort_changed_lists += joined != old;
        }
    }
}

/* This call site is followed immediately by take_prefix under the same original
 * allocator lock. Interior/blacklisted splits keep the original full remap.
 * No partially mapped header is ever published on a free list.
 */
__declspec(dllexport) void remember_remap(u64 block, u64 full, u64 need,
                                        u8* base, ReclaimState* state)
{
    Unmap remap = (Unmap)(base + REMAP_RVA);
    state->pending_block = state->pending_full = state->pending_bytes = 0;
    state->remap_calls++;
    state->remap_full_bytes += full;
    if (state->magic == MAGIC && *(u64*)(base + PAGE_SIZE_RVA) == 4096
        && need && need < full && !(need & 4095) && !(full & 4095)) {
        state->pending_block = block;
        state->pending_full = full;
        state->pending_bytes = need;
        return;
    }
    remap(block, full);
    state->remap_prefix_bytes += full;
}

__declspec(dllexport) u64 take_prefix(u64 block, FreeHeader* h, u64 need,
                                    int bucket, u8* base, ReclaimState* state)
{
    FirstPart original = (FirstPart)(base + FIRST_PART_RVA);
    Unmap remap = (Unmap)(base + REMAP_RVA);
    u64 pending = state->pending_block, full = state->pending_full;
    u64 pending_need = state->pending_bytes;
    state->pending_block = state->pending_full = state->pending_bytes = 0;
    if (pending) {
        FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
        if (pending == block && pending_need == need && h == find(block)
            && h->bytes == full && bucket >= 0 && bucket < BUCKETS) {
            FindHeader install = (FindHeader)(base + INSTALL_HEADER_RVA);
            /* Small allocation pages share a bounded 64-KiB committed prefix.
             * This is a remap quantum inside an existing OS reservation, not
             * a new heap section or a change to original expansion batches.
             * Large requests retain exact-prefix remapping.
             */
            u64 warm = need < WARM_QUANTUM ?
                (full < WARM_QUANTUM ? full : WARM_QUANTUM) : need;
            FreeHeader* rest = install(block + need);
            FreeHeader* cold = 0;
            if (rest && warm > need && warm < full) {
                cold = install(block + warm);
                if (!cold) {
                    RemoveHeader remove_header = (RemoveHeader)(base + REMOVE_HEADER_RVA);
                    remove_header(block + need);
                    rest = 0;
                }
            }
            if (rest) {
                RemoveFree remove = (RemoveFree)(base + REMOVE_FREE_RVA);
                AddFree add = (AddFree)(base + ADD_FREE_RVA);
                remove(h, bucket);
                remap(block, warm);
                rest->bytes = warm > need ? warm - need : full - need;
                rest->flags = warm > need ? 0 : 2;
                add(block + need, rest);
                if (cold) {
                    cold->bytes = full - warm;
                    cold->flags = 2;
                    add(block + warm, cold);
                }
                if (warm > need) {
                    state->warm_batches++;
                    state->warm_bytes += warm;
                    state->warm_extra_bytes += warm - need;
                }
                state->remap_prefix_bytes += warm;
                state->remap_avoided_bytes += full - warm;
                state->split_prefixes++;
                return block;
            }
        } else state->rejected++;
        /* Header allocation failed: preserve the original full-remap/error
         * path. No list mutation occurred before that allocation succeeded.
         */
        remap(pending, full);
        state->remap_prefix_bytes += full;
    }
    return original(block, h, need, bucket);
}

/* Preserve both original expansion batches exactly. The section table is finite
 * and its entries survive decommit and free-span coalescing. Shrinking batches
 * according to total free bytes was wrong: fragmented free spans may not satisfy
 * the request, causing thousands of tiny permanent section registrations.
 * This adapter now only counts the original arguments; it changes no decision.
 */
__declspec(dllexport) int grow_on_demand(u64 requested, u64 required,
                                      u8* base, ReclaimState* state)
{
    Expand expand = (Expand)(base + EXPAND_RVA);
    (void)required;
    state->growth_calls++;
    state->growth_original_blocks += requested;
    state->growth_actual_blocks += requested;
    return expand(requested);
}

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
    u64 unmapped_at_entry = *(u64*)(base + UNMAPPED_RVA);
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

    order_reclaim(base, state);

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
    /* Sweep already detached empty pages. Merge their mapped/unmapped spans
     * before budgeting retirement, using the original metadata and VM routines.
     */
    {
        NoArgs merge = (NoArgs)(base + MERGE_RVA);
        u64 before = count, after = 0;
        merge();
        state->merge_calls++;
        count = committed = 0;
        for (bucket = BUCKETS - 1; bucket >= 0; --bucket) {
            u64 block = lists[bucket];
            while (block) {
                FreeHeader* h = find_header(block);
                ++after;
                if (!(h->flags & 2)) committed += pages(block, h->bytes, page_size);
                block = h->next;
            }
        }
        count = after;
        state->merged_blocks += before - after;
    }
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
    /* Original mixed-state merging can remap an adjacent unmapped span. Report
     * the positive net return across the whole callback, not gross retirement
     * after merge; decommitted_bytes remains the policy's gross unmap counter.
     */
    {
        u64 after = *(u64*)(base + UNMAPPED_RVA);
        state->last_returned = after > unmapped_at_entry ? after - unmapped_at_entry : 0;
    }
    state->whole_free_committed_after = committed;
}
