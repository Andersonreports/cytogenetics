"""Start the CMC Cytogenetics report tool and open it in the browser.

    python -m backend.main               this computer only (http://127.0.0.1:5200)
    python -m backend.main --lan         also reachable from other computers on the LAN
    python -m backend.main --port 5300 --no-browser
    python -m backend.main --reset-password NAME   new password for a user (e.g. a locked-out
                                                   admin); a new name is added as an admin
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


def _reset_password(name: str) -> None:
    """For the PC's own console: no admin can sign in any more."""
    import getpass
    from backend import auth

    try:
        name = auth.clean_name(name)
        pw = getpass.getpass(f"New password for '{name}': ")
        if pw != getpass.getpass("Again: "):
            raise auth.AuthError("The two passwords are not the same.")
        if name in auth.load_users():
            auth.set_password(name, pw)
            print(f"Password of '{name}' changed (in {auth.data_dir()}).")
        else:
            auth.create_user(name, pw, admin=True)
            print(f"Admin '{name}' added (in {auth.data_dir()}).")
    except auth.AuthError as e:
        print(f"Not changed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CMC Cytogenetics report tool")
    parser.add_argument("--lan", action="store_true", help="serve to other computers on the network")
    parser.add_argument("--port", type=int, default=5200)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--reset-password", metavar="NAME",
                        help="set a user's password (adds NAME as an admin if new) and exit")
    args = parser.parse_args()
    if args.reset_password:
        _reset_password(args.reset_password)
        return

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
