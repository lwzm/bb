#!/usr/bin/env python3
# This is bb server
"""
   /--->Q0--->\
Web            Hub --->Q2---> Log
   \<---Q1<---/

"""


def main(port, backstage, backdoor, debug, options):
    import gc
    gc.disable()

    import logging
    from multiprocessing import Process
    from multiprocessing.queues import Queue, SimpleQueue

    if debug:
        from threading import Thread as Process

    Q0, Q1, Q2 = Queue(), SimpleQueue(), SimpleQueue()

    import bb.hub
    import bb.log

    sub_procs = {}

    def start():
        logging.info("starting sub processes...")
        if any(proc.is_alive() for proc in sub_procs.values()):
            logging.warning("sub processes are running, failed to start")
            return
        sub_procs["hub"] = Process(target=bb.hub.hub, args=(Q0, Q1, Q2, options))
        sub_procs["log"] = Process(target=bb.log.log, args=(Q2, options))
        for name, proc in sub_procs.items():
            proc.start()
            logging.info("%s started, pid:%d", name, getattr(proc, "pid", 0))
        logging.info("start sub processes success!")

    def stop():
        logging.info("stopping sub processes...")
        if all(proc.is_alive() for proc in sub_procs.values()):
            Q0.put(None)
        else:
            logging.warning("sub processes are not running, failed to stop")
        for name, proc in sub_procs.items():
            proc.join()
            logging.info("%s stopped, pid:%d", name, getattr(proc, "pid", 0))
        logging.info("stop sub processes success!")

    start()

    # main from here
    import time
    import weakref
    from functools import partial

    staffs = weakref.WeakValueDictionary()
    wheels = weakref.WeakValueDictionary()

    from tornado import ioloop
    io_loop = ioloop.IOLoop.instance()

    tokens = {}


    # SIGTERM
    import signal
    def term(signal_number, stack_frame):
        logging.info("will exit")
        io_loop.stop()
        stop()
    signal.signal(signal.SIGTERM, term)


    commands = {
        "shell": lambda s: [i.write(s.encode()) for i in wheels.values()],
    }

    def msg(fd, event):
        x = Q1.get()
        logging.debug("msg from hub: %r", x)
        if len(x) == 2:
            cmd, data = x
            cb = commands.get(cmd) or (HC[cmd].popleft() if HC[cmd] else None)
            #print(cmd, data, cb)
            cb(data) if cb else None
        else:
            i, cmd, data = x
            s = staffs.get(i)
            if s:
                s.send(cmd, data)
            else:
                logging.warning("%s is not online, failed to send %s %s",
                                i, cmd, data)
    io_loop.add_handler(Q1._reader.fileno(), msg, io_loop.READ)


    from bb.oc import record, recorder
    from tornado.web import RequestHandler, Application, asynchronous

    ioloop.PeriodicCallback(record, 3000).start()
    ioloop.PeriodicCallback(lambda: tokens.update(
        {1: "token", 2: "token", 3: "token"}
        ), 2000).start()

    class BaseHandler(RequestHandler):
        def back(self):
            if self.request.host[0].isalpha():
                self.redirect("")
            else:
                self.finish()

        def get(self):
            """dummy"""

    import collections
    HC = collections.defaultdict(collections.deque)  # http commands


    class MainHandler(BaseHandler):
        commands = {
            "gc": lambda: gc.collect(),
            "HUB-RST": lambda: [gc.collect(), stop(), start()],
            "door-close": lambda: [i.close() for i in wheels.values()],
        }

        def get(self):
            self.render("index.html",
                        qsize=Q0.qsize(),
                        options=self.commands,
                        wheels=wheels,
                        staffs=staffs)

        def post(self):
            """example:
            wget -O - localhost:8100 --post-data="cmd=gc"
            """
            cmd = self.get_argument("cmd", None)
            if cmd:
                logging.info("main_commands: %s", cmd)
                self.commands[cmd]()
            self.back()


    class HubHandler(BaseHandler):
        commands = {
            "status": lambda d: StatusHandler.recorders["hub"].update(d),
            "gc": lambda n: logging.info("hub gc collect return: %d", n),
            "beginner": lambda i: logging.info("begin %d", i),
            "amend": lambda args: logging.info("amend %d %s %r %r", *args),
            "run": lambda f: logging.info("run %s succeed" % f),
            "view_data": lambda x: logging.info("%r " % x),
            "view_logs": lambda x: logging.info("%r " % x),
        }

        history = collections.deque(maxlen=3)

        def get(self):
            self.render("hub.html", options=self.commands, history=self.history)

        @asynchronous
        def post(self):
            """example:
            wget -O - localhost:8100/hub --post-data="cmd=gc"
            wget -O - localhost:8100/hub --post-data="cmd=status"
            wget -O - localhost:8100/hub --post-data="cmd=beginner&args=42"
            wget -O - localhost:8100/hub --post-data='cmd=amend&args=1&args=foobar&args={"1":1,"2":2}'
            wget -O - localhost:8100/hub --post-data="cmd=run&args=plus"
            """
            cmd = self.get_argument("cmd", None)
            args = self.get_arguments("args")
            if cmd:
                logging.info("hub_commands: %s, %s", cmd, args)
                t = time.strftime("%H:%M:%S")
                self.history.appendleft([t, cmd, args, None])
                Q0.put([cmd, args])
                HC[cmd].append(partial(self.deal_echoed, cmd))
            else:
                self.back()

        def deal_echoed(self, cmd, echo):
            self.history[0][-1] = echo
            if isinstance(echo, str) and echo.startswith("Traceback"):
                self.set_header("Content-Type", "text/plain")
                self.write(echo)
                self.finish()
            else:
                self.commands[cmd](echo)
                self.back()


    class StatusHandler(BaseHandler):
        recorders = {"web": recorder, "hub": {}, "log": {}}
        def get(self, key):
            self.render("status.html", recorder=self.recorders[key])


    class TokenUpdateHandler(BaseHandler):
        def get(self):
            """example:
            wget -O - "localhost:8100/t?_=1&_=key"
            """
            i, t = self.get_arguments("_")
            logging.info("token_generation: %s, %r", i, t)
            tokens[int(i)] = t


    from bb import conn

    conn.tcp(staffs, Q0.put, )().listen(port)
    conn.backdoor(wheels, Q0.put)().listen(backdoor)

    from tornado import autoreload
    #autoreload.start = lambda: None  # monkey patch, i don't like autoreload
    autoreload.add_reload_hook(stop)  # i like autoreload now :)

    Application([
        (r"/dummy", BaseHandler),
        (r"/", MainHandler),
        (r"/t", TokenUpdateHandler),
        (r"/hub", HubHandler),
        (r"/(.*)_status", StatusHandler),
        (r"/ws", conn.websocket(staffs, Q0.put, )),
    ], static_path="_", template_path="tpl", debug=debug).listen(backstage)


    import os
    pid = "bb.pid"
    with open(pid, "w") as f: f.write(str(os.getpid()))

    gc.collect()
    io_loop.start()   # looping...

    logging.info("bye")
    if os.path.exists(pid): os.remove(pid)



if __name__ == "__main__":
    import collections
    import itertools
    import time
    import urllib.parse
    import urllib.request
    from tornado.options import define, options, parse_command_line
    from bb import opt

    for k in dir(opt):
        if k[0].isalpha():
            v = getattr(opt, k)
            define(k, default=v, type=type(v), multiple=isinstance(v, list))

    parse_command_line()

    debug = options.debug = options.logging == "debug"

    zones = options.zones
    if len(set(zones)) != len(zones):
        raise ValueError(zones)

    ports = (options.port, options.backstage, options.backdoor)
    start_time = time.strftime("%y%m%d-%H%M%S")
    args = [("start", start_time)]
    args.extend(zip(itertools.repeat("ports"), ports))
    args.extend(zip(itertools.repeat("zones"), zones))
    args = urllib.parse.urlencode(args)

    def to_leader(key):
        if not debug:
            url = "http://%s/%s?%s" % (options.leader, key, args)
            with urllib.request.urlopen(url) as f:
                print(f.read().decode())

    to_leader("reg")

    main(*ports, debug=debug, options=options)

    to_leader("quit")
