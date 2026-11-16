"""Console-independent Windows background entry; all diagnostics go to an explicit file."""
from pathlib import Path
import os
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    data=Path(os.environ.get("DAYAN_DATA_DIR", root/"data"))
    data.mkdir(parents=True,exist_ok=True)
    log=(data/"server_dsh.log").open("a",encoding="utf-8",buffering=1)
    sys.stdout=sys.stderr=log
    if sys.stdin is None:sys.stdin=open(os.devnull,encoding="utf-8")
    print(f"DAYAN managed background pid={os.getpid()} root={root}",flush=True)
    import uvicorn
    uvicorn.run("dayan.server:app",host="127.0.0.1",port=int(os.environ.get("DAYAN_PORT","8899")),log_level="info")


if __name__=="__main__":main()
