import threading
import socket

from flask import Flask, Response, send_file
from werkzeug.serving import make_server

from app import app, init_db, BASE_DIR
from lan_utils import ensure_lan_certificates, get_lan_ip, qr_png_bytes

LAN_IP = get_lan_ip()
HTTP_PORT = 5000
HTTPS_PORT = 5443
SECURE_URL = f"https://{LAN_IP}:{HTTPS_PORT}"
BOOTSTRAP_URL = f"http://{LAN_IP}:{HTTP_PORT}"
CERTS = ensure_lan_certificates(BASE_DIR, LAN_IP)
bootstrap = Flask("routeops_lan_bootstrap", static_folder=None)


def page_html():
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RouteOps · Conectar móvil</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f7fb;color:#14213d}}main{{max-width:720px;margin:auto;padding:28px 18px 50px}}
.brand{{font-size:28px;font-weight:850}}.sub{{color:#64748b}}.card{{background:#fff;border:1px solid #e5eaf1;border-radius:16px;padding:18px;margin:14px 0}}
.step{{display:flex;gap:14px;align-items:flex-start}}.num{{width:34px;height:34px;border-radius:50%;background:#1769e0;color:#fff;display:grid;place-items:center;font-weight:800;flex:0 0 auto}}
a.btn{{display:inline-block;background:#1769e0;color:#fff;text-decoration:none;padding:12px 15px;border-radius:10px;font-weight:750;margin:5px 5px 5px 0}}a.alt{{background:#fff;color:#334155;border:1px solid #dbe2ea}}
code{{background:#eef2f7;padding:3px 6px;border-radius:6px;word-break:break-all}}img{{width:190px;max-width:55vw}}.warn{{background:#fffbeb;border-color:#fde68a}}small{{color:#64748b;line-height:1.45}}
</style></head><body><main>
<div class="brand">RouteOps <span style="font-size:13px;color:#1769e0">V0.3 SMART DISPATCH</span></div>
<p class="sub">Conecta este teléfono al mismo Wi‑Fi del computador que ejecuta RouteOps.</p>
<div class="card"><div class="step"><span class="num">1</span><div><strong>Instala el certificado local una sola vez</strong><p>Esto permite que cámara, GPS y PWA funcionen por HTTPS dentro de la red local.</p>
<a class="btn alt" href="/routeops-lan-ca.crt">Android / Windows · CA .crt</a><a class="btn alt" href="/routeops-lan-ios.mobileconfig">iPhone / iPad · perfil</a>
<p><small>Android: instala la CA desde Seguridad/Credenciales. iPhone: instala el perfil y después activa confianza total para “RouteOps LAN CA” en Ajustes → General → Información → Ajustes de confianza de certificados.</small></p></div></div></div>
<div class="card"><div class="step"><span class="num">2</span><div><strong>Abre RouteOps seguro</strong><p><code>{SECURE_URL}</code></p><a class="btn" href="{SECURE_URL}">Abrir RouteOps HTTPS</a></div></div></div>
<div class="card warn"><div class="step"><span class="num">3</span><div><strong>Inicia sesión como repartidor</strong><p>Ejemplo: <code>carlos</code> / <code>1234</code>. Cada repartidor utiliza su propia cuenta.</p></div></div></div>
<div class="card"><strong>QR para volver a esta pantalla</strong><br><img src="/qr.png" alt="QR de acceso RouteOps LAN"><p><small>IP del servidor: {LAN_IP}. Si el router cambia la IP del computador, reinicia RouteOps LAN.</small></p></div>
</main></body></html>'''


@bootstrap.get("/")
@bootstrap.get("/lan/setup")
def setup_page():
    return page_html()


@bootstrap.get("/routeops-lan-ca.crt")
def ca_cert():
    return send_file(CERTS["ca_cert"], mimetype="application/x-x509-ca-cert", as_attachment=True, download_name="routeops-lan-ca.crt")


@bootstrap.get("/routeops-lan-ios.mobileconfig")
def ios_profile():
    return send_file(CERTS["ios_profile"], mimetype="application/x-apple-aspen-config", as_attachment=True, download_name="routeops-lan-ios.mobileconfig")


@bootstrap.get("/qr.png")
def qr_image():
    return Response(qr_png_bytes(BOOTSTRAP_URL), mimetype="image/png")


@bootstrap.get("/health")
def bootstrap_health():
    return {"ok": True, "mode": "lan-bootstrap", "lan_ip": LAN_IP, "secure_url": SECURE_URL}


def port_is_free(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def run_bootstrap():
    make_server("0.0.0.0", HTTP_PORT, bootstrap, threaded=True).serve_forever()


def main():
    busy = [str(p) for p in (HTTP_PORT, HTTPS_PORT) if not port_is_free(p)]
    if busy:
        print("\nERROR: los puertos " + ", ".join(busy) + " ya están ocupados.")
        print("Cierra otra instancia de RouteOps/V0.3 y vuelve a ejecutar run_routeops_lan.bat.\n")
        raise SystemExit(2)
    init_db()
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)
    threading.Thread(target=run_bootstrap, name="routeops-bootstrap", daemon=True).start()
    print("\n======================================================")
    print(" RouteOps V0.3 — Smart Dispatch LAN")
    print("======================================================")
    print(f" PC onboarding : http://127.0.0.1:{HTTP_PORT}")
    print(f" Móvil setup   : {BOOTSTRAP_URL}")
    print(f" App HTTPS     : {SECURE_URL}")
    print(" Admin         : admin@routeops.local / demo123")
    print(" Driver        : carlos / 1234")
    print("======================================================")
    print("No abras estos puertos en el router. LAN Pilot es solo red local.\n")
    app.run(host="0.0.0.0", port=HTTPS_PORT, debug=False, threaded=True, use_reloader=False,
            ssl_context=(str(CERTS["server_cert"]), str(CERTS["server_key"])))


if __name__ == "__main__":
    main()
