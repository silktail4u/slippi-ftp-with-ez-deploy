# sharlots-slippi-ftp-server

sharlots-slippi-ftp-server is a full stack ftp server with a minimal front-end to allow for spectating and replay browsing with Slippi Nintendont, intended for use with this fork:
https://github.com/sticks-stuff/Nintendont/releases

## Features

- Watch live replays with Slippi.TV, Spectatormode.tv, or my fork of Slippi Launcher
- Watch previous finished replays on Slippi Lab or with the Slippi Launcher
- Sort replays into sets and show set score
- Organize replays by console

## Installation

### [Python](https://www.python.org/downloads)

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install requirements.txt.

```bash
pip install -r requirements.txt
```

## Usage
```bash
python sharlots-slippi-ftp-server.py
```
ensure that the following directory exists or update the following line to match your file location
```bash
FTP_ROOT = "/web/sharlot/public_html/slp-files" ##<-- ur file location here
```
to get fileshare working you will also need to update the following line in templates/index.html to point to static file hosting of the above directory

```
https://sharlot.memes.nz/slp-files ## <- change this to ur fileshare address
```

### [Docker](https://www.docker.com/get-started)

Ensure Docker is installed and setup your environment in docker-compose.yaml

```
services:
  slippi-ftp:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        - FSURL=192.168.1.100:40000/slippi ## <- ur fileshare
        - NAME=Tareland ## <- ur ftp name(can be the name of your tournament or smth)
        - USEHTTPS=FALSE ## <- turn on/off https
    container_name: slippi-ftp
    cap_add:
      - NET_BIND_SERVICE
    network_mode: "host"
    volumes:
      - /home/otis/docker/copyparty/copymedia/slippi:/web/sharlot/public_html/slp-files
    restart: unless-stopped
```

## Usage
after setting build args build your container 
```bash
docker compose build
```
once the container is built call
```
docker compose up -d
```
to run in a detatched shell or
```
docker compose up
```
# Debug
to run with debug mode on find the line

```
    app.run(host='0.0.0.0', port=9876, debug=False, use_reloader=False)
```
and change to
```
    app.run(host='0.0.0.0', port=9876, debug=True, use_reloader=False)
```
if using docker you must call docker compose build again
