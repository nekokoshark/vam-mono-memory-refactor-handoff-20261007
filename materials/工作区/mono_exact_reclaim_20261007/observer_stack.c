/* Isolation-only observer bridge; never injected into the game or candidate. */
typedef unsigned long long u64;
typedef void (*Collect)(int);
__declspec(noinline) static u64 descend(Collect collect, int gen, unsigned depth)
{
    volatile u64 scratch[256];
    unsigned i;
    for (i=0;i<256;++i) scratch[i]=0;
    if (depth) scratch[0]=descend(collect,gen,depth-1);
    else collect(gen);
    return scratch[0];
}
__declspec(dllexport) void observe_collect(Collect collect, int gen)
{
    (void)descend(collect,gen,32);
}
