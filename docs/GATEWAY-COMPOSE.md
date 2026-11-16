# Native Action Core HTTPS/443 Compose service

**Status:** source candidate only. The `gateway` Compose profile is opt-in and has not been started on Windows. It is not a live TLS, network, credential or Gateway acceptance result.

## Service contract

- `action-core-gw` runs the existing application image with `python -m info_hub.gateway_https_server`; this is the dedicated `gateway_read_main:app`, not the local HTTP app and not a proxy.
- The service exposes only TCP/443 to Docker networks. It has no host `ports` binding and no HTTP/8000 listener. The default Compose profile does not start it.
- It joins the existing `feedbrain_default` network for its database dependency and the dedicated `fortis-actioncore-net` internal bridge for the Gateway path. It waits only for PostgreSQL health and deliberately does not invoke the `migrate` service; starting this profile performs no schema migration. The Gateway must join the latter only through its reviewed owner release controller; do not run manual `docker network connect`/`disconnect` commands.
- The `fortis-actioncore-net` is internal. The service does not publish 443 to Windows or the public network.
- The external Docker volume `fortis-actioncore-gateway-tls` is mounted read-only at `/run/action-core-gateway-tls`. It must contain the owner-issued `tls.crt` and `tls.key`. The certificate must have SAN `DNS:action-core-gw`; the private key remains only in the upstream owner runtime. The process runs as UID `10001`: the key must be readable by that UID (for example owner `10001:10001`, mode `0400`), with no group/other permissions; the certificate must be readable by that UID and neither file may be a symlink, hard link or group/world-writable. Both files must be regular files between 128 and 65,536 bytes. The listener fails closed if the files, permissions or verifier are invalid.
- `ACTION_GATEWAY_READ_TOKEN_SHA256` is passed only to `action-core-gw` and is the lowercase SHA-256 verifier, never the raw Bearer. The raw scoped Bearer is held only by the existing Fortis Gateway vault.
- The service runs as UID/GID `10001:10001`, with a read-only root filesystem, `NET_BIND_SERVICE` only, dropped remaining capabilities, no-new-privileges and bounded memory/processes.

## Activation gates — still STOP

The profile is deliberately not enabled by ordinary `docker compose up`. Do not start it or attach the live Gateway until all of the following are independently accepted:

1. The Windows/Docker Desktop owner proves a pre-NAT boundary that blocks **both** Gateway-to-HTTP/8000 paths while preserving Windows `127.0.0.1:8000`. The existing evidence showed HTTP 200 via `host.docker.internal:8000` and direct API IP, and the API observed the same post-NAT peer `192.168.0.1` for Gateway and Windows localhost. This Compose service does not remove the host.docker.internal bypass.
2. The Fortis owner release controller, Guard and tests support the exact reviewed `fortis-actioncore-net` membership. No manual network attachment or weakened Guard.
3. The owner provisions the external TLS volume, certificate/key, public CA and scoped Bearer verifier; Gateway vault ownership and permissions are read back without exposing values.
4. UC-GW-009 global unresolved effects and worker quiescence are resolved/confirmed; isolated restore and the normal owner Check/Apply/Backup/Promote gates pass.
5. From the real Gateway namespace, verify DNS, TLS SAN/CA/expiry, wrong CA/SAN/Host, redirects, bearer 401/403, and denial of both HTTP/8000 paths. Then run the standard UC-GW-012 Doctor and one-shot READ Acceptance.

No compatibility HTTP hop, HTTP proxy, dual transport, redirect, temporary bridge provider or fallback is allowed. Existing local API and workers remain unchanged. This source change alone does not activate `action_core.read_action` or authorize WRITE.

## Offline validation

`tests/test_gateway_compose.py` checks the Compose object model, profile, network, TLS volume, listener port and unchanged local API. It does not create Docker resources, build images, touch PostgreSQL or prove a running network.
