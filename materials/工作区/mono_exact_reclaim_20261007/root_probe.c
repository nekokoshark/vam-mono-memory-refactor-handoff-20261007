/* Private-runtime diagnostic only. No live game hooks. */
typedef unsigned long long u64;
typedef void (*FieldGet)(void*,void*,void*);
typedef unsigned (*WeakNew)(void*,int);
typedef void* (*WeakGet)(unsigned);
static u64 hidden;
static unsigned handle;
__declspec(dllexport) u64 track(void* base,void* table,void* field)
{
    void* volatile object=0;
    ((FieldGet)((char*)base+0x7b998))(table,field,(void*)&object);
    hidden=~(u64)object;
    handle=((WeakNew)((char*)base+0x37cf8))((void*)object,0);
    object=0;
    return hidden;
}
__declspec(dllexport) unsigned check(void* base,void* table,void* field)
{
    void* volatile object=0;
    unsigned result;
    ((FieldGet)((char*)base+0x7b998))(table,field,(void*)&object);
    result=object ? 2 : 0;
    object=((WeakGet)((char*)base+0x37d58))(handle);
    result|=object ? 1 : 0;
    object=0;
    return result;
}

typedef void (*Push)(u64,u64);
static u64 runtime_base;
static u64 report_words[261];
static u64 scan_epoch;
__declspec(dllexport) void configure(u64 base)
{
    unsigned i;
    runtime_base=base;
    scan_epoch=~0ULL;
    for(i=0;i<261;++i)report_words[i]=0;
}
__declspec(dllexport) void record_push(u64 start,u64 end)
{
    u64 address, target=~hidden, tid=0, i;
    int max=*(int*)(runtime_base+0x269c6c);
    u64 epoch=*(u64*)(runtime_base+0x269b90);
    if(epoch!=scan_epoch){
        scan_epoch=epoch;
        for(i=0;i<261;++i)report_words[i]=0;
    }
    report_words[0]++;
    for(i=0;i<=(u64)max && i<2048;++i){
        char* entry=(char*)(runtime_base+0x26c780+32*i);
        if(*(u64*)(entry+16)==end){tid=*(unsigned*)(entry+4);break;}
    }
    if(end>=start && end-start<16ULL*1024*1024){
        report_words[1]+=end-start;
        for(address=start;address+8<=end;address+=8){
            u64 value=*(volatile u64*)address;
            if(value>=target && value-target<805306400ULL){
                u64 n=report_words[2]++;
                if(n<64){
                    report_words[5+4*n]=tid;
                    report_words[6+4*n]=~address;
                    report_words[7+4*n]=value-target;
                    report_words[8+4*n]=~start;
                }
            }
        }
    }else report_words[3]++;
    ((Push)(runtime_base+0x15b240))(start,end);
}
__declspec(dllexport) void report(u64* out)
{
    unsigned i;
    for(i=0;i<261;++i)out[i]=report_words[i];
}

typedef void (*CollectFn)(int);
__declspec(dllexport) void collect_with_stack_root(void* base,int generation)
{
    volatile u64 root=~hidden;
    ((CollectFn)((char*)base+0x1b2c4))(generation);
    /* Keep the input live through the original GC, then end this test root. */
    if(root)root=0;
}
