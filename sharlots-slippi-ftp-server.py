import os
import time
import threading
import socket
import psutil
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import json

# Configuration
FTP_ROOT = "./ftp-files"

# Ensure FTP directory exists
os.makedirs(FTP_ROOT, exist_ok=True)

class MonitoringFTPHandler(FTPHandler):
    active_connections = []
    active_transfers = []
    
    def on_connect(self):
        connection_info = {
            'ip': self.remote_ip,
            'port': self.remote_port,
            'socket': self.socket,
            'socket_fd': self.socket.fileno(),
            'connected_at': time.time(),
            'username': None,
            'current_file': None,
            'bytes_transferred': 0,
            'transfer_start_time': None,
            'data_socket': None,
            'data_socket_fd': None,
            'transfer_active': False
        }
        MonitoringFTPHandler.active_connections.append(connection_info)
        self.connection_info = connection_info
        print(f"[{time.strftime('%H:%M:%S')}] Connection from {self.remote_ip}")
        
    def on_disconnect(self):
        if hasattr(self, 'connection_info'):
            print(f"[{time.strftime('%H:%M:%S')}] Disconnected: {self.connection_info['ip']}")
            MonitoringFTPHandler.active_connections.remove(self.connection_info)
            
    def on_login(self, username):
        if hasattr(self, 'connection_info'):
            self.connection_info['username'] = username
            print(f"[{time.strftime('%H:%M:%S')}] Login: {username} from {self.connection_info['ip']}")
    
    def on_file_sent(self, file):
        if hasattr(self, 'connection_info'):
            file_size = os.path.getsize(file) if os.path.exists(file) else 0
            self.connection_info['current_file'] = f"Sent: {os.path.basename(file)} ({file_size} bytes)"
            self.connection_info['bytes_transferred'] = file_size
            self.connection_info['transfer_active'] = False
            print(f"[{time.strftime('%H:%M:%S')}] File sent: {os.path.basename(file)} ({file_size} bytes)")
            
    def on_file_received(self, file):
        if hasattr(self, 'connection_info'):
            file_size = os.path.getsize(file) if os.path.exists(file) else 0
            self.connection_info['current_file'] = f"Received: {os.path.basename(file)} ({file_size} bytes)"
            self.connection_info['bytes_transferred'] = file_size
            self.connection_info['transfer_active'] = False
            print(f"[{time.strftime('%H:%M:%S')}] File received: {os.path.basename(file)} ({file_size} bytes)")
    
    # New methods to detect transfer start
    def ftp_STOR(self, line):
        if hasattr(self, 'connection_info'):
            filename = line.strip()
            self.connection_info['current_file'] = f"Uploading: {filename}"
            self.connection_info['transfer_start_time'] = time.time()
            self.connection_info['transfer_active'] = True
            self.connection_info['bytes_transferred'] = 0
        return super().ftp_STOR(line)
    
    def ftp_RETR(self, line):
        if hasattr(self, 'connection_info'):
            filename = line.strip()
            self.connection_info['current_file'] = f"Downloading: {filename}"
            self.connection_info['transfer_start_time'] = time.time()
            self.connection_info['transfer_active'] = True
            self.connection_info['bytes_transferred'] = 0
        return super().ftp_RETR(line)
    
    # Override data connection methods
    def data_channel(self):
        datachannel = super().data_channel()
        if hasattr(self, 'connection_info') and datachannel:
            try:
                # Try to get the data socket file descriptor
                if hasattr(datachannel, 'socket'):
                    data_fd = datachannel.socket.fileno()
                    self.connection_info['data_socket_fd'] = data_fd
                elif hasattr(datachannel, 'sock'):
                    data_fd = datachannel.sock.fileno()
                    self.connection_info['data_socket_fd'] = data_fd
            except Exception as e:
                pass
        return datachannel
            
    def on_incomplete_file_sent(self, file):
        if hasattr(self, 'connection_info'):
            self.connection_info['current_file'] = f"Incomplete send: {os.path.basename(file)}"
            self.connection_info['transfer_active'] = False
            
    def on_incomplete_file_received(self, file):
        if hasattr(self, 'connection_info'):
            self.connection_info['current_file'] = f"Incomplete receive: {os.path.basename(file)}"
            self.connection_info['transfer_active'] = False

class ReplayWebHandler(BaseHTTPRequestHandler):
    """HTTP handler for serving replay files and web interface"""
    
    def log_message(self, format, *args):
        # Suppress default HTTP logging to keep FTP logs clean
        pass
    
    def do_GET(self):
        # Parse the URL
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        
        if path == '/' or path == '/replays':
            # Serve the main replay list page
            self.serve_replay_list()
        elif path.startswith('/api/replays'):
            # Serve JSON API for replay list
            self.serve_replay_api()
        elif path.endswith('.slp'):
            # Serve individual replay file
            filename = os.path.basename(path)
            filepath = os.path.join(FTP_ROOT, filename)
            if os.path.exists(filepath):
                self.serve_file(filepath)
            else:
                self.send_error(404, "Replay file not found")
        else:
            self.send_error(404, "Not found")
    
    def serve_replay_list(self):
        """Serve the HTML page with replay list"""
        html = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>Index of /</title>
    <style type="text/css">i.icon { display: block; height: 16px; width: 16px; }
table tr { white-space: nowrap; }
td.perms {}
td.file-size { text-align: right; padding-left: 1em; }
td.display-name { padding-left: 1em; }
i.icon-_blank {
  background-image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAWBJREFUeNqEUj1LxEAQnd1MVA4lyIEWx6UIKEGUExGsbC3tLfwJ/hT/g7VlCnubqxXBwg/Q4hQP/LhKL5nZuBsvuGfW5MGyuzM7jzdvVuR5DgYnZ+f99ai7Vt5t9K9unu4HLweI3qWYxI6PDosdy0fhcntxO44CcOBzPA7mfEyuHwf7ntQk4jcnywOxIlfxOCNYaLVgb6cXbkTdhJXq2SIlNMC0xIqhHczDbi8OVzpLSUa0WebRfmigLHqj1EcPZnwf7gbDIrYVRyEinurj6jTBHyI7pqVrFQqEbt6TEmZ9v1NRAJNC1xTYxIQh/MmRUlmFQE3qWOW1nqB2TWk1/3tgJV0waVvkFIEeZbHq4ElyKzAmEXOx6gnEVJuWBzmkRJBRPYGZBDsVaOlpSgVJE2yVaAe/0kx/3azBRO0VsbMFZE3CDSZKweZfYIVg+DZ6v7h9GDVOwZPw/PoxKu/fAgwALbDAXf7DdQkAAAAASUVORK5CYII=");
}

i.icon-_page {
  background-image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAmhJREFUeNpsUztv01AYPfdhOy/XTZ80VV1VoCqlA2zQqUgwMEErWBALv4GJDfEDmOEHsFTqVCTExAiiSI2QEKJKESVFFBWo04TESRzfy2c7LY/kLtf2d8+555zvM9NaI1ora5svby9OnbUEBxgDlIKiWjXQeLy19/X17sEtcPY2rtHS96/Hu0RvXXLz+cUzM87zShsI29DpHCYt4E6Box4IZzTnbDx7V74GjhOSfwgE0H2638K9h08A3iHGVbjTw7g6YmAyw/BgecHNGGJjvfQhIfmfIFDAXJpjuugi7djIFVI4P0plctgJQ0xnFe5eOO02OwEp2VkhSCnC8WOCdqgwnzFx4/IyppwRVN+XYXsecqZA1pB48ekAnw9/4GZx3L04N/GoTwEjX4cNH5vlPfjtAIYp8cWrQutxrC5Mod3VsXVTMFSqtaE+gl9dhaUxE2tXZiF7nYiiatJ3v5s8R/1yOCNLOuwjkELiTbmC9dJHpIaGASsDkoFQGJQwHWMcHWJYOmUj1OjvQotuytt5nHMLEGkCyx6QU384jwkUAd2sxJbS/QShZtg/8rHzzQOzSaFhxQrA6YgQMQHojCUlgnCAAvKFBoXXaHfArSCZDE0gyWJgFIKmvUFKO4MUNIk2a4+hODtDUVuJ/J732AKS6ZtImdTyAQQB3bZN8l9t75IFh0JMUdVKsohsUPqRgnka0tYgggYpCHkKGTsHI5NOMojB4iTICCepvX53AIEfQta1iUCmoTiBmdEri2RgddKFhuJoqb/af/yw/d3zTNM6UkaOfis62aUgddAbnz+rXuPY+Vnzjt9/CzAAbmLjCrfBiRgAAAAASUVORK5CYII=");
}
</style>
  </head>
  <body>
<h1>Index of /</h1>
<table id="fileList">
</table>
<br><address id="footer">Enhanced FTP Server running @ 127.0.0.1:9876</address>

<script>
async function loadReplays() {
    try {
        const response = await fetch('/api/replays');
        const data = await response.json();
        
        const listEl = document.getElementById('fileList');
        
        if (data.replays.length === 0) {
            listEl.innerHTML = '<tr><td colspan="5">No files found</td></tr>';
            return;
        }
        
        listEl.innerHTML = data.replays.map(replay => {
            const isActive = replay.is_active_transfer;
            const playUrl = isActive 
                ? `slippi://play?path=http://127.0.0.1:8080/${replay.filename}&mirror=1`
                : `slippi://play?path=http://127.0.0.1:8080/${replay.filename}`;
            
            // Format file size
            let sizeStr;
            if (replay.size_bytes < 1024) {
                sizeStr = replay.size_bytes + 'B';
            } else if (replay.size_bytes < 1024 * 1024) {
                sizeStr = Math.round(replay.size_bytes / 1024 * 10) / 10 + 'k';
            } else {
                sizeStr = Math.round(replay.size_bytes / (1024 * 1024) * 10) / 10 + 'M';
            }
            
            // Format date to match nginx style
            const date = new Date(replay.modified_time);
            const dateStr = date.toLocaleDateString('en-GB', {
                day: '2-digit',
                month: 'short', 
                year: 'numeric'
            }) + ' ' + date.toLocaleTimeString('en-GB', {
                hour: '2-digit',
                minute: '2-digit',
                hour12: false
            });
            
            return `
                <tr>
                    <td><i class="icon icon-_page"></i></td>
                    <td class="perms"><code>(-rw-r--r--)</code></td>
                    <td class="last-modified">${dateStr}</td>
                    <td class="file-size"><code>${sizeStr}</code></td>
                    <td class="display-name">
                        <a href="${playUrl}">${replay.filename}</a>
                        ${isActive ? ' (uploading)' : ''}
                    </td>
                </tr>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Failed to load replays:', error);
        document.getElementById('fileList').innerHTML = '<tr><td colspan="5">Error loading files</td></tr>';
    }
}

// Load replays initially
loadReplays();

// Auto-refresh every 5 seconds
setInterval(loadReplays, 5000);
</script>
</body>
</html>"""
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.send_header('Content-Length', str(len(html.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def serve_replay_api(self):
        """Serve JSON API with replay information"""
        replays = []
        active_files = set()
        
        # Get list of files currently being transferred
        for conn in MonitoringFTPHandler.active_connections:
            if conn.get('transfer_active') and conn.get('current_file'):
                # Extract filename from the transfer info
                current_file = conn.get('current_file', '')
                if 'Uploading:' in current_file:
                    filename = current_file.replace('Uploading:', '').strip()
                    # Remove path if present
                    filename = os.path.basename(filename)
                    active_files.add(filename)
        
        if os.path.exists(FTP_ROOT):
            for filename in os.listdir(FTP_ROOT):
                filepath = os.path.join(FTP_ROOT, filename)
                if os.path.isfile(filepath) and filename.endswith('.slp'):
                    stat = os.stat(filepath)
                    size_mb = round(stat.st_size / (1024 * 1024), 2)
                    modified_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                    
                    replays.append({
                        'filename': filename,
                        'size_bytes': stat.st_size,
                        'size_mb': size_mb,
                        'modified_time': modified_time,
                        'is_active_transfer': filename in active_files
                    })
        
        # Sort by modification time (newest first)
        replays.sort(key=lambda x: x['filename'], reverse=True)
        
        response_data = {
            'total_files': len(replays),
            'active_transfers': len(active_files),
            'replays': replays
        }
        
        json_data = json.dumps(response_data, indent=2)
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Content-Length', str(len(json_data.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(json_data.encode('utf-8'))
    
    def serve_file(self, filepath):
        """Serve a replay file for download"""
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(filepath)}"')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            
        except Exception as e:
            self.send_error(500, f"Error serving file: {str(e)}")

def start_web_server():
    """Start the HTTP server for the web interface"""
    try:
        server = HTTPServer(('0.0.0.0', 9876), ReplayWebHandler)
        server.serve_forever()
    except Exception as e:
        pass

def get_socket_info():
    """Get detailed socket information from the system"""
    try:
        # Try to get connections, but handle permission errors gracefully
        connections = psutil.net_connections(kind='tcp')
        ftp_connections = []
        
        for conn in connections:
            # Skip if no local address
            if not conn.laddr:
                continue
                
            # FTP control connections (port 21)
            if conn.laddr.port == 21:
                ftp_connections.append({
                    'fd': getattr(conn, 'fd', 'N/A'),
                    'local_addr': f"{conn.laddr.ip}:{conn.laddr.port}",
                    'remote_addr': f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                    'status': conn.status,
                    'pid': getattr(conn, 'pid', 'N/A'),
                    'type': 'CONTROL'
                })
            # FTP data connections (typically high ports or port 20)
            elif conn.raddr and conn.status == 'ESTABLISHED':
                # Check if this might be an FTP data connection from known client IPs
                client_ips = [conn_info['ip'] for conn_info in MonitoringFTPHandler.active_connections]
                if conn.raddr.ip in client_ips:
                    # This looks like a data connection from our FTP client
                    ftp_connections.append({
                        'fd': getattr(conn, 'fd', 'N/A'),
                        'local_addr': f"{conn.laddr.ip}:{conn.laddr.port}",
                        'remote_addr': f"{conn.raddr.ip}:{conn.raddr.port}",
                        'status': conn.status,
                        'pid': getattr(conn, 'pid', 'N/A'),
                        'type': 'DATA'
                    })
        
        return ftp_connections
    except psutil.AccessDenied as e:
        return [{'error': f'Permission denied - run with sudo for full socket info (pid={e.pid})'}]
    except Exception as e:
        return [{'error': f'Error getting socket info: {str(e)}'}]

def get_simple_socket_info():
    """Get basic socket information using netstat-like approach"""
    try:
        import subprocess
        # Use netstat to get socket information
        result = subprocess.run(['netstat', '-an'], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            ftp_sockets = []
            for line in lines:
                if ':21 ' in line or (any(ip in line for ip in [conn['ip'] for conn in MonitoringFTPHandler.active_connections])):
                    ftp_sockets.append(line.strip())
            return ftp_sockets
    except:
        pass
    return []

def monitor_upload_directory():
    """Monitor the upload directory for file changes to detect active transfers"""
    last_files = {}
    
    while True:
        try:
            if os.path.exists(FTP_ROOT):
                current_files = {}
                for filename in os.listdir(FTP_ROOT):
                    filepath = os.path.join(FTP_ROOT, filename)
                    if os.path.isfile(filepath):
                        stat = os.stat(filepath)
                        current_files[filename] = {
                            'size': stat.st_size,
                            'mtime': stat.st_mtime
                        }
                
                # Check for files that are growing (active transfers)
                for filename, info in current_files.items():
                    if filename in last_files:
                        if info['size'] > last_files[filename]['size']:
                            # File is growing - active transfer
                            growth = info['size'] - last_files[filename]['size']
                            # Update connection info if we can find it
                            for conn in MonitoringFTPHandler.active_connections:
                                if conn.get('current_file') and filename in conn['current_file']:
                                    conn['bytes_transferred'] = info['size']
                                    conn['transfer_active'] = True
                    
                last_files = current_files.copy()
        except Exception as e:
            pass  # Ignore errors
            
        time.sleep(1)  # Check every second

def show_active_connections():
    # Just log basic info occasionally, no clearing terminal
    while True:
        if MonitoringFTPHandler.active_connections:
            for conn in MonitoringFTPHandler.active_connections:
                status = "active" if conn.get('transfer_active') else "idle"
                current_file = conn.get('current_file', '').replace('Uploading: ', '').replace('Downloading: ', '') or 'connected'
                # Only log when status changes or files change
                if not hasattr(conn, 'last_logged_status') or conn.get('last_logged_status') != (status, current_file):
                    print(f"[{time.strftime('%H:%M:%S')}] {conn['ip']} - {status} - {current_file}")
                    conn['last_logged_status'] = (status, current_file)
        
        time.sleep(5)  # Check less frequently

def main():
    # Set up FTP server
    authorizer = DummyAuthorizer()
    
    # Add anonymous user with write permissions
    authorizer.add_anonymous(FTP_ROOT, perm="elradfmwMT")
    
    # You can also add a specific user for Nintendont
    # authorizer.add_user("nintendont", "password", FTP_ROOT, perm="elradfmwMT")
    
    handler = MonitoringFTPHandler
    handler.authorizer = authorizer
    
    # Create upload directory
    os.makedirs(FTP_ROOT, exist_ok=True)
    
    # Start the upload directory monitor
    upload_monitor_thread = threading.Thread(target=monitor_upload_directory, daemon=True)
    upload_monitor_thread.start()
    
    # Start the connection monitor in a separate thread
    monitor_thread = threading.Thread(target=show_active_connections, daemon=True)
    monitor_thread.start()
    
    # Start the web server in a separate thread
    web_server_thread = threading.Thread(target=start_web_server, daemon=True)
    web_server_thread.start()
    
    # Start FTP server
    server = FTPServer(("0.0.0.0", 21), handler)
    
    print("FTP Server starting...")
    print("Port 21 - FTP uploads")
    print("Port 9876 - Web interface")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    main()
