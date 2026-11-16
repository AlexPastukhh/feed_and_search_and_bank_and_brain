# Native Action Core HTTPS/443 Compose service

**Status:** source candidate only. The `gateway` Compose profile is opt-in and has not been started on Windows. It is not a live TLS, network, credential or Gateway acceptance result.

## Service contract

- `action-core-gw` runs the existing application image with `python -m info_hub.gateway_https_server`; this is the dedicated `gateway_read_main:app`, not the local HTTP app and not a proxy.
- The service exposes only TCP/443 to Docker networks. It has no host `ports` binding and no HTTP/8000 listener. The default Compose profile does not start it.
- It joins only two internal, owner-labelled networks: `fortis-actioncore-net` for the HTTPS Gateway ingress and `fortis-actioncore-db` for PostgreSQL. It does **not** join `feedbrain_default`, where the unauthenticated local API and existing workers remain. The `db` service joins `feedbrain_default` plus `fortis-actioncore-db`; the `api` service remains on `feedbrain_default` only. This lets the ingress query the existing database without sharing a network with the local HTTP API or granting the Gateway direct database-network membership. It waits only for PostgreSQL health and deliberately does not invoke the `migrate` service; starting this profile performs no schema migration. The Fortis Gateway must join `fortis-actioncore-net` only through its reviewed owner release controller and must use a separate `fortis-gateway-egress` user-defined bridge for ordinary egress; do not run manual `docker network connect`/`disconnect` commands.
- Both `fortis-actioncore-net` and `fortis-actioncore-db` are internal bridges with explicit `io.fortis.owner` and `io.fortis.purpose` labels. The service does not publish 443 to Windows or the public network. The Gateway is not a member of the database network; it reaches only the HTTPS ingress.
- The external Docker volume `fortis-actioncore-gateway-tls` is mounted read-only at `/run/action-core-gateway-tls`. It must contain the owner-issued `tls.crt` and `tls.key`. The certificate must have SAN `DNS:action-core-gw`; the private key remains only in the upstream owner runtime. The process runs as UID `10001`: the key must be readable by that UID (for example owner `10001:10001`, mode `0400`), with no group/other permissions; the certificate must be readable by that UID and neither file may be a symlink, hard link or group/world-writable. Both files must be regular files between 128 and 65,536 bytes. The listener fails closed if the files, permissions or verifier are invalid.
- `ACTION_GATEWAY_READ_TOKEN_SHA256` is passed only to `action-core-gw` and is the lowercase SHA-256 verifier, never the raw Bearer. The raw scoped Bearer is held only by the existing Fortis Gateway vault.
- The service runs as UID/GID `10001:10001`, with a read-only root filesystem, `NET_BIND_SERVICE` only, dropped remaining capabilities, no-new-privileges and bounded memory/processes.

## Activation gates — still STOP

The profile is deliberately not enabled by ordinary `docker compose up`. Do not start it or attach the live Gateway until all of the following are independently accepted:

1. The upstream owner deploys the profile only after TLS/vault prerequisites are ready. The Compose topology separates `api` (`feedbrain_default`), ingress (`fortis-actioncore-net`), and database (`fortis-actioncore-db`); the Gateway must not join `feedbrain_default` or `fortis-actioncore-db`.
2. The Fortis owner release controller, Guard and tests must replace the legacy default `bridge` with the dedicated user-defined `fortis-gateway-egress`, attach the Gateway to `fortis-actioncore-net` before start, and admit the exact two-network membership. No manual network attachment or weakened Guard.
3. The Windows owner provisions and verifies an outbound Windows Defender Firewall block for `com.docker.backend.exe` TCP/8000. This blocks Docker Desktop host-service access while leaving Windows-local clients outside that process rule. The rule's scope includes Docker containers' TCP/8000 egress generally and must be accepted as such. The direct container-IP path is addressed separately by the user-defined network split and must be proven blocked from the real Gateway namespace; neither the Firewall rule nor Compose source alone is proof.
3. The owner provisions the external TLS volume, certificate/key, public CA and scoped Bearer verifier; Gateway vault ownership and permissions are read back without exposing values.
4. UC-GW-009 global unresolved effects and worker quiescence are resolved/confirmed; isolated restore and the normal owner Check/Apply/Backup/Promote gates pass.
5. From the real Gateway namespace, verify DNS, TLS SAN/CA/expiry, wrong CA/SAN/Host, redirects, bearer 401/403, denial of `host.docker.internal:8000`, denial of direct API container-IP:8000, and continued Windows `127.0.0.1:8000` access. Then run the standard UC-GW-012 Doctor and one-shot READ Acceptance.

No compatibility HTTP hop, HTTP proxy, dual transport, redirect, temporary bridge provider or fallback is allowed. Existing local API and workers remain unchanged. This source change alone does not activate `action_core.read_action` or authorize WRITE.

## Offline validation

`tests/test_gateway_compose.py` checks the Compose object model, profile, network, TLS volume, listener port and unchanged local API. It does not create Docker resources, build images, touch PostgreSQL or prove a running network.
