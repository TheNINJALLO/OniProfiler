"""Bounded Spark native protobuf summary reader, matched to pinned EndstoneMC/spark.

Only documented emitted fields are interpreted. It does not execute profile content,
load native modules, infer exact per-entity cost, or resolve unknown native symbols.
"""
from __future__ import annotations
from collections import defaultdict
import math
from pathlib import Path
import re
import struct
from typing import Iterator, Any
import zlib

MAX_BYTES=64*1024*1024
MAX_NODES=100000
PROFILE_NAME=re.compile(r"(?<![A-Za-z0-9_.-])(profile-[0-9]+(?:-[0-9]+)?\.sparkprofile)(?![A-Za-z0-9_.-])")

def profile_filename(message: str) -> str | None:
    # Upstream's export receipt is human-readable, not a bare path. Only its known
    # generated basename is accepted; arbitrary paths and URL targets are never used.
    names=set(PROFILE_NAME.findall(message))
    return next(iter(names)) if len(names)==1 else None

def varint(data: bytes, offset: int=0) -> tuple[int,int]:
    result=0
    for shift in range(0,70,7):
        if offset>=len(data):
            raise ValueError("Truncated protobuf varint")
        value=data[offset];offset+=1
        if shift==63 and value>1:
            raise ValueError("Protobuf integer overflow")
        result|=(value&127)<<shift
        if value<128:
            return result,offset
    raise ValueError("Invalid protobuf integer")

def fields(data: bytes) -> Iterator[tuple[int,int,Any]]:
    offset=0;count=0
    while offset<len(data):
        count+=1
        if count>1000000:
            raise ValueError("Too many protobuf fields")
        tag,offset=varint(data,offset);number,wire=tag>>3,tag&7
        if number==0:
            raise ValueError("Invalid protobuf field zero")
        if wire==0:
            value,offset=varint(data,offset)
        elif wire in (1,5):
            size=8 if wire==1 else 4
            if offset+size>len(data):
                raise ValueError("Truncated fixed-width field")
            value=data[offset:offset+size];offset+=size
        elif wire==2:
            size,offset=varint(data,offset)
            if size>MAX_BYTES or offset+size>len(data):
                raise ValueError("Invalid protobuf field length")
            value=data[offset:offset+size];offset+=size
        else:
            raise ValueError("Unsupported protobuf wire type")
        yield number,wire,value

def text(value: bytes) -> str:
    if len(value)>16384:
        raise ValueError("Native symbol label is too long")
    return value.decode("utf-8",errors="replace")

def weights(value: bytes) -> float:
    if len(value)%8:
        raise ValueError("Malformed packed sample weights")
    total=0.0
    for (v,) in struct.iter_unpack("<d",value):
        if not math.isfinite(v) or v<0:
            raise ValueError("Native profile has invalid sample weights")
        total+=v
    if not math.isfinite(total):
        raise ValueError("Native sample-weight overflow")
    return total

def indexes(value: bytes) -> list[int]:
    values=[];offset=0
    while offset<len(value):
        item,offset=varint(value,offset)
        if item>=MAX_NODES or len(values)>=MAX_NODES:
            raise ValueError("Native call-tree reference is too large")
        values.append(item)
    return values

def category(label: str) -> str:
    name=label.lower()
    for label,terms in (
        ("Pathfinding",("pathfinder","pathfinding","navigation::","path::")),
        ("Chunk and terrain work",("worldgenerator","chunkgeneration","chunkgenerator","levelchunk","biomesource","worldgen")),
        ("Redstone and hoppers",("redstone","hopper","piston","comparator","circuit")),
        ("Entity-related work",("mob::","actor::","entity::","entitytick","entitycontext")),
        ("Storage and compression",("leveldb","dbimpl::","deflate","inflate","savechunk","writetofile")),
        ("Networking",("raknet","networkhandler","sendpacket","networksystem")),
    ):
        if any(term in name for term in terms):
            return label
    return "Other or unidentified work"

def analyze_bytes(data: bytes) -> dict[str,Any]:
    if len(data)>MAX_BYTES:
        raise ValueError("Native profile exceeds the 64 MiB analysis cap")
    if data.startswith(b"\x1f\x8b"):
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
        try:
            raw=decoder.decompress(data,MAX_BYTES+1)
        except zlib.error as error:
            raise ValueError("Invalid compressed native profile") from error
        if len(raw)>MAX_BYTES or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
            raise ValueError("Compressed profile is oversized, truncated, or concatenated")
        data=raw
    metadata=None;thread_data=[];sources={}
    for number,wire,value in fields(data):
        if number==1 and wire==2:
            if metadata is not None:
                raise ValueError("Duplicate native metadata")
            metadata=value
        elif number==2 and wire==2:
            if len(thread_data)>=128:
                raise ValueError("Native profile exceeds the thread-analysis cap")
            thread_data.append(value)
        elif number==3 and wire==2:
            entry={n:text(v) for n,w,v in fields(value) if n in (1,2) and w==2}
            if 1 in entry and 2 in entry:
                sources[entry[1]]=entry[2]
    if metadata is None or not thread_data:
        raise ValueError("This file does not contain a supported native sampler recording")
    meta={n:v for n,w,v in fields(metadata) if w==0 and n in (2,3,11,12,15)}
    mode=meta.get(15,0)
    if mode not in (0,1):
        raise ValueError("Unsupported native recording mode")
    unit="sampled execution weight (ms)" if mode==0 else "sampled allocation weight (bytes)"
    result={"available":True,"format":"EndstoneMC/spark 8958173 native SamplerData",
            "mode":"execution" if mode==0 else "allocation","unit":unit,
            "started_ms":meta.get(2),"ended_ms":meta.get(11),"interval":meta.get(3),"threads":[],
            "limitations":["Percentages use one selected thread's sampled weight, not total host CPU.",
                            "Category labels are keyword-based indications, not confirmed causes.",
                            "Native labels may be resolved, guessed or unresolved. This reader does not independently verify them.",
                            "Module attribution covers available native mappings, not complete Python or JavaScript callback costs."]}
    total_nodes=0
    for packed_thread in thread_data:
        name="Unnamed thread";nodes=[];roots=[];total=None
        for number,wire,value in fields(packed_thread):
            if number==1 and wire==2:
                name=text(value)
            elif number==4 and wire==2:
                total=weights(value)
            elif number==5 and wire==2:
                roots=indexes(value)
            elif number==3 and wire==2:
                total_nodes+=1
                if total_nodes>MAX_NODES:
                    raise ValueError("Native call tree exceeds the node-analysis cap")
                node={"class":"","method":"","descriptor":"","inclusive":0.0,"children":[]}
                for n,w,v in fields(value):
                    if w==2 and n in (3,4,7):
                        node[{3:"class",4:"method",7:"descriptor"}[n]]=text(v)
                    elif n==8 and w==2:
                        node["inclusive"]=weights(v)
                    elif n==9 and w==2:
                        node["children"]=indexes(v)
                if any(child>=len(nodes) for child in node["children"]):
                    raise ValueError("Invalid or cyclic native call-tree references")
                nodes.append(node)
        if total is None or any(root>=len(nodes) for root in roots):
            raise ValueError("Native thread has missing weights or invalid roots")
        parents=[0]*len(nodes)
        for node in nodes:
            for child in node["children"]:
                parents[child]+=1
                if parents[child]>1:
                    raise ValueError("Native node has multiple parents")
        if len(roots)!=len(set(roots)) or set(roots)!={i for i,count in enumerate(parents) if count==0}:
            raise ValueError("Native call-tree roots do not match the flattened tree")
        root_weight=sum(nodes[index]["inclusive"] for index in roots)
        tolerance=max(1e-6,total*1e-8)
        if root_weight>total+tolerance:
            raise ValueError("Native root weight exceeds its thread total")
        frames={};categories=defaultdict(float);plugins=defaultdict(float)
        for node in nodes:
            children=sum(nodes[index]["inclusive"] for index in node["children"])
            if children>node["inclusive"]+tolerance:
                raise ValueError("Native child weights exceed their parent")
            own=max(0.0,node["inclusive"]-children)
            label=(node["class"]+"::"+node["method"]).strip(":") or "Unresolved frame"
            key=(label,node["descriptor"])
            row=frames.setdefault(key,{"symbol":label,"descriptor":node["descriptor"],"self_weight":0.0,"inclusive_weight":0.0})
            row["self_weight"]+=own;row["inclusive_weight"]+=node["inclusive"]
            categories[category(label)]+=own
            plugins[sources.get(node["class"],"Unattributed native module")]+=own
        unframed=max(0.0,total-root_weight)
        categories["Other or unidentified work"]+=unframed
        plugins["Unattributed native module"]+=unframed
        top=sorted(frames.values(),key=lambda n:n["self_weight"],reverse=True)[:40]
        for row in top:
            row["self_percent"]=row["self_weight"]*100/total if total else None
        def distribution(mapping):
            return [{"label":label,"weight":value,"percent":value*100/total if total else None,"evidence":"indicated"}
                    for label,value in sorted(mapping.items(),key=lambda pair:pair[1],reverse=True)[:24] if value>0]
        result["threads"].append({"name":name,"total_weight":total,"node_count":len(nodes),"top_frames":top,
                                  "categories":distribution(categories),"native_sources":distribution(plugins)})
    result["threads"].sort(key=lambda row:row["total_weight"],reverse=True)
    result["thread_count"]=len(result["threads"])
    result["threads"]=result["threads"][:16]
    result["limitations"].append("This summary retains up to 16 sampled threads, 40 self-weight frames and 24 category/source groups per thread; inspect the full native profile for complete detail.")
    return result

def analyze_file(path: Path) -> dict[str,Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise ValueError("Native profile file is unavailable or exceeds the analysis cap")
    with path.open("rb") as stream:
        return analyze_bytes(stream.read(MAX_BYTES+1))
