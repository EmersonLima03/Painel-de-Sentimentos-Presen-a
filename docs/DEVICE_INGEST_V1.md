# Device Ingest v1

## Function

`ingest-events` @ Sentimentos  
URL: `https://rmiaadljzxyehwyuhhgd.supabase.co/functions/v1/ingest-events`  
`verify_jwt=false` (auth custom via device token).

## Provisionamento

1. Gestor cria `edge_devices` (device_code = DEVICE_ID).
2. Gera token aleatório; armazena **SHA-256 hex** em `device_credentials.token_hash`.
3. Entrega plaintext só ao Edge (`DEVICE_TOKEN`).
4. Revogação: `revoked_at = now()`.

## Auth request

```
POST /functions/v1/ingest-events?token=DEVICE_TOKEN
Authorization: Bearer ANON_KEY
apikey: ANON_KEY
Content-Type: application/json
```

Device só escreve na `school_id` vinculada — mismatch → 403.

## Não aceita

Biometria, frames, vídeo, RTSP.
