"""Roda um comando mostrando a saída ao vivo e gravando tudo num log.
  python tee.py <arquivo_log> -- <comando...>"""
import os, subprocess, sys

log = sys.argv[1]
cmd = sys.argv[sys.argv.index("--") + 1:]
os.environ["PYTHONUNBUFFERED"] = "1"
with open(log, "ab") as f:
    f.write(("\n$ " + " ".join(cmd) + "\n").encode("utf-8"))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True:
        bloco = p.stdout.read1(4096)
        if not bloco:
            break
        sys.stdout.buffer.write(bloco); sys.stdout.flush()
        f.write(bloco); f.flush()
sys.exit(p.wait())
