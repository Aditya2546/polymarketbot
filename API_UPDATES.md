# API Updates - Kalshi RSA Authentication

## Summary

Updated the Kalshi API client to use **RSA key-based authentication** instead of email/password, based on the [official Kalshi API documentation](https://docs.kalshi.com/api-reference/exchange/get-exchange-status).

## Changes Made

### 1. Authentication Method

**Before** (Incorrect):
```python
# Used email + password
client = KalshiClient(
    api_key="user@email.com",
    api_secret="password"
)
```

**After** (Correct per [Kalshi docs](https://docs.kalshi.com/getting_started/api_keys)):
```python
# Uses API Key ID + RSA private key
client = KalshiClient(
    api_key_id="a1b2c3d4-...",
    private_key_path="/path/to/private_key.pem"
)
```

### 2. Updated Files

#### Core Implementation
- **`src/data/kalshi_client.py`**:
  - Added RSA signature generation using `cryptography` library
  - Updated `_authenticate()` to use timestamp + RSA signature
  - Added `_load_private_key()` to load PEM files
  - Updated API URLs to use `api.elections.kalshi.com` (correct endpoint)

#### Configuration
- **`config.template.yaml`**:
  - Changed `api_key` → `api_key_id`
  - Changed `api_secret` → `private_key_path`
  - Updated URLs to correct endpoints
  - Added documentation links

- **`src/config.py`**:
  - Updated property names: `kalshi_api_key_id`, `kalshi_private_key_path`
  - Updated environment variable overrides
  - Updated validation messages with correct credential names

- **`main.py`**:
  - Updated `KalshiClient` initialization to use new parameters

#### Documentation
- **`README.md`**: Updated quick start with correct auth method
- **`GETTING_STARTED.md`**: Detailed RSA key setup instructions
- **`KALSHI_API_SETUP.md`**: New comprehensive guide for API setup
- **`.gitignore`**: Added `*.pem`, `*.key` to prevent committing private keys

### 3. New Dependencies

Added to imports in `kalshi_client.py`:
```python
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
```

Already included in `requirements.txt` via `cryptography>=41.0.0`.

### 4. API Endpoints Corrected

**Before**:
```
https://trading-api.kalshi.com/trade-api/v2
wss://trading-api.kalshi.com/trade-api/ws/v2
```

**After** (per [official docs](https://docs.kalshi.com)):
```
https://api.elections.kalshi.com/trade-api/v2
wss://api.elections.kalshi.com/trade-api/ws/v2
```

### 5. Authentication Flow

#### New Process:
1. Load RSA private key from PEM file
2. Generate current timestamp (milliseconds)
3. Sign timestamp with private key using PKCS1v15 + SHA256
4. Base64 encode signature
5. Send POST to `/login` with:
   ```json
   {
     "key_id": "api-key-id",
     "timestamp": "1704654321000",
     "signature": "base64-encoded-signature"
   }
   ```
6. Receive JWT token in response
7. Use token in `Authorization: Bearer <token>` header for subsequent requests

## Getting Kalshi API Credentials

### Step 1: Go to Kalshi API Settings
Visit: https://kalshi.com/account/api

### Step 2: Generate API Key
1. Click "Generate API Key" or "Create New Key"
2. Kalshi will show you an **API Key ID**
3. Kalshi will download an **RSA private key file** (`.pem`)

### Step 3: Save Credentials
```bash
# Save private key securely
mkdir -p ~/.kalshi
mv ~/Downloads/kalshi_private_key.pem ~/.kalshi/
chmod 600 ~/.kalshi/kalshi_private_key.pem
```

### Step 4: Configure Bot
Edit `config.yaml`:
```yaml
kalshi:
  api_key_id: "your-key-id-from-kalshi"
  private_key_path: "/Users/yourname/.kalshi/kalshi_private_key.pem"
```

## Testing Authentication

Run this test to verify credentials:

```bash
python -c "
from src.config import get_config
from src.data.kalshi_client import KalshiClient
import asyncio

async def test():
    config = get_config()
    client = KalshiClient(
        api_key_id=config.kalshi_api_key_id,
        private_key_path=config.kalshi_private_key_path
    )
    await client.start()
    balance = await client.get_balance()
    print(f'✓ Success! Balance: \${balance}')
    await client.stop()

asyncio.run(test())
"
```

## Migration Guide

If you were using the old (incorrect) authentication:

### Old Config:
```yaml
kalshi:
  api_key: "user@email.com"
  api_secret: "password123"
```

### New Config:
```yaml
kalshi:
  api_key_id: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  private_key_path: "/Users/yourname/.kalshi/kalshi_private_key.pem"
```

### Migration Steps:
1. Generate new API key on Kalshi: https://kalshi.com/account/api
2. Download private key file
3. Update `config.yaml` with new credentials
4. Remove old credentials
5. Test authentication

## Security Notes

### ✅ Good Practices:
- Store private key outside project directory (`~/.kalshi/`)
- Set restrictive permissions: `chmod 600 private_key.pem`
- Add `*.pem` to `.gitignore` (already done)
- Never commit private keys to git
- Use different keys for dev vs production
- Rotate keys periodically

### ❌ Bad Practices:
- Committing private key to git
- Sharing private key files
- Storing private key in cloud storage
- Using same key across multiple systems

## References

- **Kalshi API Docs**: https://docs.kalshi.com
- **API Keys Guide**: https://docs.kalshi.com/getting_started/api_keys
- **Exchange Status**: https://docs.kalshi.com/api-reference/exchange/get-exchange-status
- **Python SDK**: https://docs.kalshi.com/python-sdk
- **Rate Limits**: https://docs.kalshi.com/getting_started/rate_limits

## Troubleshooting

### "Failed to load private key"
- Check file path is absolute, not relative
- Verify file exists: `ls -la /path/to/private_key.pem`
- Check file permissions: `chmod 600 private_key.pem`

### "Authentication failed (401)"
- Verify API Key ID is correct
- Ensure private key matches the Key ID
- Check if key was revoked on Kalshi website

### "Authentication failed (403)"
- Check API key permissions on Kalshi
- Enable required permissions (trading, market data)

## Additional Documentation

See these files for more details:
- **`KALSHI_API_SETUP.md`**: Comprehensive setup guide
- **`GETTING_STARTED.md`**: Updated with correct auth
- **`config.template.yaml`**: Template with new structure

---

**All changes are backward compatible with the rest of the system** - only the Kalshi client authentication method changed. The rest of the bot continues to work as designed.

