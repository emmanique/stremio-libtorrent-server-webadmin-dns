Web Admin — port 8090

Startup

docker compose up -d --build

Access http://SERVER-IP:8090 from the local network.

Available features

server status, uptime, CPU, memory, and HTTPS certificate;

Web Player and Streaming Server addresses, with quick copy and QR code;

active torrents, progress, speeds, peers, and session removal;

cache usage, including capacity, used/free space, and percentage bar;

consolidated inventory of active and inactive content stored in the cache, with individual
cleanup of stored files;

pinning/unpinning of active torrents;

control of seeding, maximum seed time, simultaneous streams, and bandwidth;

typed editing of all parameters (checkbox for Boolean values and text/number fields for the
remaining values), with an indication of those that require a restart;

controlled container restart;

update execution through an update command defined by the operator.

logs tab separated by source: application/Uvicorn, Nginx, updates, and Web Admin.

Settings are applied at runtime and persisted in the data volume in the
admin-settings.json file.

Logs are stored in the persistent volume at logs/application.log, logs/nginx.log,
logs/container.log, logs/admin.log, and admin-update.log. The Docker container source
contains the combined stream equivalent to the application output shown by docker logs, without
access to the Docker socket. The interface displays the latest 300 lines from each source.

You can clear only the selected source or all sources. The restart button automatically clears
all logs before terminating the process; after startup, the files contain only the new
initialization events.

The debug_logs parameter, available as a checkbox under All configuration, selects the profile:

disabled: application at INFO, Nginx at WARN, and HTTP access logging disabled;

enabled: application/Uvicorn and Nginx at DEBUG, with HTTP access logging enabled.

The change requires a restart. Files are truncated to the most recent 5 MiB during each startup.
Debug mode may log URLs, infohashes, IP addresses, and headers; it should be used only temporarily
and on a trusted LAN.

Controlled update

Set STREMIOSRV_ADMIN_UPDATE_COMMAND in the .env file to a trusted command that is already
available inside the container. The Update now button is enabled only when this variable is
configured. The output is stored in admin-update.log on the persistent volume.

Web Admin is not given direct, unrestricted access to the Docker socket. Such an approach would be
equivalent to granting root privileges on the host to any user with access to port 8090.

Security

Port 8090 performs management operations and does not include its own authentication. It must
remain accessible only from the trusted LAN or behind an authenticated VPN/reverse proxy. Do not
expose the port directly to the Internet.