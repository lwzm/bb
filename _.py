#!/usr/bin/env python3

if __name__ == "__main__":
    import collections
    import gc
    import itertools
    import os
    import time
    import urllib.parse
    import urllib.request

    from tornado.options import define, options, parse_command_line

    from bb import const
    from bb import opt
    from bb.web import main

    gc.disable()

    for k in dir(opt):
        if k[0].isalpha():
            v = getattr(opt, k)
            if isinstance(v, list):
                define(k, default=v, type=type(v[0]), multiple=True)
            else:
                define(k, default=v, type=type(v))

    parse_command_line()

    args = {
        "start": time.strftime("%y%m%d-%H%M%S"),
        "port": options.port,
        "backstage": options.backstage,
    }
    args = urllib.parse.urlencode(args)

    def to_leader(key):
        if False and not options.debug:  # disable this
            url = "http://%s/%s?%s" % (options.leader, key, args)
            with urllib.request.urlopen(url) as f:
                s = f.read().decode()
                if s:
                    from json import loads
                    for k, v in loads(s).items():
                        print(k, v)
                        setattr(const, k, v)

    to_leader("reg")

    pid = "bb.pid"
    with open(pid, "w") as f: f.write(str(os.getpid()))

    main(options)

    if os.path.exists(pid): os.remove(pid)

    to_leader("quit")
