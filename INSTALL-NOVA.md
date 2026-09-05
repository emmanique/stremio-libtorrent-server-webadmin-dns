# Instalação nova

## 1. Preparar a configuração

```bash
cp .env.example .env
nano .env
```

Altere `IPADDRESS` para o endereço LAN fixo do servidor. O directório ou volume definido por
`STREMIO_DATA_DIR` guarda cache, definições, certificados e logs entre recriações do contentor.

## 2. Construir e iniciar

```bash
docker compose up -d --build
docker compose ps
```

## 3. Aceder

- Web Admin: `http://IP-DO-SERVIDOR:8090`
- Web Player: `http://IP-DO-SERVIDOR:8080`
- API directa: `http://IP-DO-SERVIDOR:11470`
- Pi-hole: `http://IP-DO-SERVIDOR:8053/admin/` (sem palavra-passe)

No Web Admin pode gerir streams e cache, alterar parâmetros, definir o DNS do contentor, consultar
logs por origem, reiniciar o servidor e comparar a versão instalada com a versão no GitHub.

## Pi-hole e DNS da rede

O pacote publica o Pi-hole em `53/TCP`, `53/UDP` e a gestão em `8053/TCP`. A palavra-passe da
interface está vazia por decisão explícita; limite a porta `8053` à LAN confiável no firewall.

Antes de iniciar, confirme que a porta 53 não está ocupada:

```bash
sudo ss -lntup | grep ':53 '
```

Se `systemd-resolved` estiver a ocupar `0.0.0.0:53`, ajuste a configuração do host antes de iniciar o
Pi-hole. Depois, configure o DHCP/router para distribuir o IP deste servidor como DNS aos clientes.
No separador **All Configuration → Network & DNS**, pode definir o mesmo IP em **DNS Server** para o
contentor Stremio usar também o Pi-hole após reiniciar o servidor.

## 4. Diagnóstico inicial

```bash
docker compose ps
docker compose logs --tail=100 stremio-libtorrent-server
curl -fsS http://127.0.0.1:11470/health
curl -I http://127.0.0.1:8090/favicon.ico
```

Não publique a porta `8090` directamente na Internet. É uma superfície administrativa sem
autenticação própria. A mesma restrição aplica-se à porta `8053`, porque esta instalação do Pi-hole
não tem palavra-passe. Ambas devem ficar limitadas à LAN confiável ou protegidas por firewall/VPN.
