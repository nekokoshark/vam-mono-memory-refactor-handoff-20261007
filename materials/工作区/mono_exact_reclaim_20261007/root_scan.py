"""Read the isolated process registered static-root words and original large header."""
from __future__ import annotations
import ctypes as C, json, sys, runpy, struct, time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main() -> None:
    pid,base,hidden=map(int,sys.argv[1:4]); target=(~hidden)&((1<<64)-1)
    core=runpy.run_path(str(HERE.parent/"mono_unmap_20260930/MODIFIED_FILE.py"))
    r=core["WindowsReader"](pid); reads=0; total=0
    def read(a,n):
        nonlocal reads,total
        reads+=1;total+=n
        if total>128*1024**2:raise RuntimeError("root metadata budget exceeded")
        return r.read(a,n)
    def word(a):return int.from_bytes(read(a,8),"little")
    try:
        # Actual add-roots IL: count @269c9c; 32B entries @299ac8.
        count=int.from_bytes(read(base+0x269c9c,4),"little");assert 0<count<=4096
        roots=read(base+0x299ac8,count*32)
        matches=[]; started=time.perf_counter()
        for slot in range(count):
            start,end,link,flag=struct.unpack_from("<4Q",roots,slot*32)
            assert start<=end and end-start<128*1024**2
            for offset in range(0,end-start,65536):
                data=read(start+offset,min(65536,end-start-offset))
                for off in range(0,len(data)-7,8):
                    value=struct.unpack_from("<Q",data,off)[0]
                    if target<=value<target+805306400:
                        matches.append(dict(rootIndex=slot,rootStartHidden=(~start)&((1<<64)-1),
                            fieldOffset=offset+off,targetOffset=value-target,wordHidden=(~value)&((1<<64)-1)))
        # Native original header index, not an injected find function.
        block=target&~4095;key=block>>22;node=word(base+0x2bdcd0+(key&2047)*8);zero=word(base+0x2bdcc8)
        for _ in range(4096):
            nodekey,nextnode=struct.unpack("<QQ",read(node+0x2010,16))
            if nodekey==key or node==zero:break
            node=nextnode
        else:raise RuntimeError("header index loop")
        h=word(node+((block>>12)&1023)*8);raw=read(h,112)
        header=dict(bytes=struct.unpack_from("<Q",raw)[0],kind=raw[40],flags=raw[41],
            marks=[hex(v) for v in struct.unpack_from("<8Q",raw,48)])
        assert roots==read(base+0x299ac8,count*32)
        result=dict(pid=pid,rootCount=count,staticMatches=matches,largeHeader=header,reads=reads,
            bytesRead=total,elapsedSeconds=time.perf_counter()-started,targetAddressHidden=hidden,
            limitations="Static registered roots only; thread stacks and exclusions still require audit; matches alone are not proof of marking.")
        path=HERE/(sys.argv[4]+"_ROOT_SCAN.json");path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        print("ROOT_SCAN_PASS staticMatches="+str(len(matches))+" rootCount="+str(count)+" bytesRead="+str(total))
    finally:r.close()
if __name__=="__main__":main()
