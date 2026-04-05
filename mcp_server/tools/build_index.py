# -*- coding: utf-8 -*-
"""build_index tool — triggers indexer on the server with optional full rebuild."""
import asyncio, logging, time, os, signal, re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import log_event

_PID_FILE = Path("/tmp/vporag_build.pid")
_BUILD_TIMEOUT_S = getattr(config, 'BUILD_TIMEOUT_S', 36000)  # 10 hour hard cap


def _kill_stale_build(reason: str) -> dict | None:
    """Kill any process recorded in the PID file. Returns info dict or None."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        try:
            os.kill(pid, signal.SIGKILL)  # ensure it's dead
        except ProcessLookupError:
            pass
        _PID_FILE.unlink(missing_ok=True)
        logging.warning(f"Killed stale build PID {pid}: {reason}")
        log_event("tool_error", tool="build_index", error_type="BuildKilled",
                  error=f"Killed PID {pid}: {reason}")
        return {"killed_pid": pid, "reason": reason}
    except (ValueError, ProcessLookupError):
        _PID_FILE.unlink(missing_ok=True)
        return None


def _is_build_running() -> int | None:
    """Return PID if a build is actively running, else None (cleans stale PID file)."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = existence check only
        return pid
    except (ValueError, ProcessLookupError):
        _PID_FILE.unlink(missing_ok=True)
        return None


async def run(force_full: bool = False) -> dict:
    """Trigger a KB index build on the server.

    Args:
        force_full: Delete processing state before building to force a full rebuild.
    """
    # Kill any existing build before starting a new one
    existing_pid = _is_build_running()
    killed = None
    if existing_pid:
        killed = _kill_stale_build(f"New build requested (force_full={force_full}) — previous build PID {existing_pid} terminated")

    t0 = time.monotonic()
    if force_full:
        state = Path(config.JSON_KB_DIR) / "state" / "processing_state.json"
        state.unlink(missing_ok=True)
        logging.info("Deleted processing state — full rebuild triggered")

    try:
        proc = await asyncio.create_subprocess_exec(
            config.PYTHON_BIN, config.INDEXER_SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(Path(config.INDEXER_SCRIPT).parent),
        )

        _PID_FILE.write_text(str(proc.pid))
        logging.info(f"Build started — PID {proc.pid}, force_full={force_full}")

        # Poll /proc/<pid>/VmRSS every 5s to track peak RSS
        peak_rss_kb = 0

        async def _poll_rss():
            nonlocal peak_rss_kb
            status_path = Path(f"/proc/{proc.pid}/status")
            while proc.returncode is None:
                try:
                    for line in status_path.read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            kb = int(line.split()[1])
                            if kb > peak_rss_kb:
                                peak_rss_kb = kb
                            break
                except Exception:
                    pass
                await asyncio.sleep(5)

        poll_task = asyncio.create_task(_poll_rss())

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_BUILD_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            _PID_FILE.unlink(missing_ok=True)
            poll_task.cancel()
            duration_ms = round((time.monotonic() - t0) * 1000)
            msg = f"Build timed out after {_BUILD_TIMEOUT_S}s — process killed"
            logging.error(msg)
            log_event("tool_error", tool="build_index", error_type="BuildTimeout",
                      error=msg, force_full=force_full, duration_ms=duration_ms)
            return {"status": "error", "message": msg, "killed_previous": killed}

        poll_task.cancel()
        _PID_FILE.unlink(missing_ok=True)

        log = stdout.decode(errors="replace")
        duration_ms = round((time.monotonic() - t0) * 1000)
        peak_rss_mb = round(peak_rss_kb / 1024, 1) if peak_rss_kb else None

        files_processed = 0
        chunks_by_category = {}
        for line in log.splitlines():
            m = re.search(r'Processed (\d+) files?', line)
            if m:
                files_processed = int(m.group(1))
            m = re.search(r'Wrote (\d+) chunks to chunks\.([\w]+)\.jsonl', line)
            if m:
                chunks_by_category[m.group(2)] = int(m.group(1))

        logging.info(f"Build finished — exit code {proc.returncode}, peak RSS {peak_rss_mb} MB")
        log_event("build_index", force_full=force_full,
                  exit_code=proc.returncode, duration_ms=duration_ms,
                  files_processed=files_processed,
                  chunks_by_category=chunks_by_category or None,
                  peak_rss_mb=peak_rss_mb)
        return {"status": "done", "exit_code": proc.returncode,
                "peak_rss_mb": peak_rss_mb, "killed_previous": killed, "log": log}
    except Exception as ex:
        _PID_FILE.unlink(missing_ok=True)
        duration_ms = round((time.monotonic() - t0) * 1000)
        log_event("tool_error", tool="build_index", error_type=type(ex).__name__,
                  error=str(ex), force_full=force_full, duration_ms=duration_ms)
        logging.exception(f"build_index failed: {ex}")
        return {"status": "error", "message": str(ex)}
