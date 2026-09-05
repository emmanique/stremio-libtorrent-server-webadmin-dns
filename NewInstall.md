# New Installation Guide

This guide explains how to configure, start, access, and perform an initial validation of the
Stremio LibTorrent Server and its bundled Pi-hole service.

## Prerequisites

Before starting, ensure that:

* Docker and Docker Compose are installed;
* the server has a fixed LAN IP address;
* the required ports are allowed only on the trusted local network;
* port 53 is not already being used by another DNS service.

## 1\. Prepare the configuration

Create the environment file from the provided example and open it for editing:

```bash
cp .env.example .env
nano .env
```

In the `.env` file:

1. Set `IPADDRESS` to the server's fixed LAN IP address.
2. Review `STREMIO\_DATA\_DIR`, which defines the directory or volume used to retain cache data,
settings, certificates, and logs when the container is recreated.

## 2\. Verify that DNS port 53 is available

The package exposes Pi-hole on `53/TCP` and `53/UDP`. Before starting the containers, check whether
port 53 is already in use:

```bash
sudo ss -lntup | grep ':53 '
```

If the command returns no output, port 53 is available. If `systemd-resolved` or another process is
listening on `0.0.0.0:53`, adjust the host's DNS configuration before starting Pi-hole.

## 3\. Build and start the services

Build the images, start the containers in the background, and confirm their status:

```bash
docker compose up -d --build
docker compose ps
```

Confirm that the expected containers are running before continuing.

## 4\. Access the services

Replace `SERVER-IP` with the fixed LAN IP address configured earlier.

|Service|Address|Purpose|
|-|-|-|
|Web Admin|`http://SERVER-IP:8090`|Manage streams, cache, settings, logs, DNS, updates, and restarts|
|Web Player|`http://SERVER-IP:8080`|Access the Stremio web player|
|Direct API|`http://SERVER-IP:11470`|Access the server API directly|
|Pi-hole Admin|`http://SERVER-IP:8053/admin/`|Manage Pi-hole; no password is configured by default|

From Web Admin, you can:

* manage streams and cached content;
* change server settings;
* configure the DNS server used by the Stremio container;
* view logs by source;
* restart the server;
* compare the installed version with the version available on GitHub.

## 5\. Configure Pi-hole as the network DNS server

After Pi-hole is running:

1. Configure the DHCP server or router to distribute this server's fixed IP address as the DNS
server for network clients.
2. Open **All Configuration → Network \& DNS** in Web Admin.
3. Set **DNS Server** to the same fixed IP address if the Stremio container should also use Pi-hole.
4. Restart the Stremio server to apply the DNS change.

Pi-hole management is exposed on `8053/TCP`. Its web interface has no password by explicit design,
so access to port 8053 must be restricted to the trusted LAN through the firewall.

## 6\. Perform the initial validation

Run the following commands to verify container status, inspect recent application logs, test the
API health endpoint, and confirm that Web Admin responds:

```bash
docker compose ps
docker compose logs --tail=100 stremio-libtorrent-server
curl -fsS http://127.0.0.1:11470/health
curl -I http://127.0.0.1:8090/favicon.ico
```

Expected results:

* `docker compose ps` shows the required containers as running;
* the application logs do not show repeated startup errors;
* the health endpoint returns a successful response;
* the Web Admin request returns a successful HTTP status.

## Security requirements

> \*\*Warning:\*\* Do not expose ports `8090` or `8053` directly to the Internet.

* Port `8090` provides administrative functions and has no built-in authentication.
* Port `8053` provides access to a Pi-hole installation whose web interface has no password.
* Restrict both ports to the trusted LAN or protect them with firewall rules and an authenticated
VPN or reverse proxy.

