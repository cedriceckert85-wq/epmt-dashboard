"""Spawns a detached grandchild that outlives its parent - fixture for the
Windows process-tree kill test (registry: to be wired in Phase 00).
Grandchild writes its PID to --pidfile and sleeps; the harness asserts the
PID is gone after ProcessRunner timeout cleanup."""
import argparse, subprocess, sys, os, time

p=argparse.ArgumentParser()
p.add_argument("--pidfile", required=True)
p.add_argument("--sleep", type=int, default=600)
a=p.parse_args()

flags=0
if os.name=="nt":
    flags=subprocess.CREATE_NEW_PROCESS_GROUP|getattr(subprocess,"DETACHED_PROCESS",0x8)
child=subprocess.Popen([sys.executable,"-c",
    f"import time,os;open(r'{a.pidfile}','w').write(str(os.getpid()));time.sleep({a.sleep})"],
    creationflags=flags, start_new_session=(os.name!="nt"))
time.sleep(a.sleep)
