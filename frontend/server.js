/**
 * Custom Next.js server with robust API proxy to FastAPI backend.
 *
 * The built-in next.config.js rewrites proxy is unreliable for large file
 * uploads and long-running requests (OCR/LLM processing).  This custom server
 * uses Node's http module directly to proxy /api/* requests with no artificial
 * body-size or read-timeout limits.
 */
const http = require('http');
const https = require('https');
const next = require('next');

const dev = process.env.NODE_ENV !== 'production';
const hostname = process.env.HOST || '127.0.0.1';
const port = parseInt(process.env.PORT || '3000', 10);
const BACKEND = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

app.prepare().then(() => {
  // ── Proxy helper ──────────────────────────────────────────────────
  function proxyToBackend(req, res, backendPath) {
    const backendUrl = new URL(BACKEND);
    const client = backendUrl.protocol === 'https:' ? https : http;
    const basePath = backendUrl.pathname.replace(/\/$/, '');

    const options = {
      hostname: backendUrl.hostname,
      port: backendUrl.port || (backendUrl.protocol === 'https:' ? 443 : 80),
      path: `${basePath}${backendPath}`,
      method: req.method,
      headers: { ...req.headers },
      timeout: 300_000, // 5 minutes — OCR+LLM can take a while
    };

    // Remove hop-by-hop / Next.js internal headers
    delete options.headers['host'];
    delete options.headers['connection'];
    delete options.headers['transfer-encoding'];

    const proxyReq = client.request(options, (proxyRes) => {
      // Forward status + headers
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    });

    proxyReq.on('timeout', () => {
      proxyReq.destroy();
      res.writeHead(504, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ detail: '后端处理超时，请重试' }));
    });

    proxyReq.on('error', (err) => {
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ detail: `后端服务不可用: ${err.message}` }));
      }
    });

    // Pipe the client request body through to the backend
    req.pipe(proxyReq);
  }

  // ── Server ────────────────────────────────────────────────────────
  const server = http.createServer((req, res) => {
    // Set a generous timeout on the incoming socket
    req.socket.setTimeout(600_000);

    const parsedUrl = new URL(req.url, `http://${req.headers.host || `${hostname}:${port}`}`);
    const pathname = parsedUrl.pathname;

    // Proxy all /api/* requests to the FastAPI backend
    if (pathname.startsWith('/api/')) {
      proxyToBackend(req, res, req.url);
    } else {
      handle(req, res, {
        pathname,
        query: Object.fromEntries(parsedUrl.searchParams.entries()),
        search: parsedUrl.search,
      });
    }
  });

  server.timeout = 600_000; // 10 minutes global timeout

  server.listen(port, hostname, (err) => {
    if (err) throw err;
    console.log(`> Ready on http://${hostname}:${port} (custom proxy server)`);
    console.log(`> Proxying /api/* to ${BACKEND}`);
  });
});
