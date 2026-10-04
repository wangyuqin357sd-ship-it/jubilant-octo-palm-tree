#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语忆 · 手机预览服务器（安卓专用）
==============================================================================
为什么需要它：
  `index.html` 本身可以双击直接看，但在**安卓手机**上，
  振动 / 系统通知 / 麦克风 / 唤醒锁 都依赖「安全上下文」，也就是必须 https。
  直接传文件或走 http，会静默退化：振动收不到、通知弹不出来。

  所以这里起两个端口：
    · http  （方便电脑上看）
    · https （手机必须用这个；自签名证书，SAN 里带上当前局域网 IP）

再配合 `sw.js`：Chrome for Android 上 `new Notification()` 会抛 TypeError，
必须用 ServiceWorkerRegistration.showNotification() 才能弹出系统通知。

用法：
    python _tools/serve-mobile.py                # http 8790 + https 8444
    python _tools/serve-mobile.py --https 9443
    python _tools/serve-mobile.py --no-http
"""

import argparse
import datetime
import http.server
import ipaddress
import os
import socket
import ssl
import sys
import threading

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # yuyi-preview/

# 中文输出在 cp936/gbk 控制台下会乱码；统一成 UTF-8（.bat 里也已 chcp 65001）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

CERT_DIR = os.path.join(BASE, '_tools', '.cert')
CERT = os.path.join(CERT_DIR, 'cert.pem')
KEY = os.path.join(CERT_DIR, 'key.pem')
SAN_FILE = os.path.join(CERT_DIR, 'sans.txt')
ADDR_FILE = os.path.join(BASE, '手机地址.txt')

# 只放行这几个文件：不给目录列表，也不把 _shots/ design/ 暴露出去
ALLOW = {
    '/':                      'index.html',
    '/index.html':            'index.html',
    '/sw.js':                 'sw.js',
    # 导出用到的两个零依赖库 + 中文盲文表（只在这几个路径下暴露）
    '/lib/docx-mini.js':      os.path.join('_tools', 'docx-mini.js'),
    '/lib/braille-zh.js':     os.path.join('_tools', 'braille-zh.js'),
    '/data/braille-zh.json':  os.path.join('data', 'braille-zh.json'),
    # 手机端离线语音识别资产（WASM 引擎 + 中文模型 + 页面包装层），全部本地，不走 CDN
    '/data/asr/manifest.json': os.path.join('data', 'asr', 'manifest.json'),
    '/data/asr/yuyi-asr.js':   os.path.join('data', 'asr', 'yuyi-asr.js'),
    '/data/asr/vosk.js':       os.path.join('data', 'asr', 'vosk.js'),
    '/data/asr/model.tar.gz':  os.path.join('data', 'asr', 'model.tar.gz'),
    # 麦克风诊断页（问题定位用，不涉及数据）
    '/diag':                  os.path.join('_tools', 'mic-diagnose.html'),
    '/diag.html':             os.path.join('_tools', 'mic-diagnose.html'),
    # AI Key 实测页（同源 → 能读到手机已保存的配置，用真实 Key 发真请求；不显示完整 Key）
    '/aitest':                os.path.join('_tools', 'ai-key-test.html'),
    '/aitest.html':           os.path.join('_tools', 'ai-key-test.html'),
    '/README-预览说明.md':     'README-预览说明.md',
}


# ---------------------------------------------------------------- 局域网地址
def lan_ips():
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith('127.') and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    # 兜底：朝外网方向探一次本地出口地址（不会真的发包）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith('127.') and ip not in ips:
            ips.append(ip)
    except Exception:
        pass
    return [ip for ip in ips if not ip.startswith('169.254.')]


def rank(ip):
    # 按八位组判断，避免在源码里写出完整的私有网段字面量
    _o = ip.split('.')
    if len(_o) == 4 and _o[0] == '192' and _o[1] == '168':
        return 0          # 家用 WiFi / 热点，最可能
    if ip.startswith('10.'):
        return 1
    if ip.startswith('172.'):
        return 3          # 多半是 WSL / Hyper-V 虚拟网卡
    return 2


def ranked_ips():
    return sorted(lan_ips(), key=rank)


# ---------------------------------------------------------------- 自签名证书
def ensure_cert():
    """签发/更新自签名证书；SAN 里带上当前局域网 IP，手机才不会直接拒连。"""
    os.makedirs(CERT_DIR, exist_ok=True)
    ips = ranked_ips()
    want = ','.join(ips)
    if os.path.exists(CERT) and os.path.exists(KEY) and os.path.exists(SAN_FILE):
        have = open(SAN_FILE, encoding='utf-8').read().strip()
        if have == want:
            return
        print('  · 局域网地址变了（%s → %s），重新签发证书' % (have, want))
        for f in (CERT, KEY, SAN_FILE):
            try:
                os.remove(f)
            except OSError:
                pass

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san = [x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]
    for ip in ips:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except Exception:
            pass
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'yuyi-mobile-preview')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    with open(CERT, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(KEY, 'wb') as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(SAN_FILE, 'w', encoding='utf-8') as f:
        f.write(want)
    print('  · 已签发自签名证书（SAN: %s）' % (want or 'localhost'))


# ---------------------------------------------------------------- HTTP 处理
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'YuyiMobilePreview/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        sys.stderr.write('  %s\n' % (fmt % args))

    def _send(self, code, body=b'', ctype='text/plain; charset=utf-8', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        # 预览用：别缓存，改完刷新就能看到
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/favicon.ico':
            return self._send(204)
        name = ALLOW.get(path)
        if name is None:
            return self._send(404, ('没有这个文件：%s\n\n可用：/\n' % path).encode('utf-8'))
        full = os.path.join(BASE, name)
        if not os.path.isfile(full):
            return self._send(404, ('文件不存在：%s\n' % name).encode('utf-8'))
        ctype = ('text/html; charset=utf-8' if name.endswith('.html')
                 else 'text/javascript; charset=utf-8' if name.endswith('.js')
                 else 'application/json; charset=utf-8' if name.endswith('.json')
                 else 'application/gzip' if name.endswith('.gz')
                 else 'text/markdown; charset=utf-8')
        extra = {}
        if name == 'sw.js':
            extra['Service-Worker-Allowed'] = '/'
        with open(full, 'rb') as f:
            data = f.read()
        return self._send(200, data, ctype, extra)

    do_HEAD = do_GET


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """浏览器/命令行客户端刷新或提前断连会抛 ConnectionReset，属正常现象。
        不拦的话 socketserver 会把整段堆栈打到控制台，把预览窗口刷得很难看。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def bind_first(port, tries, label):
    """端口被占就顺延，别静默失败。"""
    for i in range(tries):
        p = port + i
        try:
            return Server(('0.0.0.0', p), Handler), p
        except OSError:
            if i == 0:
                print('  ! %s 端口 %d 被占用，顺延尝试…' % (label, p))
            continue
    raise SystemExit('  ! %s 从 %d 起 %d 个端口都占用了' % (label, port, tries))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--http', type=int, default=8790)
    ap.add_argument('--https', type=int, default=8444)
    ap.add_argument('--no-http', action='store_true')
    ap.add_argument('--no-https', action='store_true')
    args = ap.parse_args()

    print()
    print('  语忆 · 手机预览服务器')
    print('  ' + '=' * 58)

    if not os.path.isfile(os.path.join(BASE, 'index.html')):
        raise SystemExit('  ! 找不到 index.html，确认本脚本在 _tools/ 下')

    started = []
    if not args.no_https:
        try:
            ensure_cert()
        except Exception as e:
            print('  ! 证书生成失败（%s）' % e)
            print('    先执行：pip install cryptography')
            print('    —— 没有 https，手机端振动/通知/麦克风都会拿不到，强烈建议修好')
            args.no_https = True

    if not args.no_http:
        srv, p = bind_first(args.http, 10, 'http')
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(('http', p, srv))

    if not args.no_https:
        srv, p = bind_first(args.https, 10, 'https')
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, KEY)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(('https', p, srv))

    https_port = next((p for kind, p, _ in started if kind == 'https'), None)
    http_port = next((p for kind, p, _ in started if kind == 'http'), None)
    ips = ranked_ips()

    print()
    if ips:
        print('  【手机浏览器打开这个】')
        for i, ip in enumerate(ips):
            if https_port:
                mark = '  ← 优先用这个' if i == 0 else '  ← 打不开再试'
                print('      https://%s:%d/%s' % (ip, https_port, mark))
        print()
        print('  首次会提示「连接不安全」（自签名证书，数据只在你的电脑和手机之间走）：')
        print('      点「高级」→「继续前往 %s（不安全）」' % (ips[0]))
        print()
        if http_port:
            print('  【电脑上快速看】 http://127.0.0.1:%d/' % http_port)
            print('     电脑上这个地址能力是**全的**：Chrome 把 127.0.0.1 当可信来源，')
            print('     安全上下文/通知/Service Worker 都有（实测 isSecureContext=true）。')
            print('     但换成局域网 IP 走 http（http://<电脑IP>:%d/）就只剩界面，' % http_port)
            print('     没有振动/通知/麦克风——手机请务必用上面的 https。')
    else:
        print('  ! 没探到局域网 IP：请确认手机和电脑连的是同一个 WiFi / 热点')

    if https_port:
        print()
        print('  【手机上按顺序做这 4 步，功能才完整】')
        print('    1. 打开上面的 https 地址 → 高级 → 继续前往')
        print('    2. 点一下页面任意位置      ← 浏览器要求先有交互，振动才会生效')
        print('    3. 待办面板里开「浏览器通知」并在弹窗点「允许」')
        print('    4. 浏览器菜单「添加到主屏幕」，再允许浏览器后台运行')

    # 写一份地址文件，方便回头再查（沿用本项目既有做法）
    try:
        lines = ['语忆 · 手机预览地址', '=' * 44, '']
        for ip in ips:
            if https_port:
                lines.append('  手机浏览器打开：https://%s:%d/' % (ip, https_port))
            else:
                lines.append('  （无 https）http://%s:%d/' % (ip, http_port or 0))
        lines += ['', '  首次提示「连接不安全」→ 点「高级」→「继续前往」。',
                  '  打开后先点一下页面，振动才会生效。', '']
        if http_port:
            lines.append('  电脑上打开：http://127.0.0.1:%d/' % http_port)
        # utf-8-sig：带 BOM，老版「记事本」才不会把中文显示成乱码
        with open(ADDR_FILE, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines) + '\n')
        print()
        print('  地址已写入：%s' % ADDR_FILE)
    except Exception as e:
        print('  ! 写地址文件失败：%s' % e)

    print()
    print('  服务在跑，按 Ctrl+C 停止。')
    print()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print('  已停止。')


if __name__ == '__main__':
    main()