"""Estúdio GTA 6 como programa: janela PRÓPRIA (WebView2 do Windows, via pywebview) + ícone na bandeja.

Aberto pelo EstudioGTA6.exe (via iniciar.py). Também roda direto:  python ferramentas/scripts/app.py
- Não abre navegador: a tela fica dentro da janela do programa (mesmo motor que Teams/Outlook novo usam).
- Instância única: abrir de novo só traz a janela para a frente.
- Fechar a janela (X) esconde o Estúdio na bandeja, sem interromper lote/envio. Para encerrar: ícone perto do relógio > Sair.
- Se o componente de janela faltar no PC, cai para o Edge em modo aplicativo (aviso no log).
"""
import os, shutil, subprocess, sys, threading, time, urllib.request, webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FERR = AQUI.parent
RAIZ = FERR.parent
PORTA = int(os.environ.get("GTA6_PORTA", "8765"))
URL = f"http://127.0.0.1:{PORTA}"
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EstudioGTA6"
ICONE = FERR / "app" / "icone.ico"
LOG = FERR / "app_log.txt"
ESTADO = {"janela": None, "saindo": False, "icone": None, "srv": None}


def ja_aberto():
    try:
        with urllib.request.urlopen(URL + "/api/estado", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def abrir_pasta(p):
    p = Path(p)
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # noqa
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ------------------------------------------------------------------ janela própria (pywebview)
def mostrar():
    j = ESTADO["janela"]
    if j is None:
        return janela_navegador()
    try:
        j.show(); j.restore()
    except Exception:
        pass


def esconder_ao_fechar():
    """X da janela: só esconde (o trabalho continua). Sair de verdade é pela bandeja."""
    if ESTADO["saindo"] or ESTADO["icone"] is None:     # sem bandeja, o X fecha de verdade
        if not ESTADO["saindo"]:
            ESTADO["saindo"] = True
            threading.Thread(target=ESTADO["srv"].shutdown, daemon=True).start()
        return True
    try:
        ESTADO["janela"].hide()
        ic = ESTADO["icone"]
        if ic is not None and not ESTADO.get("avisou"):
            ic.notify("O Estúdio continua aberto aqui. Para fechar de vez: clique no ícone > Sair.", "Estúdio GTA 6")
            ESTADO["avisou"] = True
    except Exception:
        return True
    return False


def sair(forcar=False):
    if not forcar:
        try:
            import estudio
            import cortes
            if estudio.ocupado() or cortes.live_estado()["rodando"]:
                ic = ESTADO["icone"]
                if ic is not None:
                    ic.notify("Há um trabalho rodando (vídeo/lote/envio/gravação ao vivo). Use 'Sair mesmo assim' para interromper.",
                              "Estúdio GTA 6")
                return
        except Exception:
            pass
    ESTADO["saindo"] = True
    try:                                   # modo ao vivo: fecha a gravação direito (o ffmpeg termina o arquivo)
        import cortes
        threading.Thread(target=cortes.live_encerrar_ao_sair).start()
    except Exception:
        pass
    ic = ESTADO["icone"]
    if ic is not None:
        try:
            ic.visible = False; ic.stop()
        except Exception:
            pass
    if ESTADO["janela"] is not None:
        try:
            ESTADO["janela"].destroy()
        except Exception:
            pass
    threading.Thread(target=ESTADO["srv"].shutdown, daemon=True).start()


def reiniciar():
    """Abre uma nova cópia do programa (que espera esta fechar) e encerra esta. Usado para aplicar atualizações."""
    exe = Path(sys.executable)
    iniciar = exe.resolve().parent.parent / "iniciar.py"          # programa instalado: runtime\python.exe + iniciar.py
    alvo = iniciar if iniciar.exists() else Path(__file__).resolve()
    env = dict(os.environ, GTA6_ESPERAR="1")
    fl = 0x08000000 | 0x00000008 if sys.platform.startswith("win") else 0     # sem janela + desanexado
    try:
        subprocess.Popen([str(exe), str(alvo)], cwd=str(alvo.parent), env=env, creationflags=fl, close_fds=True)
    except Exception as e:
        print(f"falha ao reiniciar: {e}", flush=True)
        return
    sair(True)


def bandeja():
    try:
        import pystray
        from PIL import Image
    except Exception as e:
        print(f"bandeja indisponível ({e})")
        return None
    img = Image.open(ICONE) if ICONE.exists() else Image.new("RGB", (64, 64), (255, 60, 140))
    menu = pystray.Menu(
        pystray.MenuItem("Abrir Estúdio", lambda i, _: mostrar(), default=True),
        pystray.MenuItem("Abrir pasta dos vídeos", lambda i, _: abrir_pasta(RAIZ / "videos")),
        pystray.MenuItem("Abrir pasta de dados", lambda i, _: abrir_pasta(RAIZ)),
        pystray.MenuItem("Ver log do programa", lambda i, _: abrir_pasta(LOG) if LOG.exists() else None),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", lambda i, _: sair()),
        pystray.MenuItem("Sair mesmo assim (interrompe o trabalho)", lambda i, _: sair(True)),
    )
    icon = pystray.Icon("EstudioGTA6", img, "Estúdio GTA 6", menu)
    ESTADO["icone"] = icon
    icon.run_detached()
    return icon


def icone_windows(titulo="Estúdio GTA 6"):
    """Põe o ícone do Estúdio na janela e na barra de tarefas (senão aparece o ícone do Python)."""
    if not sys.platform.startswith("win") or not ICONE.exists():
        return
    import ctypes
    u = ctypes.windll.user32
    for _ in range(40):
        hwnd = u.FindWindowW(None, titulo)
        if hwnd:
            break
        time.sleep(0.25)
    else:
        return
    LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x80
    for tipo, tam in ((1, 256), (0, 32)):          # ICON_BIG, ICON_SMALL
        h = u.LoadImageW(None, str(ICONE), IMAGE_ICON, tam, tam, LR_LOADFROMFILE)
        if h:
            u.SendMessageW(hwnd, WM_SETICON, tipo, h)


def janela_propria():
    """True se abriu a janela do programa (bloqueia até sair); False se o componente não está disponível."""
    try:
        import webview
    except Exception as e:
        print(f"janela própria indisponível ({e}); usando o Edge em modo aplicativo")
        return False
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True                   # "Baixar vídeo", legenda, script do AE
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True    # links do YouTube/Zernio abrem fora
    except Exception:
        pass
    j = webview.create_window("Estúdio GTA 6", URL, width=1440, height=920, min_size=(1000, 650),
                              background_color="#140b1f", text_select=True)
    ESTADO["janela"] = j
    j.events.closing += esconder_ao_fechar
    j.events.shown += lambda: threading.Thread(target=icone_windows, daemon=True).start()
    if sys.platform.startswith("win"):
        try:   # agrupa na barra de tarefas como programa próprio (não como "Python")
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EstudioGTA6.Estudio")
        except Exception:
            pass
    (LOCAL / "janela").mkdir(parents=True, exist_ok=True)
    try:
        webview.start(gui="edgechromium" if sys.platform.startswith("win") else None, private_mode=False,
                      storage_path=str(LOCAL / "janela"), icon=str(ICONE) if ICONE.exists() else None)
    except TypeError:                                                # pywebview mais antigo (sem icon=)
        webview.start(private_mode=False, storage_path=str(LOCAL / "janela"))
    return True


# ------------------------------------------------------------------ plano B: Edge/Chrome em modo app
def janela_navegador():
    cands = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                      Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    nav = next((str(c) for c in cands if c.exists()), None) or shutil.which("msedge") or shutil.which("chrome")
    if nav:
        (LOCAL / "janela_navegador").mkdir(parents=True, exist_ok=True)
        subprocess.Popen([nav, f"--app={URL}", f"--user-data-dir={LOCAL / 'janela_navegador'}",
                          "--window-size=1440,920", "--no-first-run", "--no-default-browser-check"])
    else:
        webbrowser.open(URL)


def reabrir_atualizado():
    """Depois de aplicar uma atualização: abre o programa de novo (já com o código novo) e esta cópia termina."""
    exe = Path(sys.executable)
    iniciar = exe.resolve().parent.parent / "iniciar.py"
    alvo = iniciar if iniciar.exists() else Path(__file__).resolve()
    env = dict(os.environ, GTA6_ATUALIZADO="1")
    fl = 0x08000000 | 0x00000008 if sys.platform.startswith("win") else 0
    subprocess.Popen([str(exe), str(alvo)], cwd=str(alvo.parent), env=env, creationflags=fl, close_fds=True)


def main():
    if os.environ.pop("GTA6_ESPERAR", None):        # reinício: espera a cópia antiga liberar a porta
        for _ in range(40):
            if not ja_aberto():
                break
            time.sleep(0.5)
    if ja_aberto():                     # já está rodando: só traz a janela
        try:
            urllib.request.urlopen(URL + "/api/janela/mostrar", timeout=3).read()
        except Exception:
            janela_navegador()
        return 0
    sys.path.insert(0, str(AQUI))
    os.chdir(RAIZ)
    if not os.environ.pop("GTA6_ATUALIZADO", None):      # atualização automática pelo GitHub (antes da janela)
        try:
            import atualizar
            if atualizar.ao_abrir().get("aplicado"):
                reabrir_atualizado()
                return 0
        except Exception as e:
            print(f"atualizador falhou: {e}", flush=True)
    import estudio
    srv = estudio.servidor(PORTA)
    ESTADO["srv"] = srv
    estudio.AO_MOSTRAR = mostrar
    estudio.AO_REINICIAR = reiniciar
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Estúdio GTA 6 em {URL}  (dados: {RAIZ})", flush=True)
    bandeja()
    if not janela_propria():            # sem componente de janela: Edge em modo app + espera o "Sair" da bandeja
        janela_navegador()
        while not ESTADO["saindo"]:
            time.sleep(0.5)
    if not ESTADO["saindo"]:            # janela fechou por fora (ex.: erro): encerra direito
        sair(True)
    return 0


if __name__ == "__main__":
    if os.environ.get("GTA6_LOG_ARQUIVO") == "1" or not sys.stdout or not sys.stdout.isatty():
        try:
            f = open(LOG, "a", encoding="utf-8", buffering=1)
            f.write(f"\n===== {time.strftime('%d/%m/%Y %H:%M:%S')} =====\n")
            sys.stdout = sys.stderr = f
        except Exception:
            pass
    sys.exit(main())
