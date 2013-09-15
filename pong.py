#!/usr/bin/env python

from bb.inst import handle, run
from bb.i import P

@handle
def ping(i, n):
    i.send("pong", n)
    i.save("foo")
    return i.flush()

@handle
def pong(i, n):
    j = P[2]
    i.send("pong", n)
    j.send("pong", n)
    return i.flush(j)

@handle
def online(i, n):
    i.online = n

@run
def plus():
    for i in P.values():
        i["gold"] += 1
    return "plus"
