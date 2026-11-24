"""Start the CMC Cytogenetics report tool and open it in the browser.

    python -m backend.main               this computer only (http://127.0.0.1:5200)
    python -m backend.main --lan         also reachable from other computers on the LAN
    python -m backend.main --port 5300 --no-browser
"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(description="CMC Cytogenetics report tool")
    parser.add_argument("--lan", action="store_true", help="serve to other computers on the network")
    parser.add_argument("--port", type=int, default=5200)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = parser.parse_args()

    from werkzeug.serving import make_server
    from backend.server import app      # absolute: the exe runs this file as a script

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    url = f"http://127.0.0.1:{args.port}/"
    print("CMC Cytogenetics report tool")
    print(f"  Open {url}" + (f"  (LAN: http://{_lan_ip()}:{args.port}/)" if args.lan else ""))
    print("  Close this window to stop it.")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server = make_server(host, args.port, app, threaded=True)
    except OSError:
        print(f"\nPort {args.port} is already in use - is the tool already running? "
              f"Open {url}, or start with --port <another number>.")
        if not args.no_browser:
            webbrowser.open(url)
        return
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
