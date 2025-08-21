import os
import time
import threading
import socket
import psutil
from flask import Flask, render_template, render_template_string, jsonify, send_from_directory
from peppi_py import read_slippi, live_slippi_frame_numbers, live_slippi_info
import pyarrow as pa

# Utility function to format timer string for game info
def frame_to_game_timer(frame, starting_timer_seconds=None):
    """
    Returns a string like 'mm:ss.SS' for the timer, or 'Unknown'/'Infinite'.
    timer_type: 'DECREASING', 'INCREASING', or other.
    starting_timer_seconds: int or None
    """
    if starting_timer_seconds is None:
        return "Unknown"
    centiseconds = int(round((((60 - (frame % 60)) % 60) * 99) / 59))
    total_seconds = starting_timer_seconds - frame / 60
    if total_seconds < 0:
        total_seconds = 0
    return f"{int(total_seconds // 60):02}:{int(total_seconds % 60):02}.{centiseconds:02}"

# Utility function to format timer string for game info
def frame_to_game_timer(frame, timer_type, starting_timer_seconds=None):
    """
    Returns a string like 'mm:ss.SS' for the timer, or 'Unknown'/'Infinite'.
    timer_type: 'DECREASING', 'INCREASING', or other.
    starting_timer_seconds: int or None
    """
    if timer_type == "DECREASING":
        if starting_timer_seconds is None:
            return "Unknown"
        centiseconds = int(round((((60 - (frame % 60)) % 60) * 99) / 59))
        total_seconds = starting_timer_seconds - frame / 60
        if total_seconds < 0:
            total_seconds = 0
        return f"{int(total_seconds // 60):02}:{int(total_seconds % 60):02}.{centiseconds:02}"
    elif timer_type == "INCREASING":
        centiseconds = int((frame % 60) * 99 // 59)
        total_seconds = frame / 60
        return f"{int(total_seconds // 60):02}:{int(total_seconds % 60):02}.{centiseconds:02}"
    else:
        return "Infinite"

# Flask app setup
app = Flask(__name__)

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
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

CHARACTER_ID_MAP = {
    0x00: 'captain_falcon',
    0x01: 'donkey_kong',
    0x02: 'fox',
    0x03: 'game_and_watch',
    0x04: 'kirby',
    0x05: 'bowser',
    0x06: 'link',
    0x07: 'luigi',
    0x08: 'mario',
    0x09: 'marth',
    0x0A: 'mewtwo',
    0x0B: 'ness',
    0x0C: 'peach',
    0x0D: 'pikachu',
    0x0E: 'ice_climbers',
    0x0F: 'jigglypuff',
    0x10: 'samus',
    0x11: 'yoshi',
    0x12: 'zelda',
    0x13: 'sheik',
    0x14: 'falco',
    0x15: 'young_link',
    0x16: 'dr_mario',
    0x17: 'roy',
    0x18: 'pichu',
    0x19: 'ganondorf',
    0x1A: 'master_hand',
    0x1B: 'wireframe_male',
    0x1C: 'wireframe_female',
    0x1D: 'giga_bowser',
    0x1E: 'crazy_hand',
    0x1F: 'sandbag',
    0x20: 'popo',
    0x21: 'none'
}
STAGE_ID_MAP = {
    0: 'Dummy',
    1: 'TEST',
    2: 'Fountain of Dreams',
    3: 'Pokémon Stadium',
    4: "Princess Peach's Castle",
    5: 'Kongo Jungle',
    6: 'Brinstar',
    7: 'Corneria',
    8: "Yoshi's Story",
    9: 'Onett',
    10: 'Mute City',
    11: 'Rainbow Cruise',
    12: 'Jungle Japes',
    13: 'Great Bay',
    14: 'Hyrule Temple',
    15: 'Brinstar Depths',
    16: "Yoshi's Island",
    17: 'Green Greens',
    18: 'Fourside',
    19: 'Mushroom Kingdom I',
    20: 'Mushroom Kingdom II',
    22: 'Venom',
    23: 'Poké Floats',
    24: 'Big Blue',
    25: 'Icicle Mountain',
    26: 'Icetop',
    27: 'Flat Zone',
    28: 'Dream Land N64',
    29: "Yoshi's Island N64",
    30: 'Kongo Jungle N64',
    31: 'Battlefield',
    32: 'Final Destination',
}

# NAT Configuration - Set your public IP address here
# You can get your public IP from https://www.whatismyip.com/
# MASQUERADE_ADDRESS = "118.67.199.230"  # Set this to your public IP address (e.g., "123.456.789.012")

# Passive port range for data connections
# PASSIVE_PORTS = range(64739, 64840)  # Ports 64739-64839

def frame_to_game_timer(frame, starting_timer_seconds=None):
    """
    Returns a string like 'mm:ss.SS' for the timer, or 'Unknown'/'Infinite'.
    timer_type: 'DECREASING', 'INCREASING', or other.
    starting_timer_seconds: int or None
    """
    if starting_timer_seconds is None:
        return "Unknown"
    centiseconds = int(round((((60 - (frame % 60)) % 60) * 99) / 59))
    total_seconds = starting_timer_seconds - frame / 60
    if total_seconds < 0:
        total_seconds = 0
    return f"{int(total_seconds // 60):02}:{int(total_seconds % 60):02}.{centiseconds:02}"


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
    import psutil
    pid = os.getpid()
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
                # Get open files for this process
                try:
                    open_files = set(os.path.basename(f.path) for f in psutil.Process(pid).open_files())
                except Exception:
                    open_files = set()
                # Check for files that are growing or open (active transfers)
                for filename, info in current_files.items():
                    is_growing = filename in last_files and info['size'] > last_files[filename]['size']
                    is_open = filename in open_files
                    if is_growing or is_open:
                        # File is growing or open - active transfer
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
                current_file = conn.get('current_file')
                if current_file is None:
                    current_file = ''
                current_file = current_file.replace('Uploading: ', '').replace('Downloading: ', '') or 'connected'
                # Only log when status changes or files change
                if not hasattr(conn, 'last_logged_status') or conn.get('last_logged_status') != (status, current_file):
                    print(f"[{time.strftime('%H:%M:%S')}] {conn['ip']} - {status} - {current_file}")
                    conn['last_logged_status'] = (status, current_file)
        
        time.sleep(5)  # Check less frequently

def main():
    # Check if port 21 is already in use
    import socket as pysocket
    sock = pysocket.socket(pysocket.AF_INET, pysocket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", 21))
        sock.close()
    except OSError:
        print("[ERROR] Port 21 is already in use. FTP server will not start.")
        return
    # Set up FTP server
    authorizer = DummyAuthorizer()
    
    # Add anonymous user with write permissions
    authorizer.add_anonymous(FTP_ROOT, perm="elr")
    
    # You can also add a specific user for Nintendont
    authorizer.add_user("nintendont", "password", FTP_ROOT, perm="elradfmwMT")
    
    handler = MonitoringFTPHandler
    handler.authorizer = authorizer
    # if PASSIVE_PORTS:
    #     handler.passive_ports = PASSIVE_PORTS
    #     print(f"NAT Configuration: Passive ports set to {PASSIVE_PORTS.start}-{PASSIVE_PORTS.stop-1}")
    # if MASQUERADE_ADDRESS:
    #     handler.masquerade_address = MASQUERADE_ADDRESS
    #     print(f"NAT Configuration: Masquerade address set to {MASQUERADE_ADDRESS}")
    # else:
    #     print("NAT Configuration: No masquerade address set - you may need to configure this for NAT/gateway setups")
    upload_monitor_thread = threading.Thread(target=monitor_upload_directory, daemon=True)
    upload_monitor_thread.start()
    monitor_thread = threading.Thread(target=show_active_connections, daemon=True)
    monitor_thread.start()
    server = FTPServer(("0.0.0.0", 21), handler)
    print("FTP Server starting...")
    print("Port 21 - FTP uploads")
    print("Port 9876 - Web interface")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    # Suppress Flask GET request logging
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    # Start FTP server in a background thread, but only call main() once
    ftp_thread = threading.Thread(target=main, daemon=True)
    ftp_thread.start()

    # Flask web server
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/api/replays')
    def api_replays():
        replays = []
        active_filepaths = set()
        # Simple in-memory cache: {filename: (mtime, game_info)}
        if not hasattr(api_replays, "_gameinfo_cache"):
            api_replays._gameinfo_cache = {}
        gameinfo_cache = api_replays._gameinfo_cache


        for conn in MonitoringFTPHandler.active_connections:
            if conn.get('transfer_active') and conn.get('current_file'):
                current_file = conn.get('current_file') or ''
                if 'Uploading:' in current_file:
                    filename = current_file.replace('Uploading:', '').strip()
                    active_filepaths.add(os.path.abspath(filename))
                elif 'Downloading:' in current_file:
                    filename = current_file.replace('Downloading:', '').strip()
                    active_filepaths.add(os.path.abspath(filename))

        # Also consider files open by this process as active (by absolute path)
        try:
            for f in psutil.Process(os.getpid()).open_files():
                active_filepaths.add(os.path.abspath(f.path))
        except Exception as e:
            print(f"[DEBUG] Could not get open files: {e}")

        if os.path.exists(FTP_ROOT):
            for filename in os.listdir(FTP_ROOT):
                filepath = os.path.join(FTP_ROOT, filename)
                if os.path.isfile(filepath) and filename.endswith('.slp'):
                    stat = os.stat(filepath)
                    size_mb = round(stat.st_size / (1024 * 1024), 2)
                    modified_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                    is_active = os.path.abspath(filepath) in active_filepaths
                    cache_key = filename
                    cache_entry = gameinfo_cache.get(cache_key)
                    # Only use cache if not actively transferring and mtime matches
                    if (not is_active and cache_entry and cache_entry[0] == stat.st_mtime):
                        game_info = cache_entry[1]
                    else:
                        stage_id = None
                        stage_name = None
                        players = []
                        game_info = {}
                        try:
                            if is_active:
                                info = live_slippi_info(filepath)
                                frames = list(live_slippi_frame_numbers(filepath))
                                last_frame = frames[-1] if frames else None
                                # Stage info
                                stage_id = int(info['start']['stage']) if info.get('start') and 'stage' in info['start'] else None
                                stage_name = STAGE_ID_MAP.get(stage_id, f"Stage {stage_id}") if stage_id is not None else None
                                if info.get('start', {}).get('is_frozen_ps', False) and stage_name == "Pokémon Stadium":
                                    stage_name = "Frozen Pokémon Stadium"
                                # Player info
                                players = []
                                player_list = info.get('start', {}).get('players', [])
                                player_ports = [p['port'] for p in player_list] if player_list else []
                                min_port = min(player_ports) if player_ports else 0
                                # Get stocks for each player at last_frame if available
                                for idx, p in enumerate(player_list):
                                    char_id = int(p['character'])
                                    costume = int(p['costume'])
                                    char_name = CHARACTER_ID_MAP.get(char_id, f"char_{char_id}")
                                    port_key = 0 if p['port'] == min_port else 1
                                    stocks = None
                                    # Use last_frame's port data if available
                                    try:
                                        if last_frame is not None and hasattr(last_frame, 'ports') and len(last_frame.ports) > port_key:
                                            port_data = last_frame.ports[port_key]
                                            if hasattr(port_data, 'leader') and 'post' in port_data.leader and 'stocks' in port_data.leader['post']:
                                                stocks = port_data.leader['post']['stocks']
                                    except Exception:
                                        stocks = None
                                    icon = f"/icon/chara_2_{char_name}_{str(costume).zfill(2)}.png"
                                    players.append({
                                        'port': p['port'],
                                        'character_id': char_id,
                                        'character': char_name,
                                        'costume': costume,
                                        'stock_count': stocks,
                                        'icon': icon
                                    })
                                # Timer string
                                starting_timer_seconds = info.get('start', {}).get('timer', None)
                                timer_str = "Unknown"
                                if last_frame is not None and hasattr(last_frame, 'id'):
                                    timer_str = frame_to_game_timer(last_frame.id, starting_timer_seconds)
                                # Console name
                                console_name = info.get('metadata', {}).get('consoleNick')
                                game_info = {
                                    'stage_id': stage_id,
                                    'stage_name': stage_name,
                                    'players': players,
                                    'timer': timer_str,
                                    'console_name': console_name
                                }
                            else:
                                game = read_slippi(filepath, skip_frames=False)

                                if hasattr(game, 'start') and hasattr(game.start, 'stage'):
                                    stage_id = int(game.start.stage)
                                if stage_id is not None:
                                    stage_name = STAGE_ID_MAP.get(stage_id, f"Stage {stage_id}")
                                    if game.start.is_frozen_ps and stage_name == "Pokémon Stadium":
                                        stage_name = "Frozen Pokémon Stadium"
                                if hasattr(game, 'start') and hasattr(game.start, 'players'):
                                    # Determine the lowest and highest port among the players
                                    player_ports = [player.port for player in game.start.players]
                                    min_port = min(player_ports)
                                    max_port = max(player_ports)
                                    for p in game.start.players:
                                        char_id = int(p.character)
                                        costume = int(p.costume)
                                        char_name = CHARACTER_ID_MAP.get(char_id, f"char_{char_id}")
                                        # Use ports[0] if this is the lowest port, else ports[1]
                                        if p.port == min_port:
                                            port_key = 0
                                        else:
                                            port_key = 1
                                        stocks = game.frames.ports[port_key].leader.post.stocks[-1].as_py()
                                        icon = f"/icon/chara_2_{char_name}_{str(costume).zfill(2)}.png"
                                        players.append({
                                            'port': p.port,
                                            'character_id': char_id,
                                            'character': char_name,
                                            'costume': costume,
                                            'stock_count': stocks,
                                            'icon': icon
                                        })
                                # Calculate time remaining string
                                timer_str = "Unknown"
                                try:
                                    last_frame = game.frames.id[-1].as_py()
                                    starting_timer_seconds = game.start.timer
                                    if last_frame is not None:
                                        timer_str = frame_to_game_timer(last_frame, starting_timer_seconds)
                                except Exception as e:
                                    timer_str = f"Error: {e}"
                                game_info = {
                                    'stage_id': stage_id,
                                    'stage_name': stage_name,
                                    'players': players,
                                    'timer': timer_str,
                                    'console_name': game.metadata['consoleNick']
                                }
                        except Exception as e:
                            game_info = {'error': str(e)}
                        # Only cache if not actively transferring
                        if not is_active:
                            gameinfo_cache[cache_key] = (stat.st_mtime, game_info)
                    replays.append({
                        'filename': filename,
                        'size_bytes': stat.st_size,
                        'size_mb': size_mb,
                        'modified_time': modified_time,
                        'is_active_transfer': is_active,
                        'game_info': game_info
                    })
        replays.sort(key=lambda x: x['filename'], reverse=True)
        response_data = {
            'total_files': len(replays),
            'active_transfers': len([r for r in replays if r['is_active_transfer']]),
            'replays': replays
        }
        return jsonify(response_data)

    @app.route('/icon/<path:filename>')
    def serve_icon(filename):
        return send_from_directory('icon', filename)

    app.run(host='0.0.0.0', port=9876, debug=False, use_reloader=False)
