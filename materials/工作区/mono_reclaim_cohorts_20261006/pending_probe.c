/* Fixed-size, read-only inventory of an isolated runtime's real pending chains.
 * The harness joins managed workers and invokes no Mono allocation during probe.
 */
#include "../mono_warm_pages_20261006/reclaim_controller.c"

typedef struct ChainReport {
    u64 kind, size, head, pages, inversions, invalid, reason, bad_block;
    u64 bands[8];
} ChainReport;

typedef struct ProbeReport {
    u64 kinds, chains, pages, invalid, global_limit_exceeded;
    ChainReport chain[4096];
} ProbeReport;

__declspec(dllexport) void pending_probe(u8* base, ProbeReport* out)
{
    FindHeader find = (FindHeader)(base + FIND_HEADER_RVA);
    int kinds = *(int*)(base + KIND_COUNT_RVA), kind;
    u64 size;
    out->kinds = kinds;
    out->chains = out->pages = out->invalid = out->global_limit_exceeded = 0;
    if (kinds < 1 || kinds > 16) { out->invalid = 1; return; }
    for (kind = 0; kind < kinds; ++kind) {
        u64* pending = *(u64**)(base + KIND_TABLE_RVA + 32 * kind + 8);
        if ((kind & ~1) == 2 || !pending) continue;
        for (size = 1; size <= 256; ++size) {
            u64 block = pending[size], previous = 8, i;
            ChainReport* r;
            if (!block) continue;
            r = &out->chain[out->chains++];
            r->kind = kind; r->size = size; r->head = block;
            r->pages = r->inversions = r->invalid = r->reason = r->bad_block = 0;
            for (i = 0; i < 8; ++i) r->bands[i] = 0;
            while (block) {
                FreeHeader* h;
                u64 marks, band, reason = 0;
                if (r->pages >= 2097152) { reason = 1; h = 0; }
                else if (block & 4095) { reason = 2; h = 0; }
                else {
                    h = find(block);
                    if ((u64)h <= 4096) reason = 3;
                    else if (h->bytes != size) reason = 4;
                    else if (h->kind != kind) reason = 5;
                    else if (h->flags & 2) reason = 6;
                    else if (marked(h) > 512 / size) reason = 7;
                }
                if (reason) {
                    r->invalid = 1; r->reason = reason; r->bad_block = block;
                    out->invalid++; break;
                }
                marks = marked(h);
                band = marks * 8 / (512 / size);
                if (band > 7) band = 7;
                r->inversions += band > previous;
                r->bands[band]++; previous = band;
                r->pages++; out->pages++;
                block = h->next;
            }
        }
    }
    out->global_limit_exceeded = out->pages > MAX_BLOCKS;
}
