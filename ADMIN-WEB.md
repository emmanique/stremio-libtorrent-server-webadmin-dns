# Web Admin — porta 8090

## Arranque

```bash
docker compose up -d --build
```

Aceda a `http://IP-DO-SERVIDOR:8090` a partir da rede local.

## Conteúdo disponível

- estado do servidor, uptime, CPU, memória e certificado HTTPS;
- endereços do Web Player e Streaming Server, com cópia rápida e QR code;
- torrents activos, progresso, velocidades, peers e remoção da sessão;
- utilização da cache com capacidade, espaço usado/livre e barra percentual;
- inventário consolidado de conteúdos activos e inactivos existentes em cache, com limpeza
  individual dos ficheiros armazenados;
- pin/unpin de torrents activos;
- controlo de seeding, tempo máximo de seed, streams simultâneos e largura de banda;
- edição tipada de todos os parâmetros (`checkbox` para booleanos e campo de texto/número para os
  restantes), com indicação dos que exigem reinício;
- reinício controlado do contentor;
- execução de update através de um comando de actualização definido pelo operador.
- aba de logs separados por origem: aplicação/Uvicorn, Nginx, actualizações e Web Admin.

As definições são aplicadas em execução e persistidas no volume de dados no ficheiro
`admin-settings.json`.

Os logs são guardados no volume persistente em `logs/application.log`, `logs/nginx.log`,
`logs/container.log`, `logs/admin.log` e `admin-update.log`. A origem **Docker container** contém o
fluxo combinado equivalente à saída da aplicação apresentada por `docker logs`, sem acesso ao
socket Docker. A interface apresenta as últimas 300 linhas de cada origem.

É possível limpar apenas a origem seleccionada ou todas as origens. O botão de reinício limpa
automaticamente todos os logs antes de terminar o processo; após o novo arranque, os ficheiros
começam apenas com os novos eventos de inicialização.

O parâmetro `debug_logs`, disponível como checkbox em **All configuration**, selecciona o perfil:

- desactivado: aplicação em `INFO`, Nginx em `WARN` e access log HTTP desligado;
- activado: aplicação/Uvicorn e Nginx em `DEBUG`, com access log HTTP activo.

A alteração exige reinício. Os ficheiros são reduzidos para os 5 MiB mais recentes durante cada
arranque. O modo debug pode registar URLs, infohashes, endereços IP e cabeçalhos; deve ser usado
apenas temporariamente e na LAN confiável.

## Actualização controlada

Defina `STREMIOSRV_ADMIN_UPDATE_COMMAND` no ficheiro `.env` com um comando confiável já disponível
dentro do contentor. O botão **Update now** só fica activo quando essa variável está configurada. A
saída é guardada em `admin-update.log`, no volume persistente.

O Web Admin não recebe acesso directo e irrestrito ao socket Docker. Essa abordagem equivaleria a
dar privilégios de root sobre o host a qualquer utilizador com acesso à porta 8090.

## Segurança

A porta 8090 executa operações de gestão e não inclui autenticação própria. Deve permanecer apenas
na LAN confiável ou atrás de VPN/reverse proxy autenticado. Não publique a porta directamente na
Internet.
