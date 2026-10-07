/* Linked allocation/reclamation policies for the audited Unity Mono ABI.
 * Original marking, object layout, maximum heap, locks and OS allocator remain.
 * Seven original callsites enter these policies under the original allocator lock.
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
    u64 merge_mixed_pairs;
    u64 merge_budget_vetoes;
    u64 merge_remap_bytes;
    u64 merge_decommit_bytes;
    u64 merge_avoided_remap_bytes;
    u64 merge_header_rejects;
    u64 last_merge_committed_before;
    u64 last_merge_committed_after;
    u64 interior_split_calls;
    u64 interior_cold_splits;
    u64 interior_full_bytes;
    u64 interior_deferred_bytes;
    u64 interior_fallbacks;
    u64 warm_lookup_calls;
    u64 warm_lookup_hits;
    u64 warm_lookup_stale;
    u64 warm_lookup_misses;
    u64 warm_lookup_native_fallbacks;
    u64 warm_seed_scans;
    /* Non-owning GC-hidden addresses: hints must not pin a later allocation. */
    u64 warm_hints[32];
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
#define UNMAP_GAP_RVA 0x15ed10
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

/* A hint is not a second free list or an owner. Original header/links,
 * VM flags and the allocator lock are authoritative on every use. All hint
 * slots use complemented addresses, as conservative-GC hidden pointers do.
 */
static void remember_warm(u8* base, ReclaimState* state, u64 block)
{
    FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
    FreeHeader* h;
    u64 count;
    if (!block || (block & 4095)) return;
    h = find(block);
    if ((u64)h <= 4096 || h->free_marker != *(u64*)(base + FREE_MARKER_RVA)
        || (h->flags & 2) || !h->bytes || (h->bytes & 4095)) return;
    count = h->bytes / 4096;
    if (count <= 32) state->warm_hints[count - 1] = ~block;
}

/* GC_new_hblk already executes after original lazy reclaim failed and under
 * the original allocator lock. Try one non-owning hint per exact-size bucket,
 * not a heap scan. The original nth allocator still performs ALL blacklist,
 * collection-pressure, splitting, map/header and free-byte operations.
 */
__declspec(dllexport) u64 reuse_small(u64 size, int kind, unsigned flags,
                                    u8* base, ReclaimState* state)
{
    typedef u64 (*Allocate)(u64, int, unsigned);
    typedef u64 (*AllocateNth)(u64, int, u8, int);
    typedef u64 (*Blacklisted)(u64, u64);
    Allocate original = (Allocate)(base + 0x16060c);
    AllocateNth nth = (AllocateNth)(base + 0x160004);
    Blacklisted blacklisted = (Blacklisted)(base + 0x1618ac);
    FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
    RemoveFree remove = (RemoveFree)(base + REMOVE_FREE_RVA);
    AddFree add = (AddFree)(base + ADD_FREE_RVA);
    u64* lists = (u64*)(base + FREE_LIST_RVA);
    int bucket;
    if (state->magic != MAGIC || *(u64*)(base + PAGE_SIZE_RVA) != 4096
        || !size || size > 256 || flags || kind < 0
        || kind >= *(int*)(base + KIND_COUNT_RVA) || (kind & ~1) == 2)
        return original(size, kind, flags);
    state->warm_lookup_calls++;
    for (bucket = 1; bucket <= 32; ++bucket) {
        u64 hidden = state->warm_hints[bucket - 1], block, bytes, result;
        FreeHeader* h;
        if (!hidden) continue;
        /* Clear before any native allocation can repurpose this address. */
        state->warm_hints[bucket - 1] = 0;
        block = ~hidden;
        h = find(block);
        if ((u64)h <= 4096 || (block & 4095)
            || h->free_marker != *(u64*)(base + FREE_MARKER_RVA)
            || (h->flags & 2) || h->bytes != (u64)bucket * 4096) {
            state->warm_lookup_stale++;
            continue;
        }
        /* A matching size/marker alone does not prove current membership. */
        if ((h->previous ? ((u64)find(h->previous) <= 4096
                || find(h->previous)->next != block) : lists[bucket] != block)
            || (h->next && ((u64)find(h->next) <= 4096
                || find(h->next)->previous != block))) {
            state->warm_lookup_stale++;
            continue;
        }
        bytes = h->bytes;
        /* A one-page normal hint has no possible interior fallback. Retain the
         * native blacklist decision, and do not let this hint divert a usable
         * larger warm hint into a cold allocation in the same one-page bin.
         */
        if (kind != 0 && bucket == 1 && blacklisted(block, 4096)) continue;
        if (lists[bucket] != block) {
            remove(h, bucket);
            add(block, h);
        }
        result = nth(size, kind, (u8)flags, bucket);
        if (result) {
            if (result >= block && result - block <= bytes - 4096)
                state->warm_lookup_hits++;
            else state->warm_lookup_native_fallbacks++;
            /* An original interior split can leave a valid warm leading part. */
            remember_warm(base, state, block);
            remember_warm(base, state, result + 4096);
            return result;
        }
    }
    state->warm_lookup_misses++;
    return original(size, kind, flags);
}

/* At most 8192 header visits at the completed retirement boundary. Failure to
 * find a hint only leaves the original allocation path; it grants no release.
 */
static void seed_warm(u8* base, ReclaimState* state)
{
    u64* lists = (u64*)(base + FREE_LIST_RVA);
    FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
    int bucket;
    for (bucket = 1; bucket <= 32; ++bucket) {
        u64 block = lists[bucket], visited = 0;
        state->warm_hints[bucket - 1] = 0;
        while (block && visited++ < 256) {
            FreeHeader* h = find(block);
            state->warm_seed_scans++;
            if ((u64)h <= 4096) break;
            if (!(h->flags & 2)) {
                remember_warm(base, state, block);
                break;
            }
            block = h->next;
        }
    }
}

/* This call site is followed immediately by take_prefix under the same original
 * allocator lock. Interior splits first preserve both cold headers, then use
 * this same demand-remap transaction. No unlocked partial state is exposed.
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
                remember_warm(base, state, block + need);
                return block;
            }
        } else state->rejected++;
        /* Header allocation failed: preserve the original full-remap/error
         * path. No list mutation occurred before that allocation succeeded.
         */
        remap(pending, full);
        state->remap_prefix_bytes += full;
    }
    {
        u64 result = original(block, h, need, bucket);
        if (result) remember_warm(base, state, result + need);
        return result;
    }
}

/* Only the original allocator's accepted interior split enters this adapter.
 * Its preceding full-remap/flag-clear pair is removed at that exact callsite.
 * SplitBlock is metadata-only: preserve its list/map/age operations once, keep
 * both resulting spans cold, then let the common remember/take path commit the
 * actual accepted interval. The original allocator lock covers the transaction.
 * Unknown state takes the native full-remap + flag-clear + split path.
 */
__declspec(dllexport) void split_cold_extent(u64 block, FreeHeader* left,
        u64 cut, FreeHeader* right, int bucket, u8* base, ReclaimState* state)
{
    typedef void (*SplitBlock)(u64, FreeHeader*, u64, FreeHeader*, int);
    SplitBlock original = (SplitBlock)(base + 0x15ff50);
    int cold = (left->flags & 2) != 0;
    state->interior_split_calls++;
    if (cold) {
        FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
        u64 full = left->bytes;
        u64 lead = cut - block;
        int admitted = state->magic == MAGIC
            && *(u64*)(base + PAGE_SIZE_RVA) == 4096
            && bucket >= 0 && bucket < BUCKETS && left != right
            && !(block & 4095) && !(cut & 4095)
            && full && !(full & 4095) && full < MAX_BYTES
            && cut > block && lead < full && block + full > block
            && left == find(block) && right == find(cut)
            && left->free_marker == *(u64*)(base + FREE_MARKER_RVA);
        if (admitted) {
            original(block, left, cut, right, bucket);
            /* Native SplitBlock initializes right->flags to zero. Restore only
             * its cold bit; leave all other original header fields untouched.
             * Left's original cold bit survived the metadata split unchanged.
             */
            right->flags |= 2;
            state->interior_cold_splits++;
            state->interior_full_bytes += full;
            state->interior_deferred_bytes += lead;
            return;
        }
        {
            Unmap remap = (Unmap)(base + REMAP_RVA);
            remap(block, full);
            left->flags &= (u8)~2;
            state->interior_fallbacks++;
        }
    }
    original(block, left, cut, right, bucket);
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

/* Coalescing storage is one budgeted transaction, not a size-based remap
 * followed by a separate retirement. Keep native list traversal/order, header
 * removal, map invalidation, and VM bookkeeping; only veto a native remap that
 * would make committed whole-free storage exceed the existing reserve.
 */
__declspec(noinline) static u64 merge_with_budget(u8* base, ReclaimState* state,
                                                u64 committed, u64 marker)
{
    u64* lists = (u64*)(base + FREE_LIST_RVA);
    FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
    RemoveFree remove = (RemoveFree)(base + REMOVE_FREE_RVA);
    RemoveHeader remove_header = (RemoveHeader)(base + REMOVE_HEADER_RVA);
    AddFree add = (AddFree)(base + ADD_FREE_RVA);
    Unmap unmap = (Unmap)(base + UNMAP_RVA);
    Unmap remap = (Unmap)(base + REMAP_RVA);
    typedef void (*UnmapGap)(u64, u64, u64, u64);
    UnmapGap gap = (UnmapGap)(base + UNMAP_GAP_RVA);
    int bucket;
    state->last_merge_committed_before = committed;
    for (bucket = 0; bucket < BUCKETS; ++bucket) {
        u64 block = lists[bucket];
        while (block) {
            FreeHeader* left = find(block);
            u64 successor = block + left->bytes;
            FreeHeader* right = find(successor);
            int left_cold, right_cold;
            if ((u64)right <= 4096 || right->free_marker != marker) {
                block = left->next;
                continue;
            }
            if (!valid(right, marker, successor) || left->bytes + right->bytes >= MAX_BYTES
                || successor + right->bytes <= successor) {
                state->merge_header_rejects++;
                block = left->next;
                continue;
            }
            left_cold = (left->flags & 2) != 0;
            right_cold = (right->flags & 2) != 0;
            if (left_cold && right_cold) {
                gap(block, left->bytes, successor, right->bytes);
            } else if (left_cold != right_cold) {
                u64 cold_bytes = left_cold ? left->bytes : right->bytes;
                u64 warm_bytes = left_cold ? right->bytes : left->bytes;
                u64 cold_block = left_cold ? block : successor;
                u64 warm_block = left_cold ? successor : block;
                int native_warm = left_cold ? left->bytes <= right->bytes
                                           : left->bytes > right->bytes;
                int keep_warm = native_warm && committed <= state->reserve_bytes
                    && cold_bytes <= state->reserve_bytes - committed;
                u64 before = *(u64*)(base + UNMAPPED_RVA);
                state->merge_mixed_pairs++;
                if (keep_warm) {
                    remap(cold_block, cold_bytes);
                    state->merge_remap_bytes += before - *(u64*)(base + UNMAPPED_RVA);
                    committed += cold_bytes;
                    left->flags &= (u8)~2;
                    if (left_cold) left->reclaimed = right->reclaimed;
                } else {
                    unmap(warm_block, warm_bytes);
                    state->merge_decommit_bytes += *(u64*)(base + UNMAPPED_RVA) - before;
                    committed -= warm_bytes;
                    left->flags |= 2;
                    if (native_warm) {
                        state->merge_budget_vetoes++;
                        state->merge_avoided_remap_bytes += cold_bytes;
                    }
                }
            }
            /* Both warm: freehblk normally already coalesces them. No VM state
             * transition is needed if a valid pair reaches this inventory.
             */
            remove(left, bucket);
            remove(right, -1);
            left->bytes += right->bytes;
            remove_header(successor);
            add(block, left);
            state->merged_blocks++;
            /* Match native ascending bucket traversal and restart after merge. */
            block = lists[bucket];
        }
    }
    state->last_merge_committed_after = committed;
    return committed;
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
    /* All free headers were checked before mutation. At the audited 4-KiB
     * granularity, mapped/cold boundaries coincide with actual OS pages.
     * Other page sizes retain the original native coalescer and its gap logic.
     */
    if (page_size == 4096) {
        u64 merged_before = state->merged_blocks;
        committed = merge_with_budget(base, state, committed, marker);
        count -= state->merged_blocks - merged_before;
        state->merge_calls++;
    } else {
        NoArgs merge = (NoArgs)(base + MERGE_RVA);
        u64 before = count;
        merge();
        state->merge_calls++;
        count = committed = 0;
        for (bucket = BUCKETS - 1; bucket >= 0; --bucket) {
            u64 block = lists[bucket];
            while (block) {
                FreeHeader* h = find_header(block);
                count++;
                if (!(h->flags & 2)) committed += pages(block, h->bytes, page_size);
                block = h->next;
            }
        }
        state->merged_blocks += before - count;
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
    seed_warm(base, state);
}
