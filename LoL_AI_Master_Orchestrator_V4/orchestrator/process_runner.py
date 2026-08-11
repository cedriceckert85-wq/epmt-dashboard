import subprocess, time, os, signal
from dataclasses import dataclass

@dataclass
class ProcessResult:
    exit_code:int
    timed_out:bool
    stdout:str
    stderr:str
    duration_s:float
    cleanup_incomplete:bool=False

class ProcessRunner:
    @staticmethod
    def _close_pipes(p):
        for stream in (p.stdin, p.stdout, p.stderr):
            try:
                if stream: stream.close()
            except Exception:
                pass

    def _kill_tree_windows(self, pid:int):
        return subprocess.run(
            ["taskkill","/PID",str(pid),"/T","/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        ).returncode

    def run(self, argv, *, cwd, timeout_s, env, stdin_text=None):
        start=time.time()
        creationflags=0
        start_new_session=(os.name!="nt")
        if os.name=="nt":
            creationflags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)

        use_stdin = stdin_text is not None

        p=subprocess.Popen(
            argv, cwd=cwd, env=env,
            stdin=subprocess.PIPE if use_stdin else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            start_new_session=start_new_session,
            creationflags=creationflags
        )
        try:
            out,err=p.communicate(stdin_text if use_stdin else None, timeout=timeout_s)
            return ProcessResult(p.returncode,False,out,err,time.time()-start,False)

        except subprocess.TimeoutExpired:
            cleanup_incomplete=False

            if os.name=="nt":
                rc=self._kill_tree_windows(p.pid)
                if rc!=0:
                    cleanup_incomplete=True
                    try: p.kill()
                    except Exception: pass
            else:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception:
                    cleanup_incomplete=True
                    try: p.kill()
                    except Exception: pass

            try:
                out,err=p.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                cleanup_incomplete=True
                try: p.kill()
                except Exception: pass
                try:
                    out,err=p.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    # Fail closed instead of hanging forever; release our pipe
                    # handles so repeated timeouts cannot leak fds/handles.
                    self._close_pipes(p)
                    out=""
                    err="process tree cleanup incomplete after timeout"
                    code=-9
                    return ProcessResult(code,True,out,err,time.time()-start,True)

            code=p.returncode if p.returncode is not None else -9
            return ProcessResult(code,True,out,err,time.time()-start,cleanup_incomplete)
